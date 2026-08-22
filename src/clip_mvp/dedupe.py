"""Dedupe de momentos (SPEC 14.3).

* overlap temporal > 50% → mantém o de maior score;
* mesma punchline / texto muito parecido → mantém o de maior score.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import Candidate

OVERLAP_THRESHOLD = 0.50
TEXT_SIMILARITY_THRESHOLD = 0.72
PUNCHLINE_WORDS = 18
MIN_CHARS_FOR_TEXT_MATCH = 120
"""Trechos curtos se parecem por acidente; só comparamos texto de verdade."""


def overlap_ratio(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Fração do menor intervalo coberta pela interseção."""
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    shortest = min(a_end - a_start, b_end - b_start)
    if shortest <= 0:
        return 0.0
    return inter / shortest


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9áàâãéêíóôõúç ]+", " ", (text or "").lower()).strip()


def _punchline(text: str) -> str:
    words = _normalize(text).split()
    return " ".join(words[-PUNCHLINE_WORDS:])


def text_similarity(a: str, b: str) -> float:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def is_duplicate(a: Candidate, b: Candidate) -> tuple[bool, str]:
    ratio = overlap_ratio(
        a.horizontal.start, a.horizontal.end, b.horizontal.start, b.horizontal.end
    )
    if ratio > OVERLAP_THRESHOLD:
        return True, f"overlap_{int(ratio * 100)}pct"

    text_a, text_b = a.transcript_text or "", b.transcript_text or ""
    if min(len(text_a), len(text_b)) < MIN_CHARS_FOR_TEXT_MATCH:
        return False, ""
    if text_similarity(text_a, text_b) >= TEXT_SIMILARITY_THRESHOLD:
        return True, "texto_similar"
    punch_a, punch_b = _punchline(text_a), _punchline(text_b)
    if min(len(punch_a.split()), len(punch_b.split())) >= 8:
        if text_similarity(punch_a, punch_b) >= 0.8:
            return True, "mesma_punchline"
    return False, ""


def dedupe(candidates: list[Candidate]) -> tuple[list[Candidate], list[tuple[Candidate, str]]]:
    """Retorna (mantidos, removidos com motivo), preservando o maior score."""
    ordered = sorted(candidates, key=lambda c: (-c.score, c.horizontal.start))
    kept: list[Candidate] = []
    removed: list[tuple[Candidate, str]] = []
    for candidate in ordered:
        duplicate_of: Candidate | None = None
        reason = ""
        for winner in kept:
            dup, why = is_duplicate(candidate, winner)
            if dup:
                duplicate_of, reason = winner, why
                break
        if duplicate_of is None:
            kept.append(candidate)
        else:
            candidate.dedupe_of = duplicate_of.id
            removed.append((candidate, reason))
    kept.sort(key=lambda c: c.horizontal.start)
    return kept, removed
