"""Speaker↔rosto no face track (SPEC §9 "Falantes (2+ pessoas)", §14.6).

O que estes testes protegem: a diarização precisa **mexer o crop**. Ter a
timeline no `meta.json` e mandar o mesmo enquadramento de sempre para o render
era o buraco que fazia um podcast de duas pessoas virar um Short apontado para
quem estava calado.
"""

from __future__ import annotations

import json
from pathlib import Path

from clip_mvp import pipeline as pipeline_mod
from clip_mvp.diarization import (
    diarization_from_transcript,
    resolve_speaker_matching_method,
    speaker_at,
    speaker_timeline,
)
from clip_mvp.face_track import (
    FaceObservation,
    assign_speakers_to_slots,
    face_slots,
    fill_gaps,
    smooth_centers,
    speaker_targets,
)
from clip_mvp.models import Segment, Transcript, Word
from test_pipeline import _patch_download, _settings, fake_client  # noqa: F401

LEFT_X = 0.25
RIGHT_X = 0.75


def _two_face_scene(n_samples: int, *, talking: list[str | None]) -> list[list[FaceObservation]]:
    """Cena com dois rostos parados; só quem "fala" se move (proxy de boca)."""
    frames: list[list[FaceObservation]] = []
    for i in range(n_samples):
        jitter = 0.01 if i % 2 else -0.01
        who = talking[i] if i < len(talking) else None
        frames.append(
            [
                FaceObservation(
                    cx=LEFT_X + (jitter if who == "A" else 0.0),
                    cy=0.4 + (jitter if who == "A" else 0.0),
                    area=0.05,
                ),
                FaceObservation(
                    cx=RIGHT_X + (jitter if who == "B" else 0.0),
                    cy=0.4 + (jitter if who == "B" else 0.0),
                    area=0.05,
                ),
            ]
        )
    return frames


def _transcript_with_speakers() -> Transcript:
    segments = [
        Segment(
            id=0,
            start=0.0,
            end=4.0,
            text="Pergunta longa.",
            words=[Word(start=0.0, end=4.0, text="Pergunta")],
            speaker="SPEAKER_00",
        ),
        Segment(
            id=1,
            start=4.2,
            end=8.0,
            text="Resposta longa.",
            words=[Word(start=4.2, end=8.0, text="Resposta")],
            speaker="SPEAKER_01",
        ),
    ]
    return Transcript(duration=8.0, segments=segments, has_word_timestamps=True)


# -- timeline a partir da transcrição ---------------------------------------


def test_diarization_comes_from_transcript_speaker_labels():
    result = diarization_from_transcript(_transcript_with_speakers())
    assert result.method == "diarization"
    assert [s.speaker for s in result.segments] == ["SPEAKER_00", "SPEAKER_01"]


def test_diarization_merges_consecutive_turns_of_same_speaker():
    """O STT quebra por frase; uma fala corrida não é troca de falante."""
    transcript = Transcript(
        segments=[
            Segment(id=0, start=0.0, end=2.0, text="Primeira.", speaker="A"),
            Segment(id=1, start=2.1, end=4.0, text="Segunda.", speaker="A"),
            Segment(id=2, start=4.5, end=6.0, text="Outra pessoa.", speaker="B"),
        ]
    )
    result = diarization_from_transcript(transcript)
    assert [(s.start, s.end, s.speaker) for s in result.segments] == [
        (0.0, 4.0, "A"),
        (4.5, 6.0, "B"),
    ]


def test_diarization_unavailable_without_speaker_labels():
    transcript = Transcript(segments=[Segment(id=0, start=0.0, end=2.0, text="Sem label.")])
    result = diarization_from_transcript(transcript)
    assert result.method == "unavailable"
    assert resolve_speaker_matching_method(result) == "activity_proxy"


def test_speaker_matching_method_is_activity_proxy_when_facetrack_is_off():
    """Sem 9:16 face não existe crop guiado: dizer "diarization" seria enfeite."""
    result = diarization_from_transcript(_transcript_with_speakers())
    assert resolve_speaker_matching_method(result, used_for_crop=False) == "activity_proxy"


def test_speaker_timeline_samples_the_window_at_face_track_rate():
    result = diarization_from_transcript(_transcript_with_speakers())
    timeline = speaker_timeline(result, start=0.0, n_samples=80, dt=0.1)

    assert len(timeline) == 80
    assert timeline[0] == "SPEAKER_00"
    assert timeline[70] == "SPEAKER_01"
    # A lacuna entre turnos (4.0s -> 4.2s) é silêncio, não um falante.
    assert timeline[41] is None
    assert speaker_at(result, 5.0) == "SPEAKER_01"


def test_speaker_timeline_is_all_none_without_diarization():
    assert speaker_timeline(None, start=0.0, n_samples=3, dt=0.1) == [None, None, None]


# -- mapeamento speaker -> rosto -------------------------------------------


def test_face_slots_separates_two_people_by_position():
    frames = _two_face_scene(40, talking=["A"] * 40)
    slots = face_slots(frames)
    assert len(slots) == 2
    assert abs(slots[0] - LEFT_X) < 0.05
    assert abs(slots[1] - RIGHT_X) < 0.05


def test_face_slots_ignores_a_one_off_detection_glitch():
    frames = _two_face_scene(40, talking=[None] * 40)
    frames[7].append(FaceObservation(cx=0.02, cy=0.9, area=0.001))
    assert len(face_slots(frames)) == 2


