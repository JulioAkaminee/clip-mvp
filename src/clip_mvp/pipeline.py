"""Orquestração do pipeline completo (SPEC §6, §12). Liga todos os módulos.

Cada estágio reporta andamento em um :class:`~clip_mvp.progress.ProgressReporter`,
que é a única fonte de verdade de progresso para a CLI, a API HTTP e a UI web.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import audio as audio_mod
from . import face_track as face_track_mod
from . import meta as meta_mod
from . import render as render_mod
from . import subtitles as subtitles_mod
from .budget import apply_budget, estimate_cost
from .candidates import generate_candidates, resolve_target_range
from .config import Settings
from .dedupe import DedupeItem, dedupe_items
from .diarization import (
    resolve_diarization,
    resolve_speaker_matching_method,
    speaker_timeline,
    uses_dedicated_pass,
)
from .download import download_source, probe_metadata
from .feedback import load_recent_feedback, write_selected_index
from .models import Candidate, DiarizationResult, Score, Transcript
from .openrouter import OpenRouterClient
from .progress import ClipProgress, ProgressReporter
from .score import score_candidates
from .transcribe import dump_transcript, load_transcript, transcribe_audio
from .utils import ffprobe_duration
from .utils import job_dir as make_job_dir
from .utils import make_job_id, out_clip_dir, read_json, slugify, write_json

DEFAULT_FORMATS = ["face", "9x16", "16x9"]
DEFAULT_PLATFORMS = ["yt", "tiktok"]
DEFAULT_CAPTIONS = "both"


@dataclass
class RunOptions:
    more: bool = False
    count: int | None = None
    min_score: float | None = None
    max_score_only: float | None = None
    formats: list[str] = field(default_factory=lambda: list(DEFAULT_FORMATS))
    captions: str = DEFAULT_CAPTIONS
    platforms: list[str] = field(default_factory=lambda: list(DEFAULT_PLATFORMS))
    dry_run: bool = False
    budget: float | None = None


@dataclass
class JobSummary:
    job_id: str
    candidates: int = 0
    deduped_removed: int = 0
    selected: int = 0
    vertical_ok: int = 0
    vertical_skipped: int = 0
    min_score: float = 0.0
    #: Cortes que passaram do limiar absoluto mas ficaram muito abaixo do melhor
    #: deste vídeo (SPEC §3.5: qualidade > quantidade).
    below_floor_removed: int = 0
    quality_floor: float | None = None
    dry_run: bool = False
    cost_estimate: dict[str, Any] | None = None
    budget_warning: str | None = None
    clips: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _job_paths(work_dir: Path, job_id: str) -> dict[str, Path]:
    jdir = make_job_dir(work_dir, job_id)
    return {
        "dir": jdir,
        "video": jdir / "source.mp4",
        "audio": jdir / "source_audio.wav",
        "transcript": jdir / "transcript.json",
        "candidates": jdir / "candidates.json",
        "diarization": jdir / "diarization.json",
        "frames": jdir / "frames",
    }


def _ensure_download(
    url: str,
    settings: Settings,
    paths: dict[str, Path],
    *,
    on_progress: Callable[[float, str], None] | None = None,
) -> Path:
    if paths["video"].exists():
        if on_progress:
            on_progress(1.0, "Vídeo já baixado (cache)")
        return paths["video"]
    result = download_source(
        url, paths["dir"], height=settings.download_height, on_progress=on_progress
    )
    if result.video_path != paths["video"]:
        result.video_path.replace(paths["video"])
    return paths["video"]


def _ensure_audio(video_path: Path, paths: dict[str, Path]) -> Path:
    if paths["audio"].exists():
        return paths["audio"]
    return audio_mod.extract_audio(video_path, paths["audio"])


def _ensure_transcript(
    audio_path: Path,
    settings: Settings,
    paths: dict[str, Path],
    *,
    client: OpenRouterClient | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> Transcript:
    if paths["transcript"].exists():
        return load_transcript(paths["dir"])
    transcript = transcribe_audio(audio_path, settings, client=client, on_progress=on_progress)
    dump_transcript(transcript, paths["dir"])
    return transcript


def _ensure_candidates(
    transcript: Transcript,
    settings: Settings,
    paths: dict[str, Path],
    *,
    target_hi: int,
    client: OpenRouterClient | None = None,
    feedback_examples: list[dict] | None = None,
    force_regenerate: bool = False,
) -> list[Candidate]:
    if paths["candidates"].exists() and not force_regenerate:
        raw = read_json(paths["candidates"])
        return [Candidate.model_validate(c) for c in raw]

    candidates = generate_candidates(
        transcript,
        settings,
        target_hi=target_hi,
        client=client,
        feedback_examples=feedback_examples,
    )
    write_json(paths["candidates"], [c.model_dump() for c in candidates])
    return candidates


def _ensure_diarization(
    transcript: Transcript,
    audio_path: Path,
    settings: Settings,
    paths: dict[str, Path],
    *,
    client: OpenRouterClient | None = None,
) -> DiarizationResult:
    """Timeline de falantes (cache em work/<job_id>/diarization.json, SPEC §14.4).

    Prefere os speaker labels da própria transcrição (grátis) e só cai numa
    passada dedicada quando o papel de diarização aponta para outro modelo — que
    é o usuário dizendo "este modelo sabe separar falantes". Essa passada reusa o
    chunking da transcrição (SPEC §15) e está na estimativa de custo (SPEC §14.4).
    """
    if paths["diarization"].exists():
        try:
            return DiarizationResult.model_validate(read_json(paths["diarization"]))
        except Exception:  # noqa: BLE001 - cache velho/corrompido recalcula
            pass

    result = resolve_diarization(transcript, audio_path, settings, client=client)
    write_json(paths["diarization"], result.model_dump())
    return result


@dataclass
class SelectionOutcome:
    selected: list[tuple[Candidate, Score]] = field(default_factory=list)
    deduped_removed: int = 0
    below_floor_removed: int = 0
    quality_floor: float | None = None


def _apply_relative_floor(
    passing: list[tuple[Candidate, Score]],
    *,
    relative_gap: float | None,
    keep_at_least: int,
) -> tuple[list[tuple[Candidate, Score]], int, float | None]:
    """Corta o que ficou muito abaixo do melhor corte do job (SPEC §3.5).

    O limiar absoluto (``min_score``) responde "isso é publicável?". Ele não
    responde "isso presta ao lado do resto deste vídeo": num podcast com um
    momento de 92, entregar também um de 61 só porque passou do limiar dilui o
    lote e é exatamente o "corte mediano" que a spec pede para evitar
    ("qualidade > quantidade").

    Nunca desce abaixo do piso da faixa alvo da SPEC §3, e ``relative_gap=None``
    desliga a regra (é o caso de ``--count N``, em que o usuário pediu um número
    explícito).
    """
    if relative_gap is None or relative_gap <= 0 or len(passing) <= max(1, keep_at_least):
        return passing, 0, None

    best = passing[0][1].total
    floor = best - relative_gap
    kept = [cs for cs in passing if cs[1].total >= floor]
    if len(kept) < keep_at_least:
        kept = passing[:keep_at_least]
    return kept, len(passing) - len(kept), round(floor, 2)


def _select_clips(
    scored: list[tuple[Candidate, Score]],
    *,
    min_score: float,
    max_score_only: float | None,
    count_cap: int,
    keep_at_least: int = 1,
    relative_gap: float | None = None,
) -> SelectionOutcome:
    """Aplica limiar + dedupe (por score) + piso relativo + teto (SPEC §3)."""
    items = [
        DedupeItem(
            item=(c, s),
            start=c.window_16x9.start,
            end=c.window_16x9.end,
            text=c.text_excerpt,
            score=s.total,
            alt_start=c.window_9x16.start if c.window_9x16 else None,
            alt_end=c.window_9x16.end if c.window_9x16 else None,
        )
        for c, s in scored
    ]
    dedupe_result = dedupe_items(items)
    deduped = dedupe_result.kept

    threshold = max_score_only if max_score_only is not None else min_score
    passing = [(c, s) for c, s in deduped if s.total >= threshold]
    passing.sort(key=lambda cs: cs[1].total, reverse=True)
    passing = passing[:count_cap]

    kept, below_floor, floor = _apply_relative_floor(
        passing, relative_gap=relative_gap, keep_at_least=min(keep_at_least, count_cap)
    )
    return SelectionOutcome(
        selected=kept,
        deduped_removed=dedupe_result.removed_count,
        below_floor_removed=below_floor,
        quality_floor=floor,
    )


def make_reporter(settings: Settings, job_id: str, **kwargs: Any) -> ProgressReporter:
    """Cria um reporter que persiste status/eventos em ``work/<job_id>/``."""
    jdir = make_job_dir(settings.work_dir, job_id)
    kwargs.setdefault("heartbeat_interval", settings.progress_heartbeat_s)
    return ProgressReporter(
        job_id,
        status_path=jdir / "status.json",
        events_path=jdir / "events.jsonl",
        **kwargs,
    )


def run_job(
    url: str,
    settings: Settings,
    options: RunOptions,
    *,
    client: OpenRouterClient | None = None,
    reporter: ProgressReporter | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> JobSummary:
    job_id = make_job_id(url)
    return _run_or_resume(
        job_id,
        url,
        settings,
        options,
        client=client,
        is_resume=False,
        reporter=reporter,
        cancel_check=cancel_check,
    )


def resume_job(
    job_id: str,
    settings: Settings,
    options: RunOptions,
    *,
    client: OpenRouterClient | None = None,
    reporter: ProgressReporter | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> JobSummary:
    return _run_or_resume(
        job_id,
        None,
        settings,
        options,
        client=client,
        is_resume=True,
        reporter=reporter,
        cancel_check=cancel_check,
    )


class JobCanceled(RuntimeError):
    """Levantada quando o usuário cancela um job em andamento."""


def _hint_for(exc: BaseException) -> str:
    """Dica acionável em PT-BR — a UI nunca deve mostrar só o stack trace."""
    text = str(exc).lower()
    if "openrouter_api_key" in text:
        return "Configure OPENROUTER_API_KEY no .env e rode de novo."
    if "429" in text or "rate limit" in text:
        return "Limite de taxa da OpenRouter. Espere um pouco e rode `clip resume <job_id>`."
    if "yt-dlp" in text or "unavailable" in text:
        return "Confira se a URL está acessível e se o yt-dlp está atualizado."
    if "ffmpeg" in text or "ffprobe" in text:
        return "Verifique se o ffmpeg está instalado (`brew install ffmpeg`)."
    return "Rode `clip resume <job_id>` para continuar de onde parou (o cache é preservado)."


def _run_or_resume(
    job_id: str,
    url: str | None,
    settings: Settings,
    options: RunOptions,
    *,
    client: OpenRouterClient | None,
    is_resume: bool,
    reporter: ProgressReporter | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> JobSummary:
    reporter = reporter or make_reporter(settings, job_id)
    # Vários estágios são uma única chamada bloqueante (um prompt sobre a
    # transcrição inteira, um ffmpeg por arquivo): sem batimento o ETA congela
    # justamente nos trechos em que o usuário mais precisa saber que algo anda.
    reporter.start_heartbeat()
    try:
        return _execute(
            job_id,
            url,
            settings,
            options,
            client=client,
            is_resume=is_resume,
            reporter=reporter,
            cancel_check=cancel_check or (lambda: False),
        )
    except JobCanceled:
        reporter.cancel()
        raise
    except Exception as exc:  # noqa: BLE001 - o estado de erro precisa chegar à UI
        reporter.fail(exc, hint=_hint_for(exc))
        raise
    finally:
        reporter.stop_heartbeat()


def _execute(
    job_id: str,
    url: str | None,
    settings: Settings,
    options: RunOptions,
    *,
    client: OpenRouterClient | None,
    is_resume: bool,
    reporter: ProgressReporter,
    cancel_check: Callable[[], bool],
) -> JobSummary:
    paths = _job_paths(settings.work_dir, job_id)
    summary = JobSummary(job_id=job_id)
    client = client or OpenRouterClient(settings)

    def check_cancel() -> None:
        if cancel_check():
            raise JobCanceled("job cancelado pelo usuário")

    if is_resume:
        if not paths["transcript"].exists():
            raise RuntimeError(
                f"Job {job_id} não tem transcrição em cache; use `clip \"URL\"` para iniciar do zero."
            )
        job_meta_path = paths["dir"] / "job.json"
        source_url = read_json(job_meta_path).get("source_url", "") if job_meta_path.exists() else ""
        reporter.skip_stage("download", "Vídeo e áudio reaproveitados do cache")
    else:
        assert url is not None
        source_url = url
        write_json(paths["dir"] / "job.json", {"source_url": url, "job_id": job_id})
        # Duração conhecida antes do primeiro byte: sem isso o ETA passaria o
        # download inteiro sem ter o que estimar.
        _seed_duration_estimate(url, reporter)

        reporter.start_stage("download", units_total=1)
        video_path = _ensure_download(
            url,
            settings,
            paths,
            on_progress=lambda frac, msg: reporter.update("download", frac * 0.9, msg),
        )
        reporter.update("download", 0.95, "Extraindo áudio para transcrição…")
        _ensure_audio(video_path, paths)
        reporter.finish_stage("download", "Vídeo e áudio prontos")

    video_path = paths["video"]
    audio_path = paths["audio"]

    # Duração é conhecida sem precisar transcrever (ffprobe no vídeo baixado,
    # ou a transcrição já cacheada em `resume`). Isso permite que --dry-run e
    # --budget decidam ANTES de pagar por STT/candidatos/vision (SPEC §14.4).
    if paths["transcript"].exists():
        duration_s = load_transcript(paths["dir"]).duration
    else:
        duration_s = ffprobe_duration(video_path)
    reporter.set_source_minutes(duration_s / 60.0)

    min_score = options.min_score if options.min_score is not None else settings.min_score_default
    summary.min_score = options.max_score_only if options.max_score_only is not None else min_score

    target_lo, target_hi = resolve_target_range(duration_s, more=options.more, count=options.count)

    cost = estimate_cost(duration_s, candidates_pool_hint(target_hi), settings)
    summary.cost_estimate = cost.model_dump()

    if options.dry_run:
        summary.dry_run = True
        summary.notes.append(
            "--dry-run: parou antes de STT/candidatos/score/render (SPEC §14.4)."
        )
        for stage in ("transcribe", "candidates", "score", "select", "captions", "render", "meta"):
            reporter.skip_stage(stage, "pulado no --dry-run")
        reporter.finish(
            {"summary": _summary_payload(summary)},
            f"Dry-run: custo estimado ~US$ {cost.total_usd:.3f}",
        )
        return summary

    allowed_n, warning = apply_budget(duration_s, cost.n_candidates, options.budget, settings)
    if warning:
        summary.budget_warning = warning
        summary.notes.append(warning)
    if options.budget is not None and allowed_n <= 0:
        message = "Orçamento insuficiente; abortando antes de transcrever/gerar candidatos."
        summary.notes.append(message)
        for stage in ("transcribe", "candidates", "score", "select", "captions", "render", "meta"):
            reporter.skip_stage(stage, "orçamento insuficiente")
        reporter.finish({"summary": _summary_payload(summary)}, message)
        return summary

    check_cancel()
    if paths["transcript"].exists():
        reporter.skip_stage("transcribe", "Transcrição reaproveitada do cache")
        transcript = load_transcript(paths["dir"])
    else:
        expected_chunks = max(1, int(duration_s // 600) + 1)
        reporter.start_stage("transcribe", units_total=expected_chunks)
        transcript = _ensure_transcript(
            audio_path,
            settings,
            paths,
            client=client,
            on_progress=lambda done, total, msg: (
                reporter.set_units("transcribe", total)
                if total != reporter.stages["transcribe"].units_total
                else None
            )
            or reporter.advance_units("transcribe", done, msg),
        )
        reporter.finish_stage(
            "transcribe",
            f"Transcrição pronta ({len(transcript.segments)} segmentos"
            + (", com palavras" if transcript.has_word_timestamps else ", só segmentos")
            + ")",
        )
    if not transcript.has_word_timestamps:
        summary.notes.append(
            "STT não retornou timestamps por palavra; usando limites de segmento "
            "(fronteiras um pouco menos precisas, SPEC §15)."
        )

    feedback_examples = load_recent_feedback(settings.work_dir, settings.feedback_examples_n)

    check_cancel()
    force_regen = is_resume and options.count is not None and not paths["candidates"].exists()
    if paths["candidates"].exists() and not force_regen:
        reporter.skip_stage("candidates", "Candidatos reaproveitados do cache")
    else:
        reporter.start_stage("candidates", units_total=1)
    candidates = _ensure_candidates(
        transcript,
        settings,
        paths,
        target_hi=target_hi,
        client=client,
        feedback_examples=feedback_examples,
        force_regenerate=force_regen,
    )
    summary.candidates = len(candidates)
    if reporter.stages["candidates"].status == "running":
        reporter.finish_stage(
            "candidates", f"{len(candidates)} momentos com contexto fechado encontrados"
        )

    check_cancel()
    reporter.start_stage("score", units_total=max(1, len(candidates)))
    scored = score_candidates(
        candidates,
        video_path,
        settings,
        client=client,
        feedback_examples=feedback_examples,
        frames_dir=paths["frames"],
        use_vision=allowed_n > 0 or options.budget is None,
        on_progress=lambda done, total, cand, score: reporter.advance_units(
            "score", done, f"Avaliado {done}/{total} — {cand.title[:40]}: {score.total:.0f}"
        ),
    )
    best = max((s.total for _, s in scored), default=0.0)
    reporter.finish_stage("score", f"{len(scored)} avaliados — melhor nota: {best:.0f}")

    check_cancel()
    reporter.start_stage("select", units_total=1)
    count_cap = options.count if options.count is not None else target_hi
    outcome = _select_clips(
        scored,
        min_score=min_score,
        max_score_only=options.max_score_only,
        count_cap=count_cap,
        keep_at_least=target_lo,
        # --count N é um pedido explícito de quantidade: aí o piso relativo não
        # deve entrar no caminho do usuário.
        relative_gap=None if options.count is not None else settings.score_relative_gap,
    )
    selected = outcome.selected
    summary.deduped_removed = outcome.deduped_removed
    summary.below_floor_removed = outcome.below_floor_removed
    summary.quality_floor = outcome.quality_floor
    if outcome.below_floor_removed:
        summary.notes.append(
            f"{outcome.below_floor_removed} corte(s) descartado(s) por ficarem muito abaixo "
            f"do melhor deste vídeo (piso relativo {outcome.quality_floor:.0f}); "
            "qualidade > quantidade (SPEC §3)."
        )

    if not selected:
        message = (
            f"Nenhum candidato passou do limiar (min_score={min_score}); "
            "qualidade > quantidade (SPEC §3). Nenhum clip exportado."
        )
        summary.notes.append(message)
        reporter.finish_stage("select", message)
        for stage in ("captions", "render", "meta"):
            reporter.skip_stage(stage, "nenhum corte passou do limiar")
        reporter.finish({"summary": _summary_payload(summary)}, message)
        return summary

    reporter.finish_stage(
        "select",
        f"selected={len(selected)}, candidates={summary.candidates}, "
        f"deduped={outcome.deduped_removed}, abaixo_do_piso={outcome.below_floor_removed}",
    )

    slugs = _unique_slugs(selected)
    reporter.register_clips(
        [
            ClipProgress(slug=slugs[cand.id], score=round(score.total), status="pending")
            for cand, score in selected
        ]
    )

    check_cancel()
    diarization = _ensure_diarization(transcript, audio_path, settings, paths, client=client)
    speaker_method = resolve_speaker_matching_method(
        diarization, used_for_crop="face" in options.formats
    )
    if diarization.method != "diarization":
        hint = (
            " Escolha um modelo com speaker labels no papel de diarização (Configurações) "
            "se quiser o crop seguindo quem fala."
            if not uses_dedicated_pass(settings)
            else ""
        )
        summary.notes.append(
            "Sem labels de falante; o face track segue o rosto de maior área "
            f"(activity_proxy documentado, SPEC §14.6).{hint}"
        )

    selection_meta = {
        "mode": "count" if options.count is not None else ("more" if options.more else "auto"),
        "candidates": summary.candidates,
        "selected": len(selected),
        "min_score": min_score,
    }

    # As três fases por clipe são separadas para que a UI mostre um estágio de
    # cada vez e para que render e textos rodem em paralelo controlado.
    check_cancel()
    reporter.start_stage("captions", units_total=len(selected))
    captions_by_clip: dict[str, dict[str, Any]] = {}
    for i, (candidate, score) in enumerate(selected, 1):
        clip_dir = out_clip_dir(settings.out_dir, round(score.total), slugs[candidate.id])
        captions_by_clip[candidate.id] = _build_clip_captions(
            candidate, transcript, clip_dir, options
        )
        reporter.advance_units("captions", i, f"Legendas {i}/{len(selected)} — {slugs[candidate.id]}")
    reporter.finish_stage("captions", f"Legendas prontas para {len(selected)} cortes")

    check_cancel()
    _render_selected(
        selected,
        slugs=slugs,
        captions_by_clip=captions_by_clip,
        video_path=video_path,
        settings=settings,
        options=options,
        reporter=reporter,
        diarization=diarization,
        check_cancel=check_cancel,
    )

    check_cancel()
    selected_index = _write_selected_meta(
        selected,
        slugs=slugs,
        source_url=source_url,
        settings=settings,
        options=options,
        selection_meta=selection_meta,
        speaker_method=speaker_method,
        client=client,
        reporter=reporter,
        summary=summary,
    )

    write_selected_index(settings.work_dir, job_id, selected_index)
    summary.selected = len(selected)
    summary.notes.append(
        f"selected={summary.selected}, candidates={summary.candidates}, "
        f"deduped={summary.deduped_removed}, vertical_ok={summary.vertical_ok}, "
        f"vertical_skipped={summary.vertical_skipped}"
    )
    reporter.finish(
        {"summary": _summary_payload(summary)},
        f"{summary.selected} cortes prontos em {settings.out_dir}/",
    )
    return summary


def _summary_payload(summary: JobSummary) -> dict[str, Any]:
    return {
        "job_id": summary.job_id,
        "candidates": summary.candidates,
        "selected": summary.selected,
        "deduped_removed": summary.deduped_removed,
        "below_floor_removed": summary.below_floor_removed,
        "quality_floor": summary.quality_floor,
        "vertical_ok": summary.vertical_ok,
        "vertical_skipped": summary.vertical_skipped,
        "min_score": summary.min_score,
        "dry_run": summary.dry_run,
        "cost_estimate": summary.cost_estimate,
        "notes": list(summary.notes),
        "clips": list(summary.clips),
        "out_dirs": [c["out_dir"] for c in summary.clips],
    }


def _unique_slugs(selected: list[tuple[Candidate, Score]]) -> dict[str, str]:
    """Slug único por clipe: dois momentos podem gerar o mesmo título."""
    seen: dict[str, int] = {}
    mapping: dict[str, str] = {}
    for candidate, _score in selected:
        base = slugify(candidate.title)
        count = seen.get(base, 0)
        seen[base] = count + 1
        mapping[candidate.id] = base if count == 0 else f"{base}-{count + 1}"
    return mapping


def _seed_duration_estimate(url: str, reporter: ProgressReporter) -> None:
    try:
        info = probe_metadata(url)
        if info.get("duration"):
            reporter.set_source_minutes(float(info["duration"]) / 60.0)
    except Exception:  # noqa: BLE001 - metadados são só um chute inicial do ETA
        pass


def _render_selected(
    selected: list[tuple[Candidate, Score]],
    *,
    slugs: dict[str, str],
    captions_by_clip: dict[str, dict[str, Any]],
    video_path: Path,
    settings: Settings,
    options: RunOptions,
    reporter: ProgressReporter,
    diarization: DiarizationResult | None = None,
    check_cancel: Callable[[], None] = lambda: None,
) -> None:
    """Renderiza todos os formatos de todos os clipes, com progresso por clipe.

    ``check_cancel`` é consultado entre arquivos, não só entre estágios: render é
    o estágio mais longo do job, e um Cancelar que só responde quando o último
    ffmpeg termina não é um Cancelar.
    """
    want_face = "face" in options.formats
    want_center = "9x16" in options.formats
    want_horizontal = "16x9" in options.formats
    sample_fps = face_track_mod.DEFAULT_SAMPLE_FPS

    def _speakers_for(window) -> list[str | None] | None:
        """Quem fala em cada amostra do face track daquela janela (SPEC §14.6)."""
        if diarization is None or not diarization.segments:
            return None
        n_samples = max(1, int(round(max(0.0, window.end - window.start) * sample_fps)))
        return speaker_timeline(
            diarization, start=window.start, n_samples=n_samples, dt=1.0 / sample_fps
        )

    units = 0
    for candidate, _score in selected:
        if want_horizontal:
            units += 1
        if candidate.window_9x16 is not None:
            units += int(want_center) + int(want_face)
    reporter.start_stage("render", units_total=max(1, units))

    # Os formatos entram como "pending" antes de começar: assim o card já mostra
    # quantos arquivos aquele corte vai ter, em vez de ganhar chips do nada e
    # parecer que dois cortes exportam coisas diferentes.
    for candidate, _score in selected:
        planned = ["horizontal_16x9"] if want_horizontal else []
        if candidate.window_9x16 is not None:
            planned += ["vertical_center"] if want_center else []
            planned += ["vertical_facetrack"] if want_face else []
        for format_name in planned:
            reporter.update_clip(
                slugs[candidate.id], format_name=format_name, format_status="pending"
            )

    def render_one(candidate: Candidate, score: Score) -> None:
        check_cancel()
        slug = slugs[candidate.id]
        clip_dir = out_clip_dir(settings.out_dir, round(score.total), slug)
        caption_paths = captions_by_clip.get(candidate.id, {})
        reporter.update_clip(slug, status="running", message="Renderizando…")

        if candidate.window_9x16 is None:
            reporter.update_clip(
                slug,
                vertical_skipped=candidate.vertical_skip_reason or "context_exceeds_90s",
                message="Contexto passa de 90s — só 16:9",
            )

        if want_horizontal:
            _render_format(
                reporter,
                slug,
                "horizontal_16x9",
                lambda: render_mod.render_horizontal_16x9(
                    video_path,
                    candidate.window_16x9,
                    clip_dir / "horizontal_16x9.mp4",
                    ass_path=caption_paths.get("ass_16x9"),
                ),
            )

        if candidate.window_9x16 is not None:
            if want_center:
                check_cancel()
                _render_format(
                    reporter,
                    slug,
                    "vertical_center",
                    lambda: render_mod.render_vertical_center(
                        video_path,
                        candidate.window_9x16,
                        clip_dir / "vertical_center.mp4",
                        ass_path=caption_paths.get("ass_9x16"),
                    ),
                )
            if want_face:
                check_cancel()
                _render_format(
                    reporter,
                    slug,
                    "vertical_facetrack",
                    lambda: face_track_mod.render_vertical_facetrack(
                        video_path,
                        candidate.window_9x16,
                        clip_dir / "vertical_facetrack.mp4",
                        ass_path=caption_paths.get("ass_9x16"),
                        speakers=_speakers_for(candidate.window_9x16),
                    ),
                )

        reporter.update_clip(slug, status="done", message="Renderizado")

    # ffmpeg e MediaPipe já saturam CPU; render_workers baixo evita swap no i5.
    workers = max(1, min(settings.render_workers, len(selected)))
    if workers == 1:
        for candidate, score in selected:
            render_one(candidate, score)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(render_one, candidate, score): candidate
                for candidate, score in selected
            }
            for future in as_completed(futures):
                future.result()

    reporter.finish_stage(
        "render", f"{reporter.clips_done}/{len(selected)} cortes renderizados"
    )


def _render_format(
    reporter: ProgressReporter, slug: str, format_name: str, action: Callable[[], Any]
) -> None:
    reporter.update_clip(slug, format_name=format_name, format_status="running")
    try:
        action()
    except Exception as exc:  # noqa: BLE001 - um formato quebrado não mata o clipe
        reporter.update_clip(
            slug, format_name=format_name, format_status="error", message=str(exc)[:120]
        )
    else:
        reporter.update_clip(slug, format_name=format_name, format_status="done")
    finally:
        reporter.increment_units(
            "render",
            message=lambda done, total: f"Renderizando… {int(done)}/{int(total)} arquivos",
        )


def _write_selected_meta(
    selected: list[tuple[Candidate, Score]],
    *,
    slugs: dict[str, str],
    source_url: str,
    settings: Settings,
    options: RunOptions,
    selection_meta: dict[str, Any],
    speaker_method: str,
    client: OpenRouterClient,
    reporter: ProgressReporter,
    summary: JobSummary,
) -> list[dict[str, Any]]:
    """Gera títulos/hashtags e escreve meta.json de cada clipe (SPEC §10)."""
    reporter.start_stage("meta", units_total=len(selected))

    def build(candidate: Candidate, score: Score) -> dict[str, Any]:
        return _write_clip_meta(
            candidate,
            score,
            slug=slugs[candidate.id],
            source_url=source_url,
            settings=settings,
            selection_meta=selection_meta,
            speaker_method=speaker_method,
            client=client,
        )

    results: dict[str, dict[str, Any]] = {}
    workers = max(1, min(settings.network_workers, len(selected)))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(build, c, s): c for c, s in selected}
        for future in as_completed(futures):
            candidate = futures[future]
            results[candidate.id] = future.result()
            done += 1
            reporter.advance_units(
                "meta", done, f"Textos {done}/{len(selected)} — {slugs[candidate.id]}"
            )

    reporter.finish_stage("meta", f"Títulos e hashtags prontos para {len(selected)} cortes")

    selected_index: list[dict[str, Any]] = []
    for candidate, _score in selected:
        clip_info = results[candidate.id]
        selected_index.append(clip_info)
        summary.clips.append(clip_info)
        if clip_info["vertical_skipped"]:
            summary.vertical_skipped += 1
        else:
            summary.vertical_ok += 1
    return selected_index


def candidates_pool_hint(target_hi: int) -> int:
    from .candidates import candidate_pool_size

    return candidate_pool_size(target_hi)


def _build_clip_captions(
    candidate: Candidate,
    transcript: Transcript,
    clip_dir: Path,
    options: RunOptions,
) -> dict[str, Any]:
    """Escreve SRT (sidecar) e ASS (burn-in) do clipe — SPEC §10, §14.5.

    Roda antes do render porque o burn-in consome o .ass gerado aqui.
    """
    words = transcript.all_words()
    burn_in = options.captions in ("burn", "both")
    paths: dict[str, Any] = {}

    def cues_for(start: float, end: float):
        if words:
            return subtitles_mod.build_cues_from_words(words, start, end)
        return subtitles_mod.build_cues_from_segments(transcript.segments, start, end)

    cues_16x9 = cues_for(candidate.window_16x9.start, candidate.window_16x9.end)
    subtitles_mod.write_srt(cues_16x9, clip_dir / "captions.srt")
    if burn_in:
        ass_16x9 = clip_dir / "captions_16x9.ass"
        subtitles_mod.write_ass(
            cues_16x9, ass_16x9, *render_mod.HORIZONTAL_SIZE, is_vertical=False
        )
        paths["ass_16x9"] = ass_16x9

    if candidate.window_9x16 is not None:
        cues_9x16 = cues_for(candidate.window_9x16.start, candidate.window_9x16.end)
        subtitles_mod.write_srt(cues_9x16, clip_dir / "captions_9x16.srt")
        if burn_in:
            ass_9x16 = clip_dir / "captions_9x16.ass"
            subtitles_mod.write_ass(
                cues_9x16, ass_9x16, *render_mod.VERTICAL_SIZE, is_vertical=True
            )
            paths["ass_9x16"] = ass_9x16

    return paths


def _write_clip_meta(
    candidate: Candidate,
    score: Score,
    *,
    slug: str,
    source_url: str,
    settings: Settings,
    selection_meta: dict[str, Any],
    speaker_method: str,
    client: OpenRouterClient,
) -> dict[str, Any]:
    """Gera os textos sociais e grava meta.json (SPEC §7)."""
    clip_dir = out_clip_dir(settings.out_dir, round(score.total), slug)

    vertical_skipped = candidate.vertical_skip_reason
    if candidate.window_9x16 is None and vertical_skipped is None:
        vertical_skipped = "context_exceeds_90s"

    try:
        social_copy = meta_mod.generate_social_copy(candidate, settings, client=client)
    except Exception:  # noqa: BLE001 - o job não pode travar por causa de copy
        social_copy = {"youtube": {}, "tiktok": {}}

    meta_dict = meta_mod.build_meta(
        source_url=source_url,
        candidate=candidate,
        score=score,
        window_9x16=candidate.window_9x16,
        window_16x9=candidate.window_16x9,
        vertical_skipped=vertical_skipped,
        selection=selection_meta,
        social_copy=social_copy,
        speaker_matching_method=speaker_method,
    )
    write_json(clip_dir / "meta.json", meta_dict)

    return {
        "slug": slug,
        "score": round(score.total),
        "reason": score.reason,
        "out_dir": str(clip_dir),
        "vertical_skipped": vertical_skipped,
    }
