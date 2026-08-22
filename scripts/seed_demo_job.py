"""Gera um job completo em work/ e out/ com as chamadas de IA mockadas.

Serve para inspecionar a UI (preview, safe area, chips de formato) sem gastar
OpenRouter. Não faz parte do produto: é ferramenta de verificação local.

    python scripts/seed_demo_job.py
    clip serve
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from clip_mvp import pipeline as pipeline_mod  # noqa: E402
from clip_mvp.config import Settings  # noqa: E402
from clip_mvp.download import DownloadResult  # noqa: E402
from test_pipeline import FakeOpenRouterClient  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
URL = "https://youtube.com/watch?v=demo-pt-br"


def _fake_client() -> FakeOpenRouterClient:
    # Fixture com speaker labels: o demo exercita o crop guiado por falante
    # (SPEC §14.6) em vez do fallback, que é o caminho mais interessante de olhar.
    whisper_raw = json.loads((FIXTURES / "whisper_verbose_json_diarized.json").read_text("utf-8"))
    candidates = {
        "candidates": [
            {
                "title": "A pergunta sobre o treino novo",
                "text_excerpt": "Cê já tentou aquele treino novo?",
                "window_9x16": {"start": 0.05, "end": 9.85},
                "window_16x9": {"start": 0.05, "end": 9.85},
                "context_complete": True,
                "llm_notes": "pergunta + resposta + punchline nos segundos finais",
            }
        ]
    }
    score = {
        "total": 87,
        "breakdown": {"hook": 22, "emocao": 21, "citavel": 23, "arco": 21},
        "context_complete": True,
        "reason": "Pergunta fechada com punchline no fim; riso genuíno no último terço.",
    }
    meta = {
        "youtube": {
            "shorts_title": "Ele tentou o treino novo e não conseguiu nem rir",
            "long_title": "O treino que quebrou todo mundo | corte do podcast",
            "description": "O momento em que a academia venceu.",
            "tags": ["treino", "academia", "podcast br"],
            "hashtags": ["#Shorts", "#treino", "#academia"],
        },
        "tiktok": {
            "caption": "doeu tanto que não conseguia nem rir 😭",
            "hashtags": ["#fyp", "#treino", "#academia", "#humor", "#br"],
        },
    }
    return FakeOpenRouterClient(whisper_raw, candidates, score, meta)


def _patch_download() -> None:
    def fake_download_source(url, job_dir, *, height=720, on_progress=None):
        job_dir = Path(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        dest = job_dir / "source.mp4"
        shutil.copyfile(FIXTURES / "sample_video.mp4", dest)
        if on_progress:
            on_progress(1.0, "Baixando vídeo… 100%")
        return DownloadResult(
            video_path=dest,
            info_path=job_dir / "source.info.json",
            title="Podcast BR (fixture)",
            duration_s=12.0,
            source_url=url,
        )

    pipeline_mod.download_source = fake_download_source
    pipeline_mod.probe_metadata = lambda url: {"duration": 12.0}


def main() -> int:
    _patch_download()
    settings = Settings(
        openrouter_api_key="demo-key",
        work_dir=ROOT / "work",
        out_dir=ROOT / "out",
        min_duration_full_arc_s=0.0,
    )
    summary = pipeline_mod.run_job(URL, settings, pipeline_mod.RunOptions(), client=_fake_client())
    print(f"job_id={summary.job_id} selected={summary.selected}")
    for clip in summary.clips:
        print(f"  {clip['score']:>3}  {clip['slug']}  -> {clip['out_dir']}")
        meta_path = Path(clip["out_dir"]) / "meta.json"
        if meta_path.is_file():
            print(json.dumps(json.loads(meta_path.read_text("utf-8")), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
