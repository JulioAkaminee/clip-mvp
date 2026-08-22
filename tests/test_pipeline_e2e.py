"""Fixture de ponta a ponta (SPEC 14.8).

Roda o pipeline inteiro num vídeo local curto e valida as expectativas de
`tests/fixtures/expected.json`. Sem o vídeo da fixture o teste é skipado.
"""

import json
import shutil
from pathlib import Path

import pytest

from clip_mvp.config import VERTICAL_MAX_S, get_settings
from clip_mvp.jobstate import JobRecord, StateReporter, create_record
from clip_mvp.paths import job_out_dir
from clip_mvp.pipeline import JobOptions, run_job
from clip_mvp.transcript import Transcript

EXPECTED = json.loads(
    (Path(__file__).parent / "fixtures" / "expected.json").read_text(encoding="utf-8")
)["expectativas"]


@pytest.fixture(scope="module")
def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def test_pipeline_completo(fixture_video, ffmpeg_available):
    if fixture_video is None:
        pytest.skip("sem tests/fixtures/demo_480s.mp4 (veja expected.json)")
    if not ffmpeg_available:
        pytest.skip("ffmpeg indisponível")

    options = JobOptions(url=str(fixture_video), mode="count", count=2, demo=True)
    record: JobRecord = create_record(options)
    result = run_job(record.id, options, StateReporter(record))

    assert result.clips, "o job não entregou nenhum corte"
    assert result.selection["selected"] == len(result.clips)

    transcript = Transcript.load(get_settings().work_dir / record.id / "transcript.json")
    words = transcript.words
    contexto_fechado = 0
    verticais_ok = 0

    for clip in result.clips:
        clip_dir = Path(clip["dir"])
        assert clip_dir.is_dir()
        for artifact in ("horizontal_16x9.mp4", "captions.srt", "meta.json"):
            assert (clip_dir / artifact).exists(), f"{artifact} ausente em {clip_dir.name}"

        meta = json.loads((clip_dir / "meta.json").read_text(encoding="utf-8"))
        for key in EXPECTED["meta_json_obrigatorio"]:
            assert key in meta, f"meta.json sem '{key}'"
        assert meta["audio"]["loudnorm"] is True

        horizontal = clip["windows"]["horizontal_16x9"]
        vertical = clip["windows"]["vertical_9x16"]
        if clip["context_complete"]:
            contexto_fechado += 1

        if vertical:
            assert vertical["duration_s"] <= VERTICAL_MAX_S + 0.001, "9:16 passou de 90s"
            verticais_ok += 1
            assert (clip_dir / "vertical_center.mp4").exists()
        else:
            assert clip["vertical_skipped"], "sem 9:16 e sem motivo registrado"

        # Nenhuma fronteira pode cair no meio de uma palavra.
        for edge in (horizontal["start"], horizontal["end"]):
            assert not any(
                word.start < edge < word.end for word in words
            ), f"corte no meio de palavra em {edge:.3f}s"

    assert contexto_fechado >= EXPECTED["min_clips_com_contexto_fechado"]
    assert verticais_ok >= EXPECTED["min_clips_9x16_ate_90s"]
    assert job_out_dir(record.id).is_dir()


def test_resume_reaproveita_cache(fixture_video, ffmpeg_available):
    """`resume` não pode re-baixar nem re-transcrever."""
    if fixture_video is None or not ffmpeg_available:
        pytest.skip("fixture indisponível")

    options = JobOptions(
        url=str(fixture_video),
        mode="count",
        count=1,
        formats=("horizontal_16x9",),
        captions="sidecar",
        demo=True,
    )
    record = create_record(options)
    run_job(record.id, options, StateReporter(record))
    transcript_path = get_settings().work_dir / record.id / "transcript.json"
    stamp = transcript_path.stat().st_mtime

    options.mode = "more"
    run_job(record.id, options, StateReporter(record))
    assert transcript_path.stat().st_mtime == stamp, "transcrição foi refeita no resume"
