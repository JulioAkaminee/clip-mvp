"""`clip rate good|bad` → work/feedback.jsonl → few-shot nos prompts (SPEC §14.7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from .utils import now_iso, read_json

Verdict = Literal["good", "bad"]


def _selected_entry(work_dir: Path, job_id: str, clip_slug: str) -> dict[str, Any] | None:
    selected_path = Path(work_dir) / job_id / "selected.json"
    if not selected_path.exists():
        return None
    for item in read_json(selected_path):
        if item.get("slug") == clip_slug:
            return item
    return None


def rate_clip(
    work_dir: Path,
    job_id: str,
    clip_slug: str,
    verdict: Verdict,
    *,
    note: str = "",
) -> dict[str, Any]:
    """Registra o veredito do usuário para um clip em `work/feedback.jsonl`
    (SPEC §14.7). Não falha se o job/slug não for encontrado — grava o que
    tiver disponível, já que o feedback pode ser sobre um clip antigo."""
    entry = _selected_entry(work_dir, job_id, clip_slug)

    record = {
        "timestamp": now_iso(),
        "job_id": job_id,
        "slug": clip_slug,
        "score": entry.get("score") if entry else None,
        "reason": entry.get("reason") if entry else None,
        "verdict": verdict,
        "note": note or "",
    }

    feedback_path = Path(work_dir) / "feedback.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    with open(feedback_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record


def load_recent_feedback(work_dir: Path, n: int = 6) -> list[dict[str, Any]]:
    """Carrega os `n` registros de feedback mais recentes, para injeção
    few-shot nos prompts de candidatos/score (SPEC §14.7)."""
    path = Path(work_dir) / "feedback.jsonl"
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    records = [json.loads(ln) for ln in lines]
    return records[-n:]


def write_selected_index(work_dir: Path, job_id: str, entries: list[dict[str, Any]]) -> Path:
    """Grava work/<job_id>/selected.json: índice slug -> score/reason/out_dir,
    usado por `clip rate` para localizar o clip sem precisar escanear out/."""
    from .utils import write_json

    path = Path(work_dir) / job_id / "selected.json"
    write_json(path, entries)
    return path
