"""CLI (typer) do clip-mvp — SPEC §11, §12 passo 1."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .config import get_settings
from .feedback import rate_clip as _rate_clip
from .models import Window
from .pipeline import RunOptions, resume_job, run_job

app = typer.Typer(
    name="clip",
    help="Cortes automáticos a partir de link (YouTube/Twitch/etc), com IA via OpenRouter.",
    no_args_is_help=False,
)
console = Console()

_KNOWN_COMMANDS = {"run", "resume", "rate", "test", "cut", "--help", "-h"}


def _parse_formats(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _print_summary(summary) -> None:
    console.print(f"[bold]job_id[/bold]: {summary.job_id}")
    if summary.dry_run:
        console.print("[yellow]--dry-run[/yellow]: estimativa de custo (nenhuma chamada cara foi feita)")
        if summary.cost_estimate:
            console.print(summary.cost_estimate)
        return
    if summary.budget_warning:
        console.print(f"[yellow]{summary.budget_warning}[/yellow]")
    for note in summary.notes:
        console.print(f"- {note}")
    for clip in summary.clips:
        skip = f" (vertical_skipped={clip['vertical_skipped']})" if clip["vertical_skipped"] else ""
        console.print(f"  [green]{clip['score']}[/green] {clip['slug']}{skip} -> {clip['out_dir']}")


@app.command("run")
def run_cmd(
    url: str = typer.Argument(..., help="URL do vídeo-fonte (YouTube/Twitch/etc)."),
    more: bool = typer.Option(False, "--more", help="Pede ~+50% de cortes vs. o auto."),
    count: Optional[int] = typer.Option(None, "--count", help="Força até N cortes (sujeito ao limiar)."),
    min_score: Optional[float] = typer.Option(None, "--min-score", help="Afrouxa/aperta o limiar (default 60)."),
    max_score_only: Optional[float] = typer.Option(
        None, "--max-score-only", help="Só clips com score >= valor informado."
    ),
    formats: str = typer.Option("face,9x16,16x9", "--formats", help="Subconjunto de: face,9x16,16x9."),
    captions: str = typer.Option("both", "--captions", help="burn|sidecar|both"),
    platforms: str = typer.Option("yt,tiktok", "--platforms", help="Subconjunto de: yt,tiktok"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Estima custo OpenRouter e para antes do passo caro."),
    budget: Optional[float] = typer.Option(None, "--budget", help="Orçamento em USD; reduz candidatos ou aborta."),
) -> None:
    """Roda o pipeline completo para uma URL nova (SPEC §11)."""
    settings = get_settings()
    options = RunOptions(
        more=more,
        count=count,
        min_score=min_score,
        max_score_only=max_score_only,
        formats=_parse_formats(formats),
        captions=captions,
        platforms=_parse_formats(platforms),
        dry_run=dry_run,
        budget=budget,
    )
    summary = run_job(url, settings, options)
    _print_summary(summary)


@app.command("resume")
def resume_cmd(
    job_id: str = typer.Argument(..., help="job_id retornado por uma execução anterior."),
    more: bool = typer.Option(False, "--more"),
    count: Optional[int] = typer.Option(None, "--count"),
    min_score: Optional[float] = typer.Option(None, "--min-score"),
    max_score_only: Optional[float] = typer.Option(None, "--max-score-only"),
    formats: str = typer.Option("face,9x16,16x9", "--formats"),
    captions: str = typer.Option("both", "--captions"),
    platforms: str = typer.Option("yt,tiktok", "--platforms"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    budget: Optional[float] = typer.Option(None, "--budget"),
) -> None:
    """Reusa transcrição + candidatos já em work/<job_id>/ (sem re-download) — SPEC §3."""
    settings = get_settings()
    options = RunOptions(
        more=more,
        count=count,
        min_score=min_score,
        max_score_only=max_score_only,
        formats=_parse_formats(formats),
        captions=captions,
        platforms=_parse_formats(platforms),
        dry_run=dry_run,
        budget=budget,
    )
    summary = resume_job(job_id, settings, options)
    _print_summary(summary)


@app.command("rate")
def rate_cmd(
    job_id: str = typer.Argument(...),
    clip_slug: str = typer.Argument(...),
    verdict: str = typer.Argument(..., help="good|bad"),
    note: Optional[str] = typer.Option(None, "--note"),
) -> None:
    """`clip rate <job_id> <clip_slug> good|bad` — feedback few-shot (SPEC §14.7)."""
    if verdict not in ("good", "bad"):
        console.print("[red]verdict deve ser 'good' ou 'bad'[/red]")
        raise typer.Exit(code=1)
    settings = get_settings()
    record = _rate_clip(settings.work_dir, job_id, clip_slug, verdict, note=note or "")
    console.print(f"Feedback registrado: {record}")


@app.command("cut")
def cut_cmd(
    video: Path = typer.Argument(..., help="Caminho do vídeo local."),
    start: float = typer.Argument(...),
    end: float = typer.Argument(...),
    out: Path = typer.Argument(...),
) -> None:
    """Corte manual por timestamp (utilitário de baixo nível, SPEC §12 passo 1)."""
    from .render import cut_raw

    cut_raw(video, Window(start=start, end=end), out)
    console.print(f"Cortado: {out}")


@app.command("test")
def test_cmd() -> None:
    """Roda a suíte de testes (pytest) usando as fixtures BR (SPEC §14.8)."""
    import pytest

    repo_root = Path(__file__).resolve().parents[2]
    code = pytest.main([str(repo_root / "tests"), "-q"])
    raise typer.Exit(code=code)


def main() -> None:
    """Entrypoint do console script `clip`. Permite tanto `clip "URL"`
    (equivalente a `clip run "URL"`) quanto os subcomandos explícitos
    (`resume`, `rate`, `test`, `cut`) — SPEC §11."""
    args = sys.argv[1:]
    if args and args[0] not in _KNOWN_COMMANDS and not args[0].startswith("-"):
        args = ["run", *args]
        sys.argv = [sys.argv[0], *args]
    app()


if __name__ == "__main__":
    main()
