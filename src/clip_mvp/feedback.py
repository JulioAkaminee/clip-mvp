"""Loop de feedback `clip rate` → few-shot nos prompts (SPEC 14.7)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict

from .config import Settings, get_settings

MAX_FEW_SHOT = 6


@dataclass
class Rating:
    job_id: str
    clip_slug: str
    verdict: str
    score: int = 0
    reason: str = ""
    title: str = ""
    note: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def rate(
    job_id: str,
    clip_slug: str,
    verdict: str,
    score: int = 0,
    reason: str = "",
    title: str = "",
    note: str = "",
    settings: Settings | None = None,
) -> Rating:
    if verdict not in {"good", "bad"}:
        raise ValueError("verdict deve ser 'good' ou 'bad'")
    settings = settings or get_settings()
    entry = Rating(
        job_id=job_id,
        clip_slug=clip_slug,
        verdict=verdict,
        score=score,
        reason=reason,
        title=title,
        note=note,
        created_at=time.time(),
    )
    path = settings.feedback_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
    return entry


def load_ratings(settings: Settings | None = None, limit: int | None = None) -> list[Rating]:
    settings = settings or get_settings()
    path = settings.feedback_path
    if not path.exists():
        return []
    ratings: list[Rating] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        ratings.append(
            Rating(
                job_id=data.get("job_id", ""),
                clip_slug=data.get("clip_slug", ""),
                verdict=data.get("verdict", "good"),
                score=int(data.get("score") or 0),
                reason=data.get("reason", ""),
                title=data.get("title", ""),
                note=data.get("note", ""),
                created_at=float(data.get("created_at") or 0.0),
            )
        )
    ratings.sort(key=lambda r: r.created_at, reverse=True)
    return ratings[:limit] if limit else ratings


def ratings_for_job(job_id: str, settings: Settings | None = None) -> dict[str, Rating]:
    """Último veredicto por clip do job."""
    out: dict[str, Rating] = {}
    for rating in reversed(load_ratings(settings)):
        if rating.job_id == job_id:
            out[rating.clip_slug] = rating
    return out


def few_shot_block(settings: Settings | None = None, limit: int = MAX_FEW_SHOT) -> str:
    """Exemplos recentes good/bad para injetar nos prompts (PT-BR)."""
    ratings = load_ratings(settings, limit=limit)
    if not ratings:
        return ""
    good = [r for r in ratings if r.verdict == "good"]
    bad = [r for r in ratings if r.verdict == "bad"]
    lines = ["MEMÓRIA DE FEEDBACK DO USUÁRIO (use para calibrar o gosto do canal):"]
    for label, group in (("APROVADOS", good), ("REPROVADOS", bad)):
        if not group:
            continue
        lines.append(f"{label}:")
        for r in group:
            detail = f" — nota do usuário: {r.note}" if r.note else ""
            lines.append(f"- \"{r.title or r.clip_slug}\" (score {r.score}): {r.reason}{detail}")
    return "\n".join(lines)
