"""Orquestrador do job (SPEC 6).

O pipeline é síncrono e reporta progresso por callbacks (`JobReporter`), o que
permite rodar tanto pela CLI quanto pela API (worker em thread) sem duplicar
lógica.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import candidates as candidates_mod
from . import download as download_mod
from .boundaries import Window
from .budget import Estimate, estimate as estimate_cost, fit_candidates_to_budget
from .captions import write_clip_captions
from .config import ALL_FORMATS, DEFAULT_MIN_SCORE, Settings, get_settings
from .dedupe import dedupe
from .diarize import speaker_timeline
from .face_track import TrackResult, track as track_faces
from .ffmpeg_utils import duration_of, require_ffmpeg, video_size
from .meta import build_meta, social_text, write_meta
from .models import Candidate, SelectionStats
from .paths import clip_out_dir, job_dir, job_out_dir, slugify
from .render import (
    render_horizontal,
    render_poster,
    render_vertical_center,
    render_vertical_facetrack,
)
from .score import score_candidates
from .transcribe import transcribe

STAGES: tuple[tuple[str, str], ...] = (
    ("download", "Download"),
    ("transcribe", "Transcrição"),
    ("candidates", "Candidatos"),
    ("score", "Score"),
    ("select", "Seleção"),
    ("render", "Render + legendas"),
    ("meta", "Títulos e hashtags"),
)


class JobCanceled(RuntimeError):
    pass


@dataclass
class JobOptions:
    url: str
    mode: str = "auto"
    count: int | None = None
    min_score: int = DEFAULT_MIN_SCORE
    max_score_only: int | None = None
    formats: tuple[str, ...] = ALL_FORMATS
    captions: str = "both"
    platforms: tuple[str, ...] = ("yt", "tiktok")
    dry_run: bool = False
    budget_usd: float | None = None
    demo: bool | None = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "mode": self.mode,
            "count": self.count,
            "min_score": self.min_score,
            "max_score_only": self.max_score_only,
            "formats": list(self.formats),
            "captions": self.captions,
            "platforms": list(self.platforms),
            "dry_run": self.dry_run,
            "budget_usd": self.budget_usd,
            "demo": self.demo,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JobOptions":
        return cls(
            url=data["url"],
            mode=data.get("mode", "auto"),
            count=data.get("count"),
            min_score=int(data.get("min_score", DEFAULT_MIN_SCORE)),
            max_score_only=data.get("max_score_only"),
            formats=tuple(data.get("formats") or ALL_FORMATS),
            captions=data.get("captions", "both"),
            platforms=tuple(data.get("platforms") or ("yt", "tiktok")),
            dry_run=bool(data.get("dry_run")),
            budget_usd=data.get("budget_usd"),
            demo=data.get("demo"),
        )


class JobReporter:
    """Recebe progresso do pipeline. A API e a CLI implementam à sua maneira."""

    def stage(
        self,
        key: str,
        status: str = "running",
        progress: float | None = None,
        message: str = "",
    ) -> None:  # pragma: no cover - interface
        pass

    def log(self, message: str, level: str = "info") -> None:  # pragma: no cover
        pass

    def source(self, info: dict) -> None:  # pragma: no cover
        pass

    def estimate(self, estimate: dict) -> None:  # pragma: no cover
        pass

    def selection(self, stats: dict) -> None:  # pragma: no cover
        pass

    def clip(self, clip: dict) -> None:  # pragma: no cover
        pass

    def check_cancel(self) -> None:  # pragma: no cover
        pass


@dataclass
class JobResult:
    job_id: str
    clips: list[dict] = field(default_factory=list)
    selection: dict = field(default_factory=dict)
    estimate: dict | None = None
    source: dict = field(default_factory=dict)
    dry_run: bool = False


def _is_local_source(url: str) -> Path | None:
    """Aceita caminho local / file:// (útil para demo e testes offline)."""
    if url.startswith("file://"):
        return Path(unquote(urlparse(url).path))
    if url.startswith(("http://", "https://")):
        return None
    candidate = Path(url).expanduser()
    return candidate if candidate.exists() else None


