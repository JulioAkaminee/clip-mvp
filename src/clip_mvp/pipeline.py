"""Orquestração do pipeline completo (SPEC §6, §12). Liga todos os módulos."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import audio as audio_mod
from . import face_track as face_track_mod
from . import meta as meta_mod
from . import render as render_mod
from . import subtitles as subtitles_mod
from .budget import apply_budget, estimate_cost
from .candidates import generate_candidates, resolve_target_range
from .config import Settings
from .dedupe import DedupeItem, dedupe_items
from .diarization import diarize, resolve_speaker_matching_method
from .download import download_source
from .feedback import load_recent_feedback, write_selected_index
from .models import Candidate, Score, Transcript
from .openrouter import OpenRouterClient
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
    }


def _ensure_download(url: str, settings: Settings, paths: dict[str, Path]) -> Path:
    if paths["video"].exists():
        return paths["video"]
    result = download_source(url, paths["dir"], height=settings.download_height)
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
) -> Transcript:
    if paths["transcript"].exists():
        return load_transcript(paths["dir"])
    transcript = transcribe_audio(audio_path, settings, client=client)
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


def _ensure_diarization_method(
    audio_path: Path,
    settings: Settings,
    paths: dict[str, Path],
    *,
    client: OpenRouterClient | None = None,
) -> str:
    """Diariza (com cache em work/<job_id>/diarization.json, SPEC §14.4) e
    retorna o método a registrar em meta.json (SPEC §14.6)."""
    if paths["diarization"].exists():
        cached = read_json(paths["diarization"])
        return cached.get("method", "activity_proxy")

    try:
        diarization = diarize(audio_path, settings, client=client)
    except Exception:
        diarization = None

    method = resolve_speaker_matching_method(diarization)
    write_json(
        paths["diarization"],
        {"method": method, "segments": [s.model_dump() for s in diarization.segments] if diarization else []},
    )
    return method


def _select_clips(
    scored: list[tuple[Candidate, Score]],
    *,
    min_score: float,
    max_score_only: float | None,
    count_cap: int,
) -> tuple[list[tuple[Candidate, Score]], int]:
    """Aplica limiar + dedupe (por score) + teto (SPEC §3 fluxo interno)."""
    items = [
        DedupeItem(item=(c, s), start=c.window_16x9.start, end=c.window_16x9.end, text=c.text_excerpt, score=s.total)
        for c, s in scored
    ]
    dedupe_result = dedupe_items(items)
    deduped = dedupe_result.kept

    threshold = max_score_only if max_score_only is not None else min_score
    passing = [(c, s) for c, s in deduped if s.total >= threshold]
    passing.sort(key=lambda cs: cs[1].total, reverse=True)
    selected = passing[:count_cap]
    return selected, dedupe_result.removed_count


def run_job(
    url: str,
    settings: Settings,
    options: RunOptions,
    *,
    client: OpenRouterClient | None = None,
) -> JobSummary:
    job_id = make_job_id(url)
    return _run_or_resume(job_id, url, settings, options, client=client, is_resume=False)


def resume_job(
    job_id: str,
    settings: Settings,
    options: RunOptions,
    *,
    client: OpenRouterClient | None = None,
) -> JobSummary:
    return _run_or_resume(job_id, None, settings, options, client=client, is_resume=True)


def _run_or_resume(
    job_id: str,
    url: str | None,
    settings: Settings,
    options: RunOptions,
    *,
    client: OpenRouterClient | None,
    is_resume: bool,
) -> JobSummary:
    paths = _job_paths(settings.work_dir, job_id)
    summary = JobSummary(job_id=job_id)
    client = client or OpenRouterClient(settings)

    if is_resume:
        if not paths["transcript"].exists():
            raise RuntimeError(
                f"Job {job_id} não tem transcrição em cache; use `clip \"URL\"` para iniciar do zero."
            )
        job_meta_path = paths["dir"] / "job.json"
        source_url = read_json(job_meta_path).get("source_url", "") if job_meta_path.exists() else ""
    else:
        assert url is not None
        source_url = url
        write_json(paths["dir"] / "job.json", {"source_url": url, "job_id": job_id})
        video_path = _ensure_download(url, settings, paths)
        _ensure_audio(video_path, paths)

    video_path = paths["video"]
    audio_path = paths["audio"]

    # Duração é conhecida sem precisar transcrever (ffprobe no vídeo baixado,
    # ou a transcrição já cacheada em `resume`). Isso permite que --dry-run e
    # --budget decidam ANTES de pagar por STT/candidatos/vision (SPEC §14.4).
    if paths["transcript"].exists():
        duration_s = load_transcript(paths["dir"]).duration
    else:
        duration_s = ffprobe_duration(video_path)

    min_score = options.min_score if options.min_score is not None else settings.min_score_default
    summary.min_score = options.max_score_only if options.max_score_only is not None else min_score

    _, target_hi = resolve_target_range(duration_s, more=options.more, count=options.count)

    cost = estimate_cost(duration_s, candidates_pool_hint(target_hi), settings)
    summary.cost_estimate = cost.model_dump()

    if options.dry_run:
        summary.dry_run = True
        summary.notes.append(
            "--dry-run: parou antes de STT/candidatos/score/render (SPEC §14.4)."
        )
        return summary

    allowed_n, warning = apply_budget(duration_s, cost.n_candidates, options.budget, settings)
    if warning:
        summary.budget_warning = warning
        summary.notes.append(warning)
    if options.budget is not None and allowed_n <= 0:
        summary.notes.append("Orçamento insuficiente; abortando antes de transcrever/gerar candidatos.")
        return summary

    transcript = _ensure_transcript(audio_path, settings, paths, client=client)
    feedback_examples = load_recent_feedback(settings.work_dir, settings.feedback_examples_n)

    force_regen = is_resume and options.count is not None and not paths["candidates"].exists()
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

    scored = score_candidates(candidates, video_path, settings, client=client, feedback_examples=feedback_examples)

    count_cap = options.count if options.count is not None else target_hi
    selected, removed = _select_clips(
        scored,
        min_score=min_score,
        max_score_only=options.max_score_only,
        count_cap=count_cap,
    )
    summary.deduped_removed = removed

    if not selected:
        summary.notes.append(
            f"Nenhum candidato passou do limiar (min_score={min_score}); "
            "qualidade > quantidade (SPEC §3). Nenhum clip exportado."
        )
        return summary

    speaker_method = _ensure_diarization_method(audio_path, settings, paths, client=client)

    selection_meta = {
        "mode": "count" if options.count is not None else ("more" if options.more else "auto"),
        "candidates": summary.candidates,
        "selected": len(selected),
        "min_score": min_score,
    }

    selected_index: list[dict[str, Any]] = []
    for candidate, score in selected:
        clip_info = _export_clip(
            candidate,
            score,
            source_url=source_url,
            video_path=video_path,
            transcript=transcript,
            settings=settings,
            options=options,
            selection_meta=selection_meta,
            speaker_method=speaker_method,
            client=client,
        )
        selected_index.append(clip_info)
        summary.clips.append(clip_info)
        if clip_info["vertical_skipped"]:
            summary.vertical_skipped += 1
        else:
            summary.vertical_ok += 1

    write_selected_index(settings.work_dir, job_id, selected_index)
    summary.selected = len(selected)
    summary.notes.append(
        f"selected={summary.selected}, candidates={summary.candidates}, "
        f"deduped={summary.deduped_removed}, vertical_ok={summary.vertical_ok}, "
        f"vertical_skipped={summary.vertical_skipped}"
    )
    return summary


def candidates_pool_hint(target_hi: int) -> int:
    from .candidates import candidate_pool_size

    return candidate_pool_size(target_hi)


def _export_clip(
    candidate: Candidate,
    score: Score,
    *,
    source_url: str,
    video_path: Path,
    transcript: Transcript,
    settings: Settings,
    options: RunOptions,
    selection_meta: dict[str, Any],
    speaker_method: str,
    client: OpenRouterClient,
) -> dict[str, Any]:
    slug = slugify(candidate.title)
    clip_dir = out_clip_dir(settings.out_dir, round(score.total), slug)

    vertical_skipped = candidate.vertical_skip_reason
    if candidate.window_9x16 is None and vertical_skipped is None:
        vertical_skipped = "context_exceeds_90s"

    words = transcript.all_words()

    srt_16x9_path = clip_dir / "captions.srt"
    if words:
        cues_16x9 = subtitles_mod.build_cues_from_words(words, candidate.window_16x9.start, candidate.window_16x9.end)
    else:
        cues_16x9 = subtitles_mod.build_cues_from_segments(
            transcript.segments, candidate.window_16x9.start, candidate.window_16x9.end
        )
    subtitles_mod.write_srt(cues_16x9, srt_16x9_path)

    want_face = "face" in options.formats
    want_center = "9x16" in options.formats
    want_horizontal = "16x9" in options.formats
    burn_in = options.captions in ("burn", "both")
    sidecar = options.captions in ("sidecar", "both")

    ass_16x9_path = None
    if burn_in:
        ass_16x9_path = clip_dir / "captions_16x9.ass"
        subtitles_mod.write_ass(cues_16x9, ass_16x9_path, *render_mod.HORIZONTAL_SIZE, is_vertical=False)

    if want_horizontal:
        render_mod.render_horizontal_16x9(
            video_path,
            candidate.window_16x9,
            clip_dir / "horizontal_16x9.mp4",
            ass_path=ass_16x9_path if burn_in else None,
        )

    if candidate.window_9x16 is not None:
        if words:
            cues_9x16 = subtitles_mod.build_cues_from_words(
                words, candidate.window_9x16.start, candidate.window_9x16.end
            )
        else:
            cues_9x16 = subtitles_mod.build_cues_from_segments(
                transcript.segments, candidate.window_9x16.start, candidate.window_9x16.end
            )
        subtitles_mod.write_srt(cues_9x16, clip_dir / "captions_9x16.srt")

        ass_9x16_path = None
        if burn_in:
            ass_9x16_path = clip_dir / "captions_9x16.ass"
            subtitles_mod.write_ass(cues_9x16, ass_9x16_path, *render_mod.VERTICAL_SIZE, is_vertical=True)

        if want_center:
            render_mod.render_vertical_center(
                video_path,
                candidate.window_9x16,
                clip_dir / "vertical_center.mp4",
                ass_path=ass_9x16_path if burn_in else None,
            )
        if want_face:
            face_track_mod.render_vertical_facetrack(
                video_path,
                candidate.window_9x16,
                clip_dir / "vertical_facetrack.mp4",
                ass_path=ass_9x16_path if burn_in else None,
            )

    social_copy: dict[str, Any] = {}
    try:
        social_copy = meta_mod.generate_social_copy(candidate, settings, client=client)
    except Exception:
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

    if not sidecar and not burn_in:
        pass  # SRT sidecar sempre gerado; burn é opcional via .ass acima.

    return {
        "slug": slug,
        "score": round(score.total),
        "reason": score.reason,
        "out_dir": str(clip_dir),
        "vertical_skipped": vertical_skipped,
    }
