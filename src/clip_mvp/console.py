"""Renderização do progresso no terminal (com ETA em PT-BR)."""

from __future__ import annotations

import sys
import threading
from typing import Any

from .progress import STAGE_ORDER, format_duration

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, TextColumn
    from rich.table import Table

    RICH = True
except Exception:  # pragma: no cover - rich é opcional
    RICH = False

_STAGE_ICON = {
    "pending": "·",
    "running": "▸",
    "done": "✓",
    "skipped": "↷",
    "error": "✗",
}


class PlainProgressPrinter:
    """Fallback sem rich: uma linha por atualização relevante."""

    def __init__(self, stream=sys.stderr) -> None:
        self.stream = stream
        self._last_key: tuple[Any, ...] | None = None
        self._lock = threading.Lock()

    def __call__(self, payload: dict[str, Any]) -> None:
        key = (
            payload.get("stage"),
            int(payload.get("percent") or 0),
            payload.get("message"),
            payload.get("clips_done"),
        )
        with self._lock:
            if key == self._last_key:
                return
            self._last_key = key
            line = (
                f"[{payload.get('percent', 0):5.1f}%] "
                f"{payload.get('stage_label', '')} — {payload.get('message', '')}"
            )
            eta = payload.get("eta_text")
            if payload.get("status") == "running" and eta:
                line += f"  ({eta})"
            print(line, file=self.stream, flush=True)

    def start(self) -> None:  # paridade de API com LiveProgressDisplay
        return None

    def stop(self) -> None:
        return None


class LiveProgressDisplay:
    """Painel ao vivo: barra global, ETA, lista de estágios e status por clipe."""

    def __init__(self) -> None:
        if not RICH:
            raise RuntimeError("rich não está instalado")
        self.console = Console(stderr=True)
        self.progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("{task.percentage:>5.1f}%"),
            TextColumn("[dim]{task.fields[eta]}"),
            console=self.console,
            transient=False,
        )
        self.task = self.progress.add_task("Preparando…", total=100, eta="")
        self._live: Live | None = None
        self._payload: dict[str, Any] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        self._live = Live(self._render(), console=self.console, refresh_per_second=6)
        self._live.start()

    def stop(self) -> None:
        if self._live is not None:
            self._live.update(self._render())
            self._live.stop()
            self._live = None

    def __call__(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._payload = payload
            eta = payload.get("eta_text") or ""
            if payload.get("status") in {"done", "error", "canceled"}:
                eta = ""
            self.progress.update(
                self.task,
                completed=float(payload.get("percent") or 0.0),
                description=payload.get("stage_label", ""),
                eta=eta,
            )
            if self._live is not None:
                self._live.update(self._render())

    def _render(self):
        payload = self._payload
        stages_table = Table.grid(padding=(0, 1))
        stages_table.add_column(width=2)
        stages_table.add_column(ratio=1)
        stages_table.add_column(justify="right", width=10)

        by_name = {s["name"]: s for s in payload.get("stages", [])}
        for name in STAGE_ORDER:
            stage = by_name.get(name)
            if not stage:
                continue
            icon = _STAGE_ICON.get(stage["status"], "·")
            style = {
                "pending": "dim",
                "running": "bold cyan",
                "done": "green",
                "skipped": "yellow",
                "error": "bold red",
            }.get(stage["status"], "")
            detail = stage.get("message") or stage["label"]
            elapsed = stage.get("elapsed_seconds")
            right = (
                format_duration(elapsed)
                if stage["status"] in {"done", "skipped"} and elapsed
                else (f"{stage['percent']:.0f}%" if stage["status"] == "running" else "")
            )
            stages_table.add_row(f"[{style}]{icon}[/]", f"[{style}]{detail}[/]", right)

        renderables = [self.progress, stages_table]

        clips = payload.get("clips") or []
        if clips:
            clips_table = Table.grid(padding=(0, 1))
            clips_table.add_column(width=2)
            clips_table.add_column(ratio=1)
            clips_table.add_column(justify="right", width=22)
            for clip in clips:
                icon = _STAGE_ICON.get(clip["status"], "·")
                formats = ", ".join(
                    f"{k.replace('vertical_', '9:16 ').replace('horizontal_16x9', '16:9')}"
                    f"{'✓' if v == 'done' else ('…' if v == 'running' else '✗')}"
                    for k, v in (clip.get("formats") or {}).items()
                )
                score = f"{clip['score']:.0f}" if clip.get("score") is not None else "-"
                clips_table.add_row(icon, f"{score} · {clip['slug']}", formats)
            renderables.append(
                Panel(
                    clips_table,
                    title=(
                        f"Cortes {payload.get('clips_done', 0)}/{payload.get('clips_total', 0)}"
                    ),
                    border_style="dim",
                )
            )

        error = payload.get("error")
        if error:
            hint = error.get("hint") or ""
            renderables.append(
                Panel(
                    f"[bold red]{error.get('message')}[/]\n[dim]{hint}[/]",
                    title=f"Erro em {error.get('stage_label')}",
                    border_style="red",
                )
            )
        return Group(*renderables)


def make_progress_sink(quiet: bool = False, plain: bool = False):
    """Escolhe o renderizador adequado ao terminal."""
    if quiet:
        class _Noop:
            def __call__(self, payload: dict[str, Any]) -> None:
                return None

            def start(self) -> None:
                return None

            def stop(self) -> None:
                return None

        return _Noop()
    if plain or not RICH or not sys.stderr.isatty():
        return PlainProgressPrinter()
    return LiveProgressDisplay()
