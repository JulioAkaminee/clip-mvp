"""Modelos de domínio compartilhados entre pipeline, CLI e API."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .boundaries import Window


@dataclass
class Breakdown:
    hook: int = 0
    emocao: int = 0
    citavel: int = 0
    arco: int = 0

    @property
    def total(self) -> int:
        return self.hook + self.emocao + self.citavel + self.arco

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Breakdown":
        data = data or {}
        return cls(
            hook=int(data.get("hook", 0) or 0),
            emocao=int(data.get("emocao", 0) or 0),
            citavel=int(data.get("citavel", 0) or 0),
            arco=int(data.get("arco", 0) or 0),
        )


@dataclass
class Candidate:
    """Momento proposto pelo LLM, já com janelas normalizadas."""

    id: str
    title: str
    reason: str
    horizontal: Window
    vertical: Window | None
    transcript_text: str = ""
    score: int = 0
    breakdown: Breakdown = field(default_factory=Breakdown)
    context_complete: bool = True
    vertical_skipped: str | None = None
    dedupe_of: str | None = None
    slug: str = ""

    @property
    def duration(self) -> float:
        return self.horizontal.duration

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "reason": self.reason,
            "slug": self.slug,
            "horizontal": self.horizontal.to_dict(),
            "vertical": self.vertical.to_dict() if self.vertical else None,
            "transcript_text": self.transcript_text,
            "score": self.score,
            "breakdown": self.breakdown.to_dict(),
            "context_complete": self.context_complete,
            "vertical_skipped": self.vertical_skipped,
            "dedupe_of": self.dedupe_of,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Candidate":
        def _window(raw: dict | None) -> Window | None:
            if not raw:
                return None
            return Window(
                start=float(raw["start"]),
                end=float(raw["end"]),
                context_complete=bool(raw.get("context_complete", True)),
                method=raw.get("boundary_method", "word"),
                note=raw.get("note"),
            )

        horizontal = _window(data["horizontal"])
        assert horizontal is not None
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            reason=data.get("reason", ""),
            slug=data.get("slug", ""),
            horizontal=horizontal,
            vertical=_window(data.get("vertical")),
            transcript_text=data.get("transcript_text", ""),
            score=int(data.get("score", 0) or 0),
            breakdown=Breakdown.from_dict(data.get("breakdown")),
            context_complete=bool(data.get("context_complete", True)),
            vertical_skipped=data.get("vertical_skipped"),
            dedupe_of=data.get("dedupe_of"),
        )


@dataclass
class SelectionStats:
    mode: str = "auto"
    candidates: int = 0
    selected: int = 0
    deduped: int = 0
    below_threshold: int = 0
    min_score: int = 60
    target_min: int = 0
    target_max: int = 0
    vertical_ok: int = 0
    vertical_skipped: int = 0
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "SelectionStats":
        data = data or {}
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})
