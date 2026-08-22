"""Download da fonte via yt-dlp (vídeo 720p + áudio)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ffmpeg_utils import duration_of

PROGRESS_RE = re.compile(r"(\d{1,3}(?:\.\d)?)%")


class DownloadError(RuntimeError):
    pass


@dataclass
class SourceMedia:
    path: Path
    title: str
    duration_s: float
    url: str
    uploader: str = ""
    thumbnail: str = ""

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "title": self.title,
            "duration_s": self.duration_s,
            "url": self.url,
            "uploader": self.uploader,
            "thumbnail": self.thumbnail,
        }


def _yt_dlp_cmd() -> list[str]:
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    return [sys.executable, "-m", "yt_dlp"]


def probe_source(url: str, timeout: float = 90.0) -> dict:
    """Metadados sem baixar (título, duração) — usado pelo `--dry-run`."""
    cmd = [*_yt_dlp_cmd(), "--no-warnings", "--dump-single-json", "--no-playlist", url]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise DownloadError(
            f"yt-dlp não conseguiu ler a URL: {(proc.stderr or '').strip().splitlines()[-1:] or ''}"
        )
    data = json.loads(proc.stdout or "{}")
    return {
        "title": data.get("title") or "video",
        "duration_s": float(data.get("duration") or 0.0),
        "uploader": data.get("uploader") or "",
        "thumbnail": data.get("thumbnail") or "",
    }


def download(
    url: str,
    dest_dir: Path,
    on_progress: Callable[[float, str], None] | None = None,
    max_height: int = 720,
) -> SourceMedia:
    """Baixa a fonte em <=720p (SPEC 15: economizar disco no Mac)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(dest_dir.glob("source.*"))
    meta_path = dest_dir / "source.json"
    if existing and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return SourceMedia(
            path=Path(meta["path"]),
            title=meta.get("title", "video"),
            duration_s=float(meta.get("duration_s") or 0.0),
            url=url,
            uploader=meta.get("uploader", ""),
            thumbnail=meta.get("thumbnail", ""),
        )

    info = probe_source(url)
    output_template = str(dest_dir / "source.%(ext)s")
    cmd = [
        *_yt_dlp_cmd(),
        "--no-warnings",
        "--no-playlist",
        "--newline",
        "-f",
        f"bv*[height<={max_height}]+ba/b[height<={max_height}]/bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
        url,
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        tail.append(line)
        tail[:] = tail[-30:]
        match = PROGRESS_RE.search(line)
        if match and on_progress:
            on_progress(min(1.0, float(match.group(1)) / 100.0), line)
    code = proc.wait()
    if code != 0:
        raise DownloadError("falha no download:\n" + "\n".join(tail[-8:]))

    files = [p for p in dest_dir.glob("source.*") if p.suffix.lower() != ".json"]
    if not files:
        raise DownloadError("yt-dlp terminou mas nenhum arquivo foi criado")
    path = max(files, key=lambda p: p.stat().st_size)
    media = SourceMedia(
        path=path,
        title=info["title"],
        duration_s=info["duration_s"] or duration_of(path),
        url=url,
        uploader=info["uploader"],
        thumbnail=info["thumbnail"],
    )
    meta_path.write_text(
        json.dumps(media.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return media
