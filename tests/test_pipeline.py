"""Testes de ponta a ponta do pipeline, com download e IA mockados/fixture
(SPEC §12; "CLI end-to-end path exists, fixture/mocked ok where needed")."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from clip_mvp import pipeline as pipeline_mod
from clip_mvp.boundaries import crosses_word_midpoint
from clip_mvp.config import Settings
from clip_mvp.download import DownloadResult
from clip_mvp.models import Transcript


class FakeOpenRouterClient:
    """Cliente fake: nunca toca a rede. Distingue os prompts pelo conteúdo do
    `system` (cada prompt PT-BR tem uma frase-marcador única)."""

    def __init__(self, whisper_raw: dict, candidates_payload: dict, score_payload: dict, meta_payload: dict):
        self.whisper_raw = whisper_raw
        self.candidates_payload = candidates_payload
        self.score_payload = score_payload
        self.meta_payload = meta_payload
        self.chat_calls: list[dict] = []
        self.transcribe_calls: list[Path] = []

    def transcribe(self, audio_path: Path, *, language: str = "pt") -> dict:
        self.transcribe_calls.append(Path(audio_path))
        return self.whisper_raw

    def chat_json(self, *, model: str, system: str, user: str, images_b64=None, temperature: float = 0.4) -> dict:
        self.chat_calls.append({"model": model, "system": system[:20]})
        if "candidatos a corte" in system:
            return self.candidates_payload
        if "nota de 0 a 100" in system:
            return self.score_payload
        return self.meta_payload


@pytest.fixture()
def fake_client(whisper_verbose_json_raw) -> FakeOpenRouterClient:
    candidates_payload = {
        "candidates": [
            {
                "title": "Piada do treino que ninguém esperava",
                "text_excerpt": "Cê já tentou aquele treino novo? Sim, mas doeu tanto...",
                # Propositalmente no meio de palavras, para testar o snapping.
                "window_9x16": {"start": 0.5, "end": 6.6},
                "window_16x9": {"start": 0.05, "end": 9.85},
                "context_complete": True,
                "vertical_skip_reason": None,
                "llm_notes": "hook forte, punchline no final",
            }
        ]
    }
    score_payload = {
        "breakdown": {"hook": 22, "emocao": 21, "citavel": 23, "arco": 21},
        "total": 87,
        "context_complete": True,
        "reason": "Pergunta + resposta completa; punchline nos segundos finais",
    }
    meta_payload = {
        "youtube": {
            "shorts_title": "Ele tentou o treino e se arrependeu",
            "description": "Corte engraçado sobre treino.",
            "tags": ["treino", "engraçado"],
            "hashtags": ["#Shorts", "#treino"],
        },
        "tiktok": {"caption": "Isso doeu 😂", "hashtags": ["#fyp", "#treino", "#comedia", "#podcast"]},
    }
    return FakeOpenRouterClient(whisper_verbose_json_raw, candidates_payload, score_payload, meta_payload)


def _patch_download(monkeypatch, sample_video_path: Path):
    def fake_download_source(
        url: str, job_dir: Path, *, height: int = 720, on_progress=None
    ) -> DownloadResult:
        job_dir = Path(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        dest = job_dir / "source.mp4"
        shutil.copyfile(sample_video_path, dest)
        if on_progress:
            on_progress(0.5, "Baixando vídeo… 50%")
            on_progress(1.0, "Download concluído")
        return DownloadResult(
            video_path=dest,
            info_path=job_dir / "source.info.json",
            title="Fixture BR",
            duration_s=12.0,
            source_url=url,
        )

    monkeypatch.setattr(pipeline_mod, "download_source", fake_download_source)
    # sem isso o seed do ETA tentaria consultar a rede durante o teste
    monkeypatch.setattr(pipeline_mod, "probe_metadata", lambda url: {"duration": 12.0})


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        openrouter_api_key="test-key",
        work_dir=tmp_path / "work",
        out_dir=tmp_path / "out",
        # O vídeo de fixture tem ~10s, abaixo do piso de arco completo. Aqui
        # queremos testar o encanamento do pipeline, não a regra de duração
        # (que tem teste próprio em test_score_rules.py).
        min_duration_full_arc_s=0.0,
    )


def test_dry_run_stops_before_stt_and_returns_cost_estimate(tmp_path, monkeypatch, sample_video_path):
    _patch_download(monkeypatch, sample_video_path)
    settings = _settings(tmp_path)
    options = pipeline_mod.RunOptions(dry_run=True)

    summary = pipeline_mod.run_job("https://youtube.com/watch?v=fixture", settings, options)

    assert summary.dry_run is True
    assert summary.cost_estimate is not None
    assert summary.cost_estimate["total_usd"] >= 0
    # Não deve ter chamado STT/candidatos: nenhum transcript.json foi criado.
    job_dir = settings.work_dir / summary.job_id
    assert not (job_dir / "transcript.json").exists()
    assert not (job_dir / "candidates.json").exists()


def test_budget_too_low_aborts_before_transcribing(tmp_path, monkeypatch, sample_video_path):
    _patch_download(monkeypatch, sample_video_path)
    settings = _settings(tmp_path)
    options = pipeline_mod.RunOptions(budget=0.0000001)

    summary = pipeline_mod.run_job("https://youtube.com/watch?v=fixture", settings, options)

    assert summary.selected == 0
    assert summary.budget_warning is not None
    job_dir = settings.work_dir / summary.job_id
    assert not (job_dir / "transcript.json").exists()


def test_full_pipeline_end_to_end_mocked_ai(tmp_path, monkeypatch, sample_video_path, fake_client):
    """Roda o pipeline completo (download mockado, IA mockada, ffmpeg/mediapipe
    reais) e valida a saída em out/: meta.json, captions, exports, sem cortes
    no meio de palavra."""
    _patch_download(monkeypatch, sample_video_path)
    settings = _settings(tmp_path)
    options = pipeline_mod.RunOptions()

    summary = pipeline_mod.run_job(
        "https://youtube.com/watch?v=fixture", settings, options, client=fake_client
    )

    assert summary.selected == 1
    assert summary.vertical_ok == 1
    assert summary.vertical_skipped == 0

    clip = summary.clips[0]
    out_dir = Path(clip["out_dir"])
    assert out_dir.exists()
    assert (out_dir / "meta.json").exists()
    assert (out_dir / "horizontal_16x9.mp4").exists()
    assert (out_dir / "vertical_center.mp4").exists()
    assert (out_dir / "vertical_facetrack.mp4").exists()
    assert (out_dir / "captions.srt").exists()
    assert (out_dir / "captions_9x16.srt").exists()

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["score"] == 87
    assert meta["vertical_skipped"] is None
    assert meta["windows"]["vertical_9x16"]["duration_s"] <= settings.vertical_max_s
    assert meta["youtube"]["shorts_title"]
    assert meta["tiktok"]["caption"]
    assert meta["speaker_matching"]["method"] == "activity_proxy"
    # A fixture tem word timestamps, então o meta deve dizer isso — e dizer o
    # contrário quando o STT só der segmentos (SPEC §14.1).
    assert meta["boundaries"]["word_level_snapping"] is True
    assert meta["boundaries"]["pad_ms"] == [settings.pad_ms_min, settings.pad_ms_max]

    # Regra dura: nunca cortar no meio de palavra (SPEC §2.5/§14.1).
    job_dir = settings.work_dir / summary.job_id
    transcript = Transcript.model_validate(json.loads((job_dir / "transcript.json").read_text(encoding="utf-8")))
    words = transcript.all_words()
    v = meta["windows"]["vertical_9x16"]
    h = meta["windows"]["horizontal_16x9"]
    assert not crosses_word_midpoint(v["start"], v["end"], words)
    assert not crosses_word_midpoint(h["start"], h["end"], words)


def test_resume_reuses_cached_transcript_and_candidates(tmp_path, monkeypatch, sample_video_path, fake_client):
    _patch_download(monkeypatch, sample_video_path)
    settings = _settings(tmp_path)

    first = pipeline_mod.run_job(
        "https://youtube.com/watch?v=fixture", settings, pipeline_mod.RunOptions(), client=fake_client
    )
    n_transcribe_calls_before = len(fake_client.transcribe_calls)

    second = pipeline_mod.resume_job(
        first.job_id, settings, pipeline_mod.RunOptions(min_score=0), client=fake_client
    )

    # Não deve ter transcrito de novo nem regenerado candidatos (cache em work/<job_id>/).
    assert len(fake_client.transcribe_calls) == n_transcribe_calls_before
    assert second.candidates == first.candidates
