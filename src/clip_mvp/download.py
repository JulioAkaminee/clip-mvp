"""Download de vídeo-fonte via yt-dlp (SPEC §4, §6)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .utils import ffprobe_duration


@dataclass
class DownloadResult:
    video_path: Path
    info_path: Path
    title: str
    duration_s: float
    source_url: str


def probe_metadata(url: str) -> dict:
    """Lê metadados sem baixar — dá ao ETA uma duração antes do primeiro byte."""
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
        return ydl.extract_info(url, download=False) or {}


def download_source(
    url: str,
    job_dir: Path,
    *,
    height: int = 720,
    on_progress: Callable[[float, str], None] | None = None,
) -> DownloadResult:
    """Baixa vídeo (até `height`p) + salva metadata (info.json) em `job_dir`.

    Import de `yt_dlp` é feito dentro da função para manter o import do
    pacote leve e permitir mockar em testes sem a dependência de rede.

    ``on_progress(fração, mensagem)`` recebe o andamento do download para
    alimentar a barra de progresso e o ETA.
    """
    import yt_dlp

    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(job_dir / "source.%(ext)s")

    def hook(status: dict) -> None:
        if on_progress is None:
            return
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            if total:
                fraction = min(1.0, done / total)
                on_progress(fraction, f"Baixando vídeo… {fraction * 100:.0f}%")
        elif status.get("status") == "finished":
            on_progress(1.0, "Download concluído, juntando faixas…")

    ydl_opts = {
        "format": f"bestvideo[height<={height}]+bestaudio/best[height<={height}]",
        "outtmpl": out_template,
        "merge_output_format": "mp4",
        "writeinfojson": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        # retoma download parcial em vez de recomeçar do zero
        "continuedl": True,
        "progress_hooks": [hook],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_path = Path(ydl.prepare_filename(info))
        if video_path.suffix != ".mp4":
            candidate = video_path.with_suffix(".mp4")
            if candidate.exists():
                video_path = candidate

    info_path = job_dir / "source.info.json"
    duration = info.get("duration") or 0.0
    if not duration and video_path.exists():
        try:
            duration = ffprobe_duration(video_path)
        except Exception:
            duration = 0.0

    return DownloadResult(
        video_path=video_path,
        info_path=info_path,
        title=info.get("title", ""),
        duration_s=float(duration),
        source_url=url,
    )