def _acquire_source(
    options: JobOptions, work: Path, reporter: JobReporter
) -> download_mod.SourceMedia:
    local = _is_local_source(options.url)
    if local is not None:
        if not local.exists():
            raise FileNotFoundError(f"arquivo não encontrado: {local}")
        dest = work / f"source{local.suffix or '.mp4'}"
        if not dest.exists():
            shutil.copy2(local, dest)
        reporter.stage("download", "done", 1.0, f"arquivo local: {local.name}")
        return download_mod.SourceMedia(
            path=dest,
            title=local.stem,
            duration_s=duration_of(dest),
            url=options.url,
        )

    def on_progress(fraction: float, line: str) -> None:
        reporter.check_cancel()
        reporter.stage("download", "running", fraction, line[-120:])

    media = download_mod.download(options.url, work, on_progress=on_progress)
    reporter.stage("download", "done", 1.0, f"{media.title} ({media.duration_s / 60:.1f} min)")
    return media


def _probe_duration(options: JobOptions, reporter: JobReporter) -> tuple[float, dict]:
    local = _is_local_source(options.url)
    if local is not None:
        return duration_of(local), {"title": local.stem, "duration_s": duration_of(local)}
    info = download_mod.probe_source(options.url)
    return info["duration_s"], info


def dry_run(options: JobOptions, reporter: JobReporter, settings: Settings) -> JobResult:
    """Estimativa de custo sem baixar nem chamar vision (SPEC 14.4)."""
    reporter.stage("download", "running", 0.2, "lendo metadados da fonte")
    duration, info = _probe_duration(options, reporter)
    reporter.source({**info, "url": options.url})
    reporter.stage("download", "skipped", 1.0, "dry-run: sem download")

    plan = candidates_mod.plan_count(duration, options.mode, options.count)
    est = estimate_cost(
        duration_s=duration,
        candidates=plan.pool,
        selected=plan.target_max,
        budget_usd=options.budget_usd,
    )
    if options.budget_usd is not None and not est.within_budget:
        allowed, est = fit_candidates_to_budget(
            duration, plan.pool, plan.target_max, options.budget_usd
        )
        reporter.log(
            f"orçamento US$ {options.budget_usd:.2f}: pool cairia para {allowed} candidatos",
            "warn",
        )
    for key, _ in STAGES[1:]:
        reporter.stage(key, "skipped", 0.0, "dry-run")
    reporter.estimate(est.to_dict())
    reporter.log(
        f"estimativa: US$ {est.total_usd:.2f} para {duration / 60:.1f} min "
        f"({plan.pool} candidatos, alvo {plan.target_min}–{plan.target_max} cortes)"
    )
    return JobResult(
        job_id="",
        estimate=est.to_dict(),
        source={**info, "url": options.url},
        dry_run=True,
        selection={
            "mode": plan.mode,
            "target_min": plan.target_min,
            "target_max": plan.target_max,
            "candidates": plan.pool,
            "min_score": options.min_score,
        },
    )


