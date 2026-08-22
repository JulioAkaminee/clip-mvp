"""CLI (SPEC 11).

    clip "URL"                       # auto
    clip "URL" --more
    clip "URL" --count 12
    clip "URL" --dry-run --budget 2
    clip resume <job_id> --more
    clip rate <job_id> <slug> good
    clip serve                       # API + UI web local
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import typer

from .config import ALL_FORMATS, DEFAULT_MIN_SCORE, VERSION, get_settings
from .feedback import load_ratings, rate as rate_clip
from .jobstate import JobRecord, StateReporter, create_record
from .pipeline import JobOptions, run_job
from .paths import job_out_dir

cli = typer.Typer(
    add_completion=False,
    help="Cortes automáticos de vídeos longos (YouTube Shorts / TikTok / 16:9).",
    no_args_is_help=True,
)

FORMAT_ALIASES = {
    "face": "vertical_facetrack",
    "facetrack": "vertical_facetrack",
    "9x16": "vertical_center",
    "vertical": "vertical_center",
    "center": "vertical_center",
    "16x9": "horizontal_16x9",
    "horizontal": "horizontal_16x9",
}


class ConsoleReporter(StateReporter):
    """Progresso legível no terminal + `work/<job>/job.json` para a UI web."""

    def __init__(self, record: JobRecord, verbose: bool = False):
        super().__init__(record)
        self.verbose = verbose
        self._last_stage = ""

    def stage(self, key, status="running", progress=None, message=""):
        super().stage(key, status, progress, message)
        if status == "running" and key == self._last_stage and not self.verbose:
            if progress is not None:
                bar = _bar(progress)
                typer.echo(f"\r  {bar} {message[:70]:<70}", nl=False)
            return
        if self._last_stage and key != self._last_stage:
            typer.echo("")
        self._last_stage = key
        icon = {"running": "▶", "done": "✓", "skipped": "–", "error": "✗"}.get(status, "·")
        typer.echo(f"{icon} {key}: {message}")

    def log(self, message, level="info"):
        super().log(message, level)
        if level == "debug" and not self.verbose:
            return
        prefix = {"warn": "! ", "error": "✗ ", "debug": "· "}.get(level, "  ")
        typer.echo(f"{prefix}{message}")

    def estimate(self, estimate):
        super().estimate(estimate)
        typer.echo(
            f"  custo estimado: US$ {estimate['total_usd']:.3f}"
            + (
                f" (orçamento US$ {estimate['budget_usd']:.2f})"
                if estimate.get("budget_usd")
                else ""
            )
        )

    def selection(self, stats):
        super().selection(stats)
        typer.echo(
            f"  selected={stats['selected']} candidates={stats['candidates']} "
            f"deduped={stats['deduped']} vertical_ok={stats['vertical_ok']} "
            f"vertical_skipped={stats['vertical_skipped']}"
        )

    def clip(self, clip):
        super().clip(clip)
        if self.verbose:
            typer.echo(f"  → {clip['score']:>3} {clip['slug']}")


def _bar(progress: float, width: int = 18) -> str:
    filled = int(max(0.0, min(1.0, progress)) * width)
    return "[" + "█" * filled + "·" * (width - filled) + "]"


def _parse_formats(raw: str) -> tuple[str, ...]:
    formats: list[str] = []
    for token in raw.split(","):
        token = token.strip().lower()
        if not token:
            continue
        name = FORMAT_ALIASES.get(token, token)
        if name not in ALL_FORMATS:
            raise typer.BadParameter(f"formato desconhecido: {token}")
        if name not in formats:
            formats.append(name)
    if not formats:
        raise typer.BadParameter("escolha pelo menos um formato")
    return tuple(formats)


def _execute(record: JobRecord, verbose: bool):
    """Roda o pipeline mantendo `job.json` coerente para a UI web."""
    reporter = ConsoleReporter(record, verbose=verbose)
    record.status = "running"
    record.started_at = time.time()
    record.save()
    try:
        result = run_job(record.id, record.options, reporter)
    except Exception as exc:  # noqa: BLE001
        record.status = "error"
        record.error = str(exc) or exc.__class__.__name__
        record.finished_at = time.time()
        record.save()
        typer.echo("")
        typer.secho(f"erro: {record.error}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    record.status = "done"
    record.finished_at = time.time()
    record.clips = result.clips or record.clips
    record.selection = result.selection or record.selection
    record.estimate = result.estimate or record.estimate
    record.source = result.source or record.source
    record.save()
    return result


@cli.command("run")
def run(
    url: str = typer.Argument(..., help="URL do vídeo (ou caminho de arquivo local)"),
    more: bool = typer.Option(False, "--more", help="~+50% cortes vs. o auto"),
    count: int | None = typer.Option(None, "--count", help="Força até N cortes"),
    min_score: int = typer.Option(DEFAULT_MIN_SCORE, "--min-score", help="Limiar de score"),
    max_score_only: int | None = typer.Option(
        None, "--max-score-only", help="Só cortes com score >= N"
    ),
    formats: str = typer.Option("face,9x16,16x9", "--formats"),
    captions: str = typer.Option("both", "--captions", help="burn|sidecar|both"),
    platforms: str = typer.Option("yt,tiktok", "--platforms"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Só estima custo OpenRouter"),
    budget: float | None = typer.Option(None, "--budget", help="Teto de custo em USD"),
    demo: bool = typer.Option(False, "--demo", help="Roda sem OpenRouter (dados sintéticos)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Roda o pipeline completo em uma URL."""
    options = JobOptions(
        url=url,
        mode="count" if count else ("more" if more else "auto"),
        count=count,
        min_score=min_score,
        max_score_only=max_score_only,
        formats=_parse_formats(formats),
        captions=captions,
        platforms=tuple(p.strip() for p in platforms.split(",") if p.strip()),
        dry_run=dry_run,
        budget_usd=budget,
        demo=demo or None,
    )
    record = create_record(options)
    job_id = record.id
    typer.echo(f"job {job_id}")
    result = _execute(record, verbose)
    typer.echo("")
    if result.dry_run:
        typer.secho("dry-run: nada foi baixado nem renderizado.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    typer.secho(
        f"{len(result.clips)} cortes em {job_out_dir(job_id)}", fg=typer.colors.GREEN
    )
    for clip in result.clips:
        vertical = clip["windows"].get("vertical_9x16")
        vertical_info = (
            f"9:16 {vertical['duration_s']:.0f}s"
            if vertical
            else f"9:16 descartado ({clip.get('vertical_skipped')})"
        )
        typer.echo(
            f"  {clip['score']:>3}  {clip['slug']}  "
            f"16:9 {clip['windows']['horizontal_16x9']['duration_s']:.0f}s · {vertical_info}"
        )


