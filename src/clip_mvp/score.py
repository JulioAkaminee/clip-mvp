"""Score de viralização: texto + 3 frames (vision) — SPEC §8."""

from __future__ import annotations

import tempfile
from importlib import resources
from pathlib import Path

from .config import Settings
from .models import Candidate, Score, ScoreBreakdown
from .openrouter import OpenRouterClient, image_to_b64
from .utils import run_ffmpeg


def _load_prompt(name: str) -> str:
    return resources.files("clip_mvp.prompts").joinpath(name).read_text(encoding="utf-8")


def extract_frames(video_path: Path, start: float, end: float, out_dir: Path, *, n: int = 3) -> list[Path]:
    """Extrai `n` frames (início/meio/fim, por padrão) do trecho [start, end]
    do vídeo-fonte, usados como entrada de vision no scorer (SPEC §8)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = max(0.01, end - start)
    if n == 1:
        fractions = [0.5]
    else:
        fractions = [i / (n - 1) for i in range(n)]

    paths: list[Path] = []
    for i, frac in enumerate(fractions):
        t = start + duration * frac
        # Evita cair exatamente no último frame (pode não existir).
        t = min(t, start + duration - 0.05) if duration > 0.1 else t
        t = max(t, start)
        out_path = out_dir / f"frame_{i}.jpg"
        run_ffmpeg(["-ss", str(t), "-i", str(video_path), "-frames:v", "1", "-q:v", "2", str(out_path)])
        paths.append(out_path)
    return paths


def _parse_score(raw: dict) -> Score:
    breakdown_raw = raw.get("breakdown", {})
    breakdown = ScoreBreakdown(
        hook=float(breakdown_raw.get("hook", 0)),
        emocao=float(breakdown_raw.get("emocao", 0)),
        citavel=float(breakdown_raw.get("citavel", 0)),
        arco=float(breakdown_raw.get("arco", 0)),
    )
    total = float(raw.get("total", breakdown.total)) or breakdown.total
    return Score(
        total=round(total, 2),
        breakdown=breakdown,
        reason=str(raw.get("reason", ""))[:500],
        context_complete=bool(raw.get("context_complete", True)),
    )


def score_candidate(
    candidate: Candidate,
    video_path: Path,
    settings: Settings,
    *,
    client: OpenRouterClient | None = None,
    feedback_examples: list[dict] | None = None,
) -> Score:
    """Avalia um candidato com texto + 3 frames via modelo de vision (SPEC §8)."""
    client = client or OpenRouterClient(settings)
    system = _load_prompt("score_pt.md")

    window = candidate.window_16x9
    with tempfile.TemporaryDirectory(prefix="clip_mvp_frames_") as tmp:
        frame_paths = extract_frames(video_path, window.start, window.end, Path(tmp), n=settings.frames_per_score)
        images_b64 = [image_to_b64(p) for p in frame_paths]

        feedback_text = ""
        if feedback_examples:
            feedback_text = "\nExemplos de feedback anterior (few-shot):\n" + "\n".join(
                f"- [{ex.get('verdict')}] score={ex.get('score')} reason={ex.get('reason')!r}"
                for ex in feedback_examples
            )

        user = (
            f"Título: {candidate.title}\n"
            f"Trecho da transcrição: {candidate.text_excerpt}\n"
            f"Notas do gerador de candidatos: {candidate.llm_notes}\n"
            f"context_complete (proposto): {candidate.context_complete}"
            f"{feedback_text}"
        )
        raw = client.chat_json(model=settings.score_model, system=system, user=user, images_b64=images_b64)

    return _parse_score(raw)


def score_candidates(
    candidates: list[Candidate],
    video_path: Path,
    settings: Settings,
    *,
    client: OpenRouterClient | None = None,
    feedback_examples: list[dict] | None = None,
) -> list[tuple[Candidate, Score]]:
    client = client or OpenRouterClient(settings)
    return [
        (c, score_candidate(c, video_path, settings, client=client, feedback_examples=feedback_examples))
        for c in candidates
    ]