def run_job(
    job_id: str,
    options: JobOptions,
    reporter: JobReporter,
    settings: Settings | None = None,
) -> JobResult:
    settings = settings or get_settings()
    if options.demo:
        settings = Settings(**{**settings.__dict__, "demo": True})
    require_ffmpeg()
    work = job_dir(job_id)
    work.mkdir(parents=True, exist_ok=True)

    if options.dry_run:
        result = dry_run(options, reporter, settings)
        result.job_id = job_id
        return result

    if not settings.ai_enabled:
        reporter.log(
            "modo demo: transcrição, candidatos e score são sintéticos "
            "(defina OPENROUTER_API_KEY para usar a IA real).",
            "warn",
        )

    # 1. Fonte -----------------------------------------------------------------
    reporter.stage("download", "running", 0.0, "obtendo fonte")
    media = _acquire_source(options, work, reporter)
    reporter.source(media.to_dict())
    reporter.check_cancel()

    # 2. Transcrição -----------------------------------------------------------
    reporter.stage("transcribe", "running", 0.0, "transcrevendo (PT-BR)")
    transcript_obj = transcribe(
        media.path,
        work,
        settings,
        on_progress=lambda p, m: (
            reporter.check_cancel(),
            reporter.stage("transcribe", "running", p, m),
        )[-1],
        duration_hint=media.duration_s,
    )
    reporter.stage(
        "transcribe",
        "done",
        1.0,
        f"{len(transcript_obj.segments)} segmentos · fronteira por "
        f"{'palavra' if transcript_obj.has_word_timestamps else 'segmento'}",
    )
    reporter.check_cancel()

    # 3. Candidatos ------------------------------------------------------------
    plan = candidates_mod.plan_count(transcript_obj.duration, options.mode, options.count)
    transcript_chars = sum(len(s.text) for s in transcript_obj.segments)
    est = estimate_cost(
        transcript_obj.duration,
        plan.pool,
        plan.target_max,
        transcript_chars,
        options.budget_usd,
    )
    if options.budget_usd is not None:
        allowed, est = fit_candidates_to_budget(
            transcript_obj.duration,
            plan.pool,
            plan.target_max,
            options.budget_usd,
            transcript_chars,
        )
        if not est.within_budget:
            reporter.estimate(est.to_dict())
            raise RuntimeError(
                f"orçamento insuficiente: estimativa US$ {est.total_usd:.2f} > "
                f"US$ {options.budget_usd:.2f}. Aumente --budget ou reduza o vídeo."
            )
        if allowed < plan.pool:
            reporter.log(est.note or f"pool reduzido para {allowed} candidatos", "warn")
            plan.pool = allowed
    reporter.estimate(est.to_dict())

    reporter.stage(
        "candidates",
        "running",
        0.0,
        f"alvo {plan.target_min}–{plan.target_max} cortes · pool {plan.pool}",
    )
    pool = candidates_mod.generate(
        transcript_obj,
        settings,
        plan,
        on_progress=lambda p, m: (
            reporter.check_cancel(),
            reporter.stage("candidates", "running", p, m),
        )[-1],
    )
    reporter.stage("candidates", "done", 1.0, f"{len(pool)} candidatos válidos")
    if not pool:
        reporter.log("nenhum candidato com contexto fechado foi encontrado", "warn")

    # 4. Score -----------------------------------------------------------------
    reporter.stage("score", "running", 0.0, "pontuando candidatos")
    score_candidates(
        pool,
        media.path,
        work,
        settings,
        on_progress=lambda p, m: (
            reporter.check_cancel(),
            reporter.stage("score", "running", p, m),
        )[-1],
    )
    reporter.stage("score", "done", 1.0, f"{len(pool)} candidatos pontuados")
    reporter.check_cancel()

    # 5. Seleção (dedupe → limiar → teto) --------------------------------------
    reporter.stage("select", "running", 0.3, "deduplicando e aplicando limiar")
    kept, removed = dedupe(pool)
    for candidate, why in removed:
        reporter.log(
            f"dedupe: '{candidate.title[:40]}' removido ({why}, score {candidate.score})",
            "debug",
        )
    floor = max(options.min_score, options.max_score_only or 0)
    passing = [c for c in kept if c.score >= floor]
    below = len(kept) - len(passing)
    passing.sort(key=lambda c: (-c.score, c.horizontal.start))
    selected = passing[: plan.target_max]
    selected.sort(key=lambda c: c.horizontal.start)

    stats = SelectionStats(
        mode=plan.mode,
        candidates=len(pool),
        selected=len(selected),
        deduped=len(removed),
        below_threshold=below,
        min_score=floor,
        target_min=plan.target_min,
        target_max=plan.target_max,
        vertical_ok=sum(1 for c in selected if c.vertical),
        vertical_skipped=sum(1 for c in selected if not c.vertical),
        reason=_selection_reason(plan, selected, below, len(removed), options),
    )
    reporter.selection(stats.to_dict())
    reporter.stage(
        "select",
        "done",
        1.0,
        f"selected={stats.selected} candidates={stats.candidates} "
        f"deduped={stats.deduped} vertical_ok={stats.vertical_ok} "
        f"vertical_skipped={stats.vertical_skipped}",
    )
    reporter.log(stats.reason)

    # 6. Render + legendas -----------------------------------------------------
    out_root = job_out_dir(job_id)
    out_root.mkdir(parents=True, exist_ok=True)
    clips: list[dict] = []
    reporter.stage("render", "running", 0.0, f"renderizando {len(selected)} cortes")
    used_slugs: set[str] = set()
    for index, candidate in enumerate(selected):
        reporter.check_cancel()
        candidate.slug = _unique_slug(candidate, index, used_slugs)
        clip_dir = clip_out_dir(job_id, candidate.score, candidate.slug)
        clip_dir.mkdir(parents=True, exist_ok=True)
        reporter.stage(
            "render",
            "running",
            index / max(1, len(selected)),
            f"corte {index + 1}/{len(selected)} · {candidate.title[:48]}",
        )
        clip = _render_clip(
            candidate=candidate,
            clip_dir=clip_dir,
            media=media,
            transcript_obj=transcript_obj,
            options=options,
            settings=settings,
            stats=stats,
            reporter=reporter,
        )
        clips.append(clip)
        reporter.clip(clip)
    reporter.stage("render", "done", 1.0, f"{len(clips)} cortes renderizados")

    # 7. Meta (títulos/hashtags) ----------------------------------------------
    reporter.stage("meta", "running", 0.0, "gerando títulos e hashtags")
    for index, (candidate, clip) in enumerate(zip(selected, clips)):
        reporter.check_cancel()
        reporter.stage(
            "meta", "running", index / max(1, len(clips)), f"meta {index + 1}/{len(clips)}"
        )
        social = social_text(candidate, settings, options.platforms)
        meta = build_meta(
            candidate=candidate,
            source_url=options.url,
            source_title=media.title,
            stats=stats,
            settings=settings,
            exports=clip["artifacts"],
            social=social,
            face_track_method=clip.get("face_track"),
            captions_mode=options.captions,
        )
        write_meta(Path(clip["dir"]) / "meta.json", meta)
        clip["meta"] = meta
        clip["artifacts"]["meta"] = "meta.json"
        reporter.clip(clip)
    reporter.stage("meta", "done", 1.0, f"{len(clips)} meta.json escritos")

    return JobResult(
        job_id=job_id,
        clips=clips,
        selection=stats.to_dict(),
        estimate=est.to_dict(),
        source=media.to_dict(),
    )


