"""Score de viralização: texto + 3 frames (vision) — SPEC §8."""

from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib import resources
from pathlib import Path
from typing import Callable

from .config import Settings
from .models import Candidate, Score, ScoreBreakdown
from .openrouter import OpenRouterClient, image_to_b64
from .utils import run_ffmpeg

#: Teto de score para trecho com contexto aberto (SPEC §8: penalidade dura).
TRUNCATED_SCORE_CAP = 45.0
#: Um corte que não fecha a ideia não pode pontuar alto em "arco".
TRUNCATED_ARCO_CAP = 6.0
#: Abaixo disso não há espaço para setup → punch completo.
MIN_DURATION_FOR_FULL_ARC_S = 12.0
SHORT_CLIP_SCORE_CAP = 70.0

TERMINAL_PUNCT = ".!?…"


def _load_prompt(name: str) -> str:
    return resources.files("clip_mvp.prompts").joinpath(name).read_text(encoding="utf-8")


#: Largura dos frames enviados ao scorer. O modelo de vision só precisa ver se
#: há pessoa falando, reação e enquadramento; mandar 720p cru só engorda o
#: payload em base64 e a latência de cada chamada.
FRAME_WIDTH = 512


def extract_frames(
    video_path: Path,
    start: float,
    end: float,
    out_dir: Path,
    *,
    n: int = 3,
    width: int = FRAME_WIDTH,
) -> list[Path]:
    """Extrai `n` frames (início/meio/fim, por padrão) do trecho [start, end]
    do vídeo-fonte, usados como entrada de vision no scorer (SPEC §8).

    Frames já existentes são reaproveitados: com ``out_dir`` dentro de
    ``work/<job_id>/`` um ``resume`` não repete a extração.
    """
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
        if out_path.exists() and out_path.stat().st_size > 0:
            paths.append(out_path)
            continue
        run_ffmpeg(
            [
                "-ss",
                str(t),
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                f"scale={width}:-2",
                "-q:v",
                "6",
                str(out_path),
            ]
        )
        paths.append(out_path)
    return paths


def looks_truncated(text: str) -> bool:
    """Heurística barata: o trecho termina no meio de uma ideia?"""
    stripped = (text or "").strip()
    if not stripped:
        return False
    return stripped[-1] not in TERMINAL_PUNCT


def apply_quality_rules(
    score: Score,
    *,
    text_excerpt: str,
    duration_s: float,
    boundary_context_complete: bool = True,
    settings: Settings | None = None,
) -> Score:
    """Aplica a penalidade dura da SPEC §8 em cima da nota do modelo.

    O scorer se apaixona por momentos fortes mesmo quando o trecho começa ou
    termina no meio da fala. Corte truncado não é publicável, então o teto é
    inegociável e vale independentemente do que o modelo respondeu.
    """
    truncated_cap = settings.truncated_score_cap if settings else TRUNCATED_SCORE_CAP
    min_arc_s = settings.min_duration_full_arc_s if settings else MIN_DURATION_FOR_FULL_ARC_S
    short_cap = settings.short_clip_score_cap if settings else SHORT_CLIP_SCORE_CAP

    context_complete = score.context_complete and boundary_context_complete
    notes: list[str] = []
    breakdown = score.breakdown.model_copy()
    total = score.total

    if not context_complete or looks_truncated(text_excerpt):
        context_complete = False
        if breakdown.arco > TRUNCATED_ARCO_CAP:
            breakdown.arco = TRUNCATED_ARCO_CAP
        if total > truncated_cap:
            total = truncated_cap
            notes.append(f"penalidade: contexto não fecha (teto {truncated_cap:.0f})")

    if min_arc_s > 0 and 0 < duration_s < min_arc_s and total > short_cap:
        total = short_cap
        notes.append("corte curto demais para arco completo")

    reason = score.reason
    if notes:
        reason = f"{reason} ({'; '.join(notes)})".strip()

    return Score(
        total=round(max(0.0, min(100.0, total)), 2),
        breakdown=breakdown,
        reason=reason[:500],
        context_complete=context_complete,
    )


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
    frames_dir: Path | None = None,
    use_vision: bool = True,
) -> Score:
    """Avalia um candidato com texto + 3 frames via modelo de vision (SPEC §8).

    ``frames_dir`` mantém os frames em ``work/<job_id>/`` para que um
    ``resume`` não pague de novo pela extração (SPEC §14.4).
    """
    client = client or OpenRouterClient(settings)
    system = _load_prompt("score_pt.md")

    window = candidate.window_16x9
    tmp_ctx = None
    if frames_dir is None:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="clip_mvp_frames_")
        target_dir = Path(tmp_ctx.name)
    else:
        target_dir = Path(frames_dir) / candidate.id

    try:
        images_b64: list[str] = []
        if use_vision:
            frame_paths = extract_frames(
                video_path, window.start, window.end, target_dir, n=settings.frames_per_score
            )
            images_b64 = [image_to_b64(p) for p in frame_paths]

        feedback_text = ""
        if feedback_examples:
            feedback_text = "\nExemplos de feedback anterior (few-shot):\n" + "\n".join(
                f"- [{ex.get('verdict')}] score={ex.get('score')} reason={ex.get('reason')!r}"
                for ex in feedback_examples
            )

        user = (
            f"Título: {candidate.title}\n"
            f"Duração do corte: {window.duration_s:.1f}s\n"
            f"Trecho da transcrição: {candidate.text_excerpt}\n"
            f"Notas do gerador de candidatos: {candidate.llm_notes}\n"
            f"context_complete (proposto): {candidate.context_complete}"
            f"{feedback_text}"
        )
        raw = client.chat_json(model=settings.score_model, system=system, user=user, images_b64=images_b64)
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()

    return apply_quality_rules(
        _parse_score(raw),
        text_excerpt=candidate.text_excerpt,
        duration_s=window.duration_s,
        boundary_context_complete=candidate.context_complete,
        settings=settings,
    )


def score_candidates(
    candidates: list[Candidate],
    video_path: Path,
    settings: Settings,
    *,
    client: OpenRouterClient | None = None,
    feedback_examples: list[dict] | None = None,
    frames_dir: Path | None = None,
    use_vision: bool = True,
    on_progress: Callable[[int, int, Candidate, Score], None] | None = None,
) -> list[tuple[Candidate, Score]]:
    """Avalia todos os candidatos em paralelo limitado (I/O de rede).

    Um candidato que falha não derruba o job: recebe nota 0 e o pipeline segue
    com os demais.
    """
    client = client or OpenRouterClient(settings)
    if not candidates:
        return []

    results: dict[str, Score] = {}
    workers = max(1, min(settings.network_workers, len(candidates)))

    def work(candidate: Candidate) -> tuple[Candidate, Score]:
        try:
            score = score_candidate(
                candidate,
                video_path,
                settings,
                client=client,
                feedback_examples=feedback_examples,
                frames_dir=frames_dir,
                use_vision=use_vision,
            )
        except Exception as exc:  # noqa: BLE001
            score = Score(
                total=0.0,
                breakdown=ScoreBreakdown(),
                reason=f"falha ao avaliar: {exc}",
                context_complete=False,
            )
        return candidate, score

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, c) for c in candidates]
        for future in as_completed(futures):
            candidate, score = future.result()
            results[candidate.id] = score
            done += 1
            if on_progress:
                on_progress(done, len(candidates), candidate, score)

    # devolve na ordem original: a ordem de conclusão do pool é arbitrária
    return [(c, results[c.id]) for c in candidates if c.id in results]