def test_speakers_map_to_the_face_that_moves_while_they_talk():
    talking = ["A"] * 20 + ["B"] * 20
    frames = _two_face_scene(40, talking=talking)

    assignment = assign_speakers_to_slots(frames, talking, face_slots(frames))

    slots = face_slots(frames)
    assert abs(slots[assignment["A"]] - LEFT_X) < 0.05
    assert abs(slots[assignment["B"]] - RIGHT_X) < 0.05


def test_two_speakers_never_share_the_same_face():
    """O mapeamento é um-para-um: sem isso o crop trava numa pessoa só."""
    talking = ["A"] * 20 + ["B"] * 20
    frames = _two_face_scene(40, talking=talking)
    assignment = assign_speakers_to_slots(frames, talking, face_slots(frames))
    assert len(set(assignment.values())) == len(assignment)


def test_crop_follows_the_active_speaker_across_the_turn():
    talking = ["A"] * 20 + ["B"] * 20
    frames = _two_face_scene(40, talking=talking)

    targets, _ = speaker_targets(frames, talking, dt=0.1)

    assert targets[5] is not None and abs(targets[5].cx - LEFT_X) < 0.05
    assert targets[35] is not None and abs(targets[35].cx - RIGHT_X) < 0.05


def test_speaker_change_crossfades_instead_of_cutting():
    talking = ["A"] * 20 + ["B"] * 20
    frames = _two_face_scene(40, talking=talking)

    targets, allowance = speaker_targets(frames, talking, dt=0.1, crossfade_s=0.4)
    smoothed = smooth_centers(fill_gaps(targets, dt=0.1), step_allowance=allowance)

    # A folga de velocidade só existe na troca.
    assert allowance[20] > 0
    assert allowance[5] == 0
    # E o crop realmente chega no rosto novo pouco depois da troca, sem salto
    # de um frame para o outro.
    jumps = [abs(smoothed[i + 1].cx - smoothed[i].cx) for i in range(len(smoothed) - 1)]
    assert max(jumps) < abs(RIGHT_X - LEFT_X) / 2
    assert abs(smoothed[26].cx - RIGHT_X) < 0.1


def test_without_diarization_target_is_the_largest_face():
    """Fallback documentado (activity_proxy, SPEC §14.6): o rosto mais em foco."""
    frames = [
        [FaceObservation(cx=0.2, cy=0.4, area=0.01), FaceObservation(cx=0.8, cy=0.4, area=0.09)]
    ] * 10

    targets, allowance = speaker_targets(frames, [None] * 10, dt=0.1)

    assert all(t is not None and abs(t.cx - 0.8) < 1e-6 for t in targets)
    assert all(step == 0 for step in allowance)


def test_speaker_without_a_visible_face_falls_back_to_the_proxy():
    """Falante fora de quadro não deve congelar o crop num rosto vazio."""
    frames = [[FaceObservation(cx=0.6, cy=0.4, area=0.05)]] * 10

    targets, _ = speaker_targets(frames, ["C"] * 10, dt=0.1)

    assert all(t is not None and abs(t.cx - 0.6) < 1e-6 for t in targets)


# -- o pipeline entrega a timeline ao render --------------------------------


def test_pipeline_feeds_the_speaker_timeline_into_the_facetrack_render(
    tmp_path, monkeypatch, sample_video_path, whisper_verbose_json_diarized, fake_client
):
    """A ponta solta que este teste fecha: a diarização ia para o `meta.json` e o
    render recebia o enquadramento padrão de sempre."""
    _patch_download(monkeypatch, sample_video_path)
    settings = _settings(tmp_path)
    fake_client.whisper_raw = whisper_verbose_json_diarized

    seen: list[list[str | None] | None] = []
    real_render = pipeline_mod.face_track_mod.render_vertical_facetrack

    def spy(video_path, window, out_path, **kwargs):
        seen.append(kwargs.get("speakers"))
        return real_render(video_path, window, out_path, **kwargs)

    monkeypatch.setattr(pipeline_mod.face_track_mod, "render_vertical_facetrack", spy)

    summary = pipeline_mod.run_job(
        "https://youtube.com/watch?v=diarized", settings, pipeline_mod.RunOptions(), client=fake_client
    )

    assert summary.selected == 1
    assert len(seen) == 1
    timeline = seen[0]
    assert timeline is not None
    assert {label for label in timeline if label} == {"SPEAKER_00", "SPEAKER_01"}

    meta = json.loads((Path(summary.clips[0]["out_dir"]) / "meta.json").read_text(encoding="utf-8"))
    assert meta["speaker_matching"]["method"] == "diarization"


def test_diarization_does_not_pay_for_a_second_transcription(
    tmp_path, monkeypatch, sample_video_path, whisper_verbose_json_diarized, fake_client
):
    """SPEC §14.4: o `--budget` estima UM STT. Diarizar com uma segunda passada
    de áudio dobrava o custo real sem aparecer na estimativa."""
    _patch_download(monkeypatch, sample_video_path)
    settings = _settings(tmp_path)
    fake_client.whisper_raw = whisper_verbose_json_diarized

    pipeline_mod.run_job(
        "https://youtube.com/watch?v=diarized", settings, pipeline_mod.RunOptions(), client=fake_client
    )

    assert len(fake_client.transcribe_calls) == 1