def _unique_slug(candidate: Candidate, index: int, used: set[str]) -> str:
    base = candidate.slug or slugify(candidate.title) or f"corte-{index + 1}"
    slug = base
    suffix = 2
    while slug in used:
        slug = f"{base}-{suffix}"
        suffix += 1
    used.add(slug)
    return slug


def _selection_reason(
    plan: candidates_mod.CountPlan,
    selected: list[Candidate],
    below: int,
    deduped: int,
    options: JobOptions,
) -> str:
    parts = [
        f"modo {plan.mode}: {len(selected)} cortes (alvo {plan.target_min}–{plan.target_max})"
    ]
    if deduped:
        parts.append(f"{deduped} removidos por dedupe")
    if below:
        parts.append(f"{below} abaixo do limiar {options.min_score}")
    if plan.mode == "count" and options.count and len(selected) < options.count:
        parts.append(
            f"não havia {options.count} momentos com contexto fechado acima do limiar — "
            "entreguei só os que passaram"
        )
    if plan.mode == "more" and len(selected) < plan.target_min:
        parts.append("o vídeo não tinha mais momentos fortes para dar --more")
    return "; ".join(parts)


def _render_clip(
    candidate: Candidate,
    clip_dir: Path,
    media: download_mod.SourceMedia,
    transcript_obj,
    options: JobOptions,
    settings: Settings,
    stats: SelectionStats,
    reporter: JobReporter,
) -> dict:
    burn_vertical = options.captions in {"burn", "both"}
    sidecar = options.captions in {"sidecar", "both"}

    caption_window: Window = candidate.vertical or candidate.horizontal
    caption_paths = write_clip_captions(
        clip_dir,
        transcript_obj,
        horizontal=(candidate.horizontal.start, candidate.horizontal.end),
        vertical=(
            (candidate.vertical.start, candidate.vertical.end) if candidate.vertical else None
        ),
    )
    vertical_ass = caption_paths.get("ass_vertical")

    artifacts: dict[str, str] = {}
    if sidecar:
        artifacts["captions_srt"] = "captions.srt"
        if vertical_ass:
            artifacts["captions_ass"] = vertical_ass.name

    face_method: str | None = None
    formats = set(options.formats)

    if candidate.vertical and "vertical_center" in formats:
        result = render_vertical_center(
            media.path,
            candidate.vertical,
            clip_dir / "vertical_center.mp4",
            ass_name=vertical_ass.name if (burn_vertical and vertical_ass) else None,
            work_dir=clip_dir,
        )
        artifacts["vertical_center"] = result.path.name

    if candidate.vertical and "vertical_facetrack" in formats:
        width, _height = video_size(media.path)
        turns = speaker_timeline(
            transcript_obj, candidate.vertical.start, candidate.vertical.end
        )
        tracking: TrackResult = track_faces(
            media.path,
            candidate.vertical.start,
            candidate.vertical.end,
            frame_width=width or 1280,
            turns=turns,
        )
        face_method = tracking.method if tracking.available else "center_fallback"
        if not tracking.available:
            reporter.log(
                "face track indisponível (MediaPipe ausente ou sem rosto): "
                "usando center crop no vertical_facetrack",
                "warn",
            )
        result = render_vertical_facetrack(
            media.path,
            candidate.vertical,
            clip_dir / "vertical_facetrack.mp4",
            tracking,
            ass_name=vertical_ass.name if (burn_vertical and vertical_ass) else None,
            work_dir=clip_dir,
        )
        artifacts["vertical_facetrack"] = result.path.name
        face_method = result.face_track or face_method
        for leftover in clip_dir.glob("*_track.cmd"):
            leftover.unlink(missing_ok=True)

    if "horizontal_16x9" in formats:
        result = render_horizontal(
            media.path,
            candidate.horizontal,
            clip_dir / "horizontal_16x9.mp4",
            ass_name="captions_16x9.ass" if options.captions == "burn" else None,
            work_dir=clip_dir,
        )
        artifacts["horizontal_16x9"] = result.path.name

    poster_at = caption_window.start + min(2.0, caption_window.duration / 2)
    try:
        render_poster(media.path, poster_at, clip_dir / "poster.jpg")
        artifacts["poster"] = "poster.jpg"
    except Exception:
        pass

    if not sidecar:
        (clip_dir / "captions.srt").unlink(missing_ok=True)
        if vertical_ass:
            vertical_ass.unlink(missing_ok=True)
    (clip_dir / "captions_16x9.ass").unlink(missing_ok=True)

    return {
        "slug": candidate.slug,
        "dir": str(clip_dir),
        "title": candidate.title,
        "score": candidate.score,
        "breakdown": candidate.breakdown.to_dict(),
        "reason": candidate.reason,
        "context_complete": candidate.context_complete,
        "boundary_method": candidate.horizontal.method,
        "transcript_text": candidate.transcript_text,
        "windows": {
            "horizontal_16x9": candidate.horizontal.to_dict(),
            "vertical_9x16": candidate.vertical.to_dict() if candidate.vertical else None,
        },
        "vertical_skipped": candidate.vertical_skipped,
        "face_track": face_method,
        "artifacts": artifacts,
        "created_at": time.time(),
    }
