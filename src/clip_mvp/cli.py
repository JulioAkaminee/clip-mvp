"""CLI (typer) do clip-mvp — SPEC §11, §12 passo 1."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .config import get_settings
from .console import make_progress_sink
from .feedback import rate_clip as _rate_clip
from .models import Window
from .pipeline import JobCanceled, RunOptions, make_reporter, resume_job, run_job
from .progress import format_duration

app = typer.Typer(
    name="clip",
    help="Cortes automáticos a partir de link (YouTube/Twitch/etc), com IA via OpenRouter.",
    no_args_is_help=False,
)
console = Console()

_KNOWN_COMMANDS = {"run", "resume", "rate", "status", "serve", "test", "cut", "--help", "-h"}


def _parse_formats(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _print_summary(summary, *, elapsed: float | None = None) -> None:
    console.print(f"[bold]job_id[/bold]: {summary.job_id}")
    if summary.dry_run:
        console.print("[yellow]--dry-run[/yellow]: estimativa de custo (nenhuma chamada cara foi feita)")
        if summary.cost_estimate:
            console.print(summary.cost_estimate)
        return
    if elapsed is not None:
        console.print(f"[bold green]Pronto em {format_duration(elapsed)}[/bold green]")
    if summary.budget_warning:
        console.print(f"[yellow]{summary.budget_warning}[/yellow]")
    for note in summary.notes:
        console.print(f"- {note}")
    for clip in summary.clips:
        skip = f" (vertical_skipped={clip['vertical_skipped']})" if clip["vertical_skipped"] else ""
        console.print(f"  [green]{clip['score']}[/green] {clip['slug']}{skip} -> {clip['out_dir']}")


def _run_with_progress(runner, settings, job_id: str, *, quiet: bool, plain: bool):
    """Executa um job desenhando o progresso ao vivo (barra, estágios, ETA)."""
    reporter = make_reporter(settings, job_id)
    sink = make_progress_sink(quiet=quiet, plain=plain)
    reporter.add_sink(sink)
    sink.start()
    try:
        summary = runner(reporter)
    except JobCanceled:
        sink.stop()
        console.print("[yellow]Job cancelado.[/yellow]")
        raise typer.Exit(code=130)
    except Exception as exc:  # noqa: BLE001 - erro precisa virar mensagem, não stack trace
        sink.stop()
        error = reporter.snapshot().get("error") or {}
        console.print(f"\n[red]Erro em {error.get('stage_label', '?')}:[/red] {exc}")
        if error.get("hint"):
            console.print(f"[yellow]{error['hint']}[/yellow]")
        console.print(f"[blue]job_id:[/blue] {job_id}")
        raise typer.Exit(code=1)
    sink.stop()
    _print_summary(summary, elapsed=reporter.snapshot().get("elapsed_seconds"))
    return summary


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
    quiet: bool = typer.Option(False, "--quiet", help="Sem barra de progresso."),
    plain: bool = typer.Option(False, "--plain", help="Progresso em linhas simples (bom para log/CI)."),
) -> None:
    """Roda o pipeline completo para uma URL nova (SPEC §11)."""
    from .utils import make_job_id

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
    job_id = make_job_id(url)
    _run_with_progress(
        lambda reporter: run_job(url, settings, options, reporter=reporter),
        settings,
        job_id,
        quiet=quiet,
        plain=plain,
    )


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
    quiet: bool = typer.Option(False, "--quiet"),
    plain: bool = typer.Option(False, "--plain"),
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
    _run_with_progress(
        lambda reporter: resume_job(job_id, settings, options, reporter=reporter),
        settings,
        job_id,
        quiet=quiet,
        plain=plain,
    )


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


@app.command("status")
def status_cmd(
    job_id: Optional[str] = typer.Argument(None, help="job_id; vazio lista os últimos jobs."),
    watch: bool = typer.Option(False, "--watch", help="Acompanha até o job terminar."),
) -> None:
    """Mostra estágio, percentual e minutos restantes de um job (SPEC §11)."""
    import json
    import time

    settings = get_settings()
    work_dir = Path(settings.work_dir)

    if job_id is None:
        if not work_dir.exists():
            console.print("Nenhum job em work/.")
            return
        for path in sorted(work_dir.iterdir(), reverse=True)[:20]:
            status_path = path / "status.json"
            if not status_path.is_file():
                continue
            data = json.loads(status_path.read_text("utf-8"))
            console.print(
                f"{data['job_id']}  {data['status']:9} {data['percent']:5.1f}%  "
                f"{data['stage_label']}"
            )
        return

    status_path = work_dir / job_id / "status.json"
    while True:
        if not status_path.is_file():
            console.print(f"[yellow]job {job_id} ainda não registrou progresso[/yellow]")
            raise typer.Exit(code=1)
        data = json.loads(status_path.read_text("utf-8"))
        console.print(
            f"{data['percent']:5.1f}%  {data['stage_label']}  {data['eta_text']}  "
            f"({data['clips_done']}/{data['clips_total']} cortes)"
        )
        if not watch or data["status"] in {"done", "error", "canceled"}:
            if data["status"] == "error" and data.get("error"):
                console.print(f"[red]{data['error']['message']}[/red]")
                console.print(f"[yellow]{data['error'].get('hint', '')}[/yellow]")
            break
        time.sleep(2)


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
) -> None:
    """Sobe a API + UI web com progresso ao vivo e minutos restantes."""
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]Instale os extras da API:[/red] pip install 'fastapi>=0.111' 'uvicorn>=0.30'"
        )
        raise typer.Exit(code=1)

    from .server import create_app

    settings = get_settings()
    console.print(f"[bold green]UI em http://{host}:{port}[/bold green]")
    uvicorn.run(create_app(settings), host=host, port=port, log_level="warning")


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
