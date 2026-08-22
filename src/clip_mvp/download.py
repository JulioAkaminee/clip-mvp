"""Download de vídeo-fonte via yt-dlp (SPEC §4, §6)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .utils import ffprobe_duration


#: Onde cada navegador guarda os cookies, por plataforma. A auto-detecção olha
#: o disco em vez de chutar: apontar o yt-dlp para um navegador que não está
#: instalado derruba o download inteiro com um erro de perfil inexistente.
_BROWSER_COOKIE_PATHS: dict[str, tuple[str, ...]] = {
    "chrome": (
        "~/Library/Application Support/Google/Chrome",
        "~/.config/google-chrome",
    ),
    "brave": (
        "~/Library/Application Support/BraveSoftware/Brave-Browser",
        "~/.config/BraveSoftware/Brave-Browser",
    ),
    "edge": (
        "~/Library/Application Support/Microsoft Edge",
        "~/.config/microsoft-edge",
    ),
    "firefox": (
        "~/Library/Application Support/Firefox/Profiles",
        "~/.mozilla/firefox",
    ),
    "safari": (
        "~/Library/Containers/com.apple.Safari/Data/Library/Cookies",
        "~/Library/Cookies",
    ),
}

#: Ordem de preferência da auto-detecção.
_BROWSER_ORDER: tuple[str, ...] = ("chrome", "brave", "edge", "firefox", "safari")


def installed_cookie_browsers() -> list[str]:
    """Navegadores com perfil de cookies presente nesta máquina."""
    found = []
    for browser in _BROWSER_ORDER:
        for raw in _BROWSER_COOKIE_PATHS[browser]:
            if Path(raw).expanduser().exists():
                found.append(browser)
                break
    return found


def _cookies_opts() -> dict:
    """Opções de cookies do yt-dlp.

    O YouTube exige autenticação em vários vídeos ("Sign in to confirm you're
    not a bot"). Precedência:

    1. CLIP_YTDLP_COOKIE_FILE — arquivo Netscape cookies.txt
    2. CLIP_YTDLP_COOKIES_FROM_BROWSER — nome explícito do navegador
    3. Auto-detecção: o primeiro navegador **instalado** de
       :data:`_BROWSER_ORDER`
    """
    cookie_file = (os.getenv("CLIP_YTDLP_COOKIE_FILE") or "").strip()
    if cookie_file and Path(cookie_file).expanduser().is_file():
        return {"cookiefile": str(Path(cookie_file).expanduser())}

    from_browser = (os.getenv("CLIP_YTDLP_COOKIES_FROM_BROWSER") or "").strip().lower()
    if from_browser:
        return {"cookiesfrombrowser": (from_browser,)}

    detected = installed_cookie_browsers()
    if detected:
        return {"cookiesfrombrowser": (detected[0],)}
    return {}


def _js_runtime_opts() -> dict:
    """Aponta o Deno (ou Node) para o yt-dlp resolver o n-challenge do YouTube."""
    deno = shutil.which("deno") or "/usr/local/bin/deno"
    if Path(deno).exists():
        return {"js_runtimes": {"deno": {"path": deno}}}
    node = shutil.which("node")
    if node:
        return {"js_runtimes": {"node": {"path": node}}}
    return {}


def _player_client_opts() -> dict:
    """Escolha do player client do YouTube — por padrão, a do próprio yt-dlp.

    Fixar uma lista aqui parece inofensivo e não é: o YouTube muda o que cada
    client entrega, e os clients ``web``/``mweb`` hoje devolvem **só o formato
    18 (360p progressivo)**. Com isso o projeto inteiro passou a produzir corte
    a partir de 360p — o 9:16 recortava 202x360 e ampliava 5x. O padrão do
    yt-dlp é mantido upstream e devolve os formatos adaptativos até 1080p.

    ``CLIP_YTDLP_PLAYER_CLIENT`` continua existindo como escape para quando um
    vídeo específico só abrir com um client determinado.
    """
    raw = (os.getenv("CLIP_YTDLP_PLAYER_CLIENT") or "").strip()
    if not raw:
        return {}
    clients = [item.strip() for item in raw.split(",") if item.strip()]
    return {"extractor_args": {"youtube": {"player_client": clients}}} if clients else {}


def _base_ydl_opts() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        **_player_client_opts(),
        **_js_runtime_opts(),
        **_cookies_opts(),
    }


def _format_selection(height: int) -> dict:
    """Como escolher o formato do YouTube.

    Duas decisões, as duas medidas nesta máquina:

    * **Resolução manda.** ``bestvideo`` sozinho já errou: num podcast com
      1080p disponível ele trouxe 720p, e o 9:16 recorta 9/16 da largura da
      fonte — 720p vira um recorte de 405px que precisa esticar 2,7x. O
      ``format_sort`` com ``res:{height}`` torna a preferência explícita em vez
      de depender do ranking interno.
    * **Entre formatos da mesma resolução, o menor arquivo ganha.** O instinto
      é fugir do AV1 por medo do decode em software, mas aqui o dav1d
      decodificou 90s de 1080p60 em 5,5s contra 6,4s do H.264 — AV1 é mais
      rápido *e* o arquivo é 45% menor (2,3GB contra 4,1GB no mesmo vídeo).
      Como o download é ~um quarto do tempo do job, o arquivo menor vale mais
      que qualquer preferência de codec.

    O ``?`` em ``height<=?`` mantém no páreo formatos que não declaram altura
    (arquivo direto, extractor genérico), que de outro modo seriam filtrados
    para fora e derrubariam o job no download.
    """
    return {
        "format": f"bestvideo[height<=?{height}]+bestaudio/best[height<=?{height}]/best",
        "format_sort": [f"res:{height}", "fps", "+size"],
    }


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

    opts = {**_base_ydl_opts(), "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}


def download_source(
    url: str,
    job_dir: Path,
    *,
    height: int = 1080,
    on_progress: Callable[[float, str], None] | None = None,
) -> DownloadResult:
    """Baixa vídeo (até height p) + salva metadata (info.json) em job_dir."""
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
        **_base_ydl_opts(),
        **_format_selection(height),
        "outtmpl": out_template,
        "merge_output_format": "mp4",
        "writeinfojson": True,
        "noplaylist": True,
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