@cli.command("resume")
def resume(
    job_id: str = typer.Argument(..., help="ID do job em work/"),
    more: bool = typer.Option(False, "--more"),
    count: int | None = typer.Option(None, "--count"),
    min_score: int | None = typer.Option(None, "--min-score"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Re-roda um job usando transcrição/scores já em `work/<job_id>/`."""
    record = JobRecord.load(job_id)
    if record is None:
        source_path = get_settings().work_dir / job_id / "source.json"
        if not source_path.exists():
            typer.secho(f"job {job_id} não encontrado em work/", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        data = json.loads(source_path.read_text(encoding="utf-8"))
        record = JobRecord(id=job_id, options=JobOptions(url=data.get("url", "")))

    record.options.mode = "count" if count else ("more" if more else "auto")
    record.options.count = count
    record.options.dry_run = False
    if min_score is not None:
        record.options.min_score = min_score
    record.clips = []
    record.selection = None
    record.error = None
    record.resumed_from = job_id
    record.reset_stages()
    typer.echo(f"resume {job_id} (modo {record.options.mode})")
    result = _execute(record, verbose)
    typer.echo("")
    typer.secho(f"{len(result.clips)} cortes em {job_out_dir(job_id)}", fg=typer.colors.GREEN)


@cli.command("rate")
def rate(
    job_id: str = typer.Argument(...),
    clip_slug: str = typer.Argument(...),
    verdict: str = typer.Argument(..., help="good|bad"),
    note: str = typer.Option("", "--note"),
) -> None:
    """Marca um corte como good/bad (vira few-shot nos próximos prompts)."""
    if verdict not in {"good", "bad"}:
        raise typer.BadParameter("verdict deve ser good ou bad")
    score, title, reason = 0, clip_slug, ""
    for meta_path in job_out_dir(job_id).glob(f"*_{clip_slug}/meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        score = int(meta.get("score") or 0)
        title = meta.get("title") or clip_slug
        reason = meta.get("reason") or ""
        break
    rate_clip(
        job_id=job_id,
        clip_slug=clip_slug,
        verdict=verdict,
        score=score,
        reason=reason,
        title=title,
        note=note,
    )
    typer.secho(f"feedback salvo: {clip_slug} = {verdict}", fg=typer.colors.GREEN)


@cli.command("feedback")
def feedback(limit: int = typer.Option(20, "--limit")) -> None:
    """Lista os últimos veredictos gravados."""
    ratings = load_ratings(limit=limit)
    if not ratings:
        typer.echo("sem feedback ainda (use `clip rate`)")
        return
    for entry in ratings:
        mark = "+" if entry.verdict == "good" else "-"
        typer.echo(f"{mark} {entry.job_id} {entry.clip_slug} (score {entry.score}) {entry.note}")


@cli.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Sobe a API + UI web local."""
    import uvicorn

    settings = get_settings()
    dist = settings.root / "web" / "dist"
    typer.echo(f"clip-mvp {VERSION} → http://{host}:{port}")
    if not (dist / "index.html").exists():
        typer.secho(
            "UI não buildada: rode `cd web && npm install && npm run build` "
            "(ou `npm run dev` para hot reload em :5173).",
            fg=typer.colors.YELLOW,
        )
    uvicorn.run(
        "clip_mvp.api.app:get_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
        log_level="info",
    )


@cli.command("test")
def test_fixture(
    path: Path = typer.Option(
        None, "--fixture", help="Vídeo local de teste (default: tests/fixtures/expected.json)"
    ),
) -> None:
    """Roda a fixture BR e valida as expectativas mínimas (SPEC 14.8)."""
    import subprocess

    root = get_settings().root
    cmd = [sys.executable, "-m", "pytest", "-q", str(root / "tests")]
    if path:
        cmd.extend(["--fixture-video", str(path)])
    raise typer.Exit(code=subprocess.call(cmd, cwd=root))


@cli.command("version")
def version() -> None:
    typer.echo(VERSION)


def main() -> None:
    """`clip "URL"` funciona sem digitar `run`."""
    argv = sys.argv[1:]
    known = {"run", "resume", "rate", "feedback", "serve", "test", "version", "--help", "-h"}
    if argv and argv[0] not in known and not argv[0].startswith("-"):
        sys.argv.insert(1, "run")
    cli()


if __name__ == "__main__":  # pragma: no cover
    main()
