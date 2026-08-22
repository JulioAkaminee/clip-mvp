"""Enquadramento e qualidade de corte: o que separa um Short publicável de um
arquivo tecnicamente válido mas ruim de assistir.

Cada teste aqui existe porque a versão anterior errava exatamente naquilo.
"""

from __future__ import annotations

import os

from clip_mvp.boundaries import extend_window_to_minimum
from clip_mvp.download import _base_ydl_opts, _player_client_opts
from clip_mvp.face_track import (
    FaceCenter,
    resample_centers,
    smooth_centers,
)
from clip_mvp.models import Segment, Transcript, Word
from clip_mvp.render import (
    fit_output_size,
    source_matches_aspect,
    vertical_blur_filter,
    vertical_fill_filter,
)
from clip_mvp.transcribe import drop_hallucinated_segments, looks_like_boilerplate


def _words(rows: list[tuple[float, float, str]]) -> list[Word]:
    return [Word(start=a, end=b, text=t) for a, b, t in rows]


class TestCropMotionIsPerFrame:
    """O crop tem de andar por quadro, não por amostra de detecção.

    A detecção roda a ~12 Hz e o vídeo sai a 30 ou 60 fps. Emitindo um comando
    por amostra, cada posição segurava por 3 a 5 quadros e o movimento virava
    degrau — tranco lateral visível.
    """

    def _ramp(self, n: int = 13) -> list[FaceCenter]:
        return [FaceCenter(t=i / 12.0, cx=0.30 + i * 0.02, cy=0.4) for i in range(n)]

    def test_resampling_produces_one_center_per_output_frame(self):
        out = resample_centers(self._ramp(), sample_dt=1 / 12.0, out_fps=60.0)
        assert len(out) == 61  # 1 s de rampa a 60 fps

    def test_resampling_shrinks_the_per_frame_jump(self):
        source = self._ramp()
        out = resample_centers(source, sample_dt=1 / 12.0, out_fps=60.0)
        before = max(abs(source[i].cx - source[i - 1].cx) for i in range(1, len(source)))
        after = max(abs(out[i].cx - out[i - 1].cx) for i in range(1, len(out)))
        assert after < before / 4

    def test_a_scene_cut_is_not_smeared_across_frames(self):
        """Interpolar por cima de um corte de câmera arrasta o enquadramento
        pelo quadro novo. Ali o salto é o comportamento certo."""
        centers = [
            FaceCenter(t=0.0, cx=0.20, cy=0.4),
            FaceCenter(t=1 / 12.0, cx=0.80, cy=0.4, scene_cut=True),
        ]
        out = resample_centers(centers, sample_dt=1 / 12.0, out_fps=60.0)
        seen = {round(c.cx, 3) for c in out}
        assert seen <= {0.2, 0.8}, "houve interpolação entre os dois planos"


class TestSceneCutSnapsInsteadOfGliding:
    def test_smoothing_restarts_on_a_camera_change(self):
        centers = [
            FaceCenter(t=0.0, cx=0.20, cy=0.4),
            FaceCenter(t=0.1, cx=0.85, cy=0.4, scene_cut=True),
            FaceCenter(t=0.2, cx=0.85, cy=0.4),
        ]
        out = smooth_centers(centers)
        assert out[1].cx == 0.85

    def test_without_a_cut_the_speed_limit_still_applies(self):
        centers = [
            FaceCenter(t=0.0, cx=0.20, cy=0.4),
            FaceCenter(t=0.1, cx=0.85, cy=0.4),
        ]
        out = smooth_centers(centers)
        assert out[1].cx < 0.30, "sem corte, o crop não pode teleportar"


class TestOutputNeverUpscalesBeyondTheSource:
    """Ampliar 360p para 1080p não cria detalhe: só triplica o arquivo e o
    tempo de render."""

    def test_a_small_source_keeps_its_own_size(self):
        assert fit_output_size(640, 360, (1920, 1080)) == (640, 360)

    def test_a_source_at_the_target_is_untouched(self):
        assert fit_output_size(1920, 1080, (1920, 1080)) == (1920, 1080)

    def test_a_bigger_source_is_downscaled_to_the_target(self):
        assert fit_output_size(3840, 2160, (1920, 1080)) == (1920, 1080)

    def test_unknown_dimensions_fall_back_to_the_target(self):
        assert fit_output_size(0, 0, (1920, 1080)) == (1920, 1080)

    def test_dimensions_stay_even_for_yuv420p(self):
        w, h = fit_output_size(641, 361, (1920, 1080))
        assert w % 2 == 0 and h % 2 == 0


class TestHorizontalDoesNotDecapitateOddSources:
    def test_a_16x9_source_matches(self):
        assert source_matches_aspect(1920, 1080, (1920, 1080))

    def test_a_vertical_source_does_not_match(self):
        assert not source_matches_aspect(1080, 1920, (1920, 1080))

    def test_a_4x3_source_does_not_match(self):
        assert not source_matches_aspect(640, 480, (1920, 1080))


class TestVerticalFillsTheScreen:
    """Encaixar o 16:9 inteiro num 9:16 deixava o vídeo numa tira de 31% da
    altura, com o rosto minúsculo e dois terços de tela em borrão."""

    def test_the_default_vertical_crops_to_fill_without_blur(self):
        f = vertical_fill_filter(1080, 1920)
        assert "crop=" in f and "scale=1080:1920" in f
        assert "gblur" not in f and "overlay" not in f

    def test_the_wide_shot_fallback_keeps_the_subject_large(self):
        """No plano aberto ainda há blur, mas o vídeo ocupa a maior parte da
        tela — não uma tira."""
        f = vertical_blur_filter(1080, 1920)
        assert "gblur" in f
        assert "scale=1080:1350" in f, "o primeiro plano encolheu demais"

    def test_captions_get_room_at_the_bottom(self):
        assert "(H-h)*0.34" in vertical_blur_filter(1080, 1920)


class TestWindowGrowsForwardFirst:
    """O modelo escolheu aquele início por um motivo. Puxar o começo para trás
    por uma fração arbitrária abria o corte no meio do assunto anterior."""

    def _transcript_words(self) -> list[Word]:
        rows = []
        t = 0.0
        for i in range(40):
            rows.append((t, t + 0.8, "palavra" if (i + 1) % 5 else "fim."))
            t += 1.0
        return _words(rows)

    def test_it_extends_the_end_before_touching_the_start(self):
        words = self._transcript_words()
        result = extend_window_to_minimum(
            10.0, 14.0, words, min_duration_s=12.0, pad_before_s=0.2, pad_after_s=0.2
        )
        assert result.start >= 9.0, "o começo foi puxado para trás sem necessidade"
        assert result.duration_s >= 12.0

    def test_it_lands_on_a_sentence_boundary(self):
        words = self._transcript_words()
        result = extend_window_to_minimum(
            10.0, 14.0, words, min_duration_s=12.0, pad_before_s=0.2, pad_after_s=0.2
        )
        assert result.ends_on_sentence

    def test_a_window_already_long_enough_is_left_alone(self):
        words = self._transcript_words()
        result = extend_window_to_minimum(
            10.0, 30.0, words, min_duration_s=12.0, pad_before_s=0.2, pad_after_s=0.2
        )
        assert result.duration_s < 24.0

    def test_it_gives_up_instead_of_inventing_context(self):
        """Sem pontuação à frente, entregar um corte mais curto é melhor que
        estender para sempre."""
        words = _words([(0.0, 1.0, "sem"), (1.0, 2.0, "pontuacao")])
        result = extend_window_to_minimum(
            0.0, 2.0, words, min_duration_s=60.0, pad_before_s=0.2, pad_after_s=0.2
        )
        assert result.duration_s < 10.0


class TestHallucinatedSpeechIsDropped:
    """O Whisper preenche silêncio com boilerplate. Num podcast isso virou 51
    segmentos de `www.opusdei.tp`, e um deles ancorou o começo de um corte."""

    def test_a_repeated_url_is_dropped(self):
        transcript = Transcript(
            segments=[
                Segment(id=i, start=float(i), end=i + 0.3, text="www.opusdei.tp")
                for i in range(5)
            ]
        )
        assert drop_hallucinated_segments(transcript) == 5
        assert all(not seg.text for seg in transcript.segments)

    def test_a_real_verbal_tic_survives_even_repeated_30_times(self):
        """"Tá ligado?" apareceu 30 vezes por ser bordão de quem falava.
        "Repetiu muito" não pode ser critério sozinho."""
        transcript = Transcript(
            segments=[
                Segment(id=i, start=float(i), end=i + 0.5, text="Tá ligado?")
                for i in range(30)
            ]
        )
        assert drop_hallucinated_segments(transcript) == 0
        assert all(seg.text for seg in transcript.segments)

    def test_a_repeated_song_chorus_survives(self):
        transcript = Transcript(
            segments=[
                Segment(id=i, start=float(i), end=i + 3.0, text="A humildade, a visão da sobrevivência")
                for i in range(9)
            ]
        )
        assert drop_hallucinated_segments(transcript) == 0

    def test_boilerplate_seen_only_once_is_kept(self):
        """Uma URL dita de verdade no meio da conversa não é alucinação."""
        transcript = Transcript(
            segments=[Segment(id=0, start=0.0, end=1.0, text="www.exemplo.com")]
        )
        assert drop_hallucinated_segments(transcript) == 0

    def test_the_pattern_list_does_not_catch_ordinary_speech(self):
        assert not looks_like_boilerplate("Eu fui pra São Paulo com 12 anos.")
        assert not looks_like_boilerplate("Tá ligado, mano?")
        assert looks_like_boilerplate("https://exemplo.com/x")


class TestYoutubeFormatsAreNotThrottledByAHardcodedClient:
    """Fixar `player_client` congelou o projeto num conjunto que hoje devolve
    só o formato 18 (360p progressivo): todo corte saiu de 360p, e o 9:16
    recortava 202x360 para ampliar 5x."""

    def test_no_player_client_override_by_default(self, monkeypatch):
        monkeypatch.delenv("CLIP_YTDLP_PLAYER_CLIENT", raising=False)
        assert "extractor_args" not in _base_ydl_opts()

    def test_the_escape_hatch_still_works(self, monkeypatch):
        monkeypatch.setenv("CLIP_YTDLP_PLAYER_CLIENT", "tv, web_safari")
        opts = _player_client_opts()
        assert opts["extractor_args"]["youtube"]["player_client"] == ["tv", "web_safari"]

    def test_an_empty_value_is_the_same_as_unset(self, monkeypatch):
        monkeypatch.setenv("CLIP_YTDLP_PLAYER_CLIENT", "  ")
        assert _player_client_opts() == {}


def test_download_height_default_is_full_hd():
    """O 9:16 recorta 9/16 da largura da fonte: com 720p sobram 405px para
    virar 1080 de largura. Full HD deixa esse recorte em 608px."""
    from clip_mvp.config import Settings

    os.environ.pop("CLIP_DOWNLOAD_HEIGHT", None)
    assert Settings().download_height >= 1080


class TestSpeakerDrivesTheCrop:
    """SPEC §14.6 pedia ligar o falante ativo ao rosto no quadro. A diarização
    era calculada, gravada em disco e então descartada: o crop seguia o rosto
    maior mesmo sabendo quem falava."""

    def _mesa(self) -> list[FaceCenter | None]:
        """Dois participantes fixos: um à esquerda (0.25), outro à direita (0.75).

        O escolhedor de base ficou no da direita o tempo todo (é o maior rosto).
        """
        from clip_mvp.face_track import DetectedFace

        esquerda = DetectedFace(cx=0.25, cy=0.4, area=0.03)
        direita = DetectedFace(cx=0.75, cy=0.4, area=0.06)
        return [
            FaceCenter(
                t=i / 12.0, cx=direita.cx, cy=0.4, area=direita.area,
                n_faces=2, faces=(esquerda, direita),
            )
            for i in range(24)
        ]

    def _quem_fala(self, t: float) -> str:
        return "A" if t < 1.0 else "B"

    def test_it_learns_where_each_speaker_sits(self):
        from clip_mvp.face_track import learn_speaker_positions

        # A base escolheu sempre a direita, então os dois rótulos aprendem 0.75.
        positions = learn_speaker_positions(self._mesa(), self._quem_fala)
        assert set(positions) == {"A", "B"}

    def test_a_speaker_with_too_few_samples_is_ignored(self):
        """Posição inventada a partir de duas amostras é pior que nenhuma."""
        from clip_mvp.face_track import learn_speaker_positions

        samples = self._mesa()[:3]
        assert learn_speaker_positions(samples, self._quem_fala) == {}

    def test_the_crop_follows_the_active_speaker(self):
        from clip_mvp.face_track import repick_by_speaker

        samples = self._mesa()
        out = repick_by_speaker(samples, self._quem_fala, {"A": 0.25, "B": 0.75})
        assert out[0].cx == 0.25, "durante a fala de A o crop deveria ir para a esquerda"
        assert out[-1].cx == 0.75, "durante a fala de B o crop deveria ir para a direita"

    def test_without_positions_nothing_changes(self):
        from clip_mvp.face_track import repick_by_speaker

        samples = self._mesa()
        assert repick_by_speaker(samples, self._quem_fala, {}) is samples

    def test_a_single_face_frame_is_left_alone(self):
        """Com um rosto só não há o que reescolher."""
        from clip_mvp.face_track import DetectedFace, repick_by_speaker

        only = DetectedFace(cx=0.5, cy=0.4, area=0.08)
        samples = [FaceCenter(t=0.0, cx=0.5, cy=0.4, n_faces=1, faces=(only,))]
        out = repick_by_speaker(samples, self._quem_fala, {"A": 0.9})
        assert out[0].cx == 0.5


class TestMouthActivityOnlyBreaksTies:
    """Sem diarização, o movimento de boca desempata entre dois rostos. É uma
    medida grosseira — muda também quando a pessoa mexe a cabeça — então não
    pode decidir sozinha."""

    def test_a_clearly_more_active_face_wins(self):
        from clip_mvp.face_track import DetectedFace, pick_by_mouth_activity

        quieto = DetectedFace(cx=0.25, cy=0.4, area=0.06, mouth_activity=0.01)
        falando = DetectedFace(cx=0.75, cy=0.4, area=0.03, mouth_activity=0.09)
        assert pick_by_mouth_activity([quieto, falando], quieto) is falando

    def test_a_narrow_difference_keeps_the_base_choice(self):
        from clip_mvp.face_track import DetectedFace, pick_by_mouth_activity

        a = DetectedFace(cx=0.25, cy=0.4, area=0.06, mouth_activity=0.050)
        b = DetectedFace(cx=0.75, cy=0.4, area=0.03, mouth_activity=0.055)
        assert pick_by_mouth_activity([a, b], a) is a

    def test_a_lone_face_is_never_second_guessed(self):
        from clip_mvp.face_track import DetectedFace, pick_by_mouth_activity

        only = DetectedFace(cx=0.5, cy=0.4, area=0.08, mouth_activity=0.0)
        assert pick_by_mouth_activity([only], only) is only

    def test_no_movement_anywhere_keeps_the_base_choice(self):
        from clip_mvp.face_track import DetectedFace, pick_by_mouth_activity

        a = DetectedFace(cx=0.25, cy=0.4, area=0.06)
        b = DetectedFace(cx=0.75, cy=0.4, area=0.03)
        assert pick_by_mouth_activity([a, b], a) is a


class TestOutputFrameRateIsCapped:
    """Um podcast em 60fps saía em 60fps por inércia. Cabeça falando não tem
    movimento que 30 não resolva, e 60 dobra os quadros que passam por crop,
    escala e encoder: medido nesta máquina, cair para 30 tirou um terço do
    tempo de render."""

    def test_a_60fps_source_is_halved(self):
        from clip_mvp.render import fps_filter

        assert fps_filter(60.0) == "fps=30"

    def test_a_source_already_at_the_target_is_untouched(self):
        from clip_mvp.render import fps_filter

        assert fps_filter(30.0) is None

    def test_a_slower_source_is_never_upsampled(self):
        """Forçar 30 numa fonte de 24 duplica quadros: gasta tempo para piorar
        a cadência."""
        from clip_mvp.render import fps_filter

        assert fps_filter(24.0) is None

    def test_the_cap_is_configurable(self, monkeypatch):
        from clip_mvp import render

        monkeypatch.setenv("CLIP_OUTPUT_FPS", "60")
        assert render.output_fps() == 60.0
        assert render.fps_filter(60.0) is None

    def test_a_broken_value_falls_back_to_the_default(self, monkeypatch):
        from clip_mvp import render

        monkeypatch.setenv("CLIP_OUTPUT_FPS", "abacaxi")
        assert render.output_fps() == render.DEFAULT_OUTPUT_FPS


class TestBlurredBackgroundIsCheap:
    """Borrar em 1080x1920 é desperdício: o gblur destrói justamente o detalhe
    que a resolução carrega."""

    def test_the_blur_runs_on_a_reduced_frame(self):
        from clip_mvp.render import vertical_blur_filter

        f = vertical_blur_filter(1080, 1920)
        assert "scale=180:320" in f, "o fundo não está sendo reduzido antes do blur"
        assert "gblur" in f

    def test_the_background_is_scaled_back_to_full_size(self):
        from clip_mvp.render import vertical_blur_filter

        assert "scale=1080:1920:flags=bilinear" in vertical_blur_filter(1080, 1920)


class TestPublishFolders:
    """Publicar exigia entrar em cinco pastas. A pasta por corte continua sendo
    a fonte da verdade; isto é uma segunda visão, para arrastar tudo de uma vez."""

    def _fake_clips(self, tmp_path):
        clips = []
        for score, slug in ((75, "primeiro"), (60, "segundo")):
            d = tmp_path / f"{score}_{slug}"
            d.mkdir()
            for name in ("vertical_facetrack.mp4", "vertical_center.mp4", "horizontal_16x9.mp4"):
                (d / name).write_bytes(b"video")
            clips.append({"slug": slug, "score": score, "out_dir": str(d)})
        return clips

    def test_verticals_and_horizontals_land_in_separate_folders(self, tmp_path):
        from clip_mvp.pipeline import HORIZONTAL_DIR, VERTICAL_DIR, organize_for_publishing

        made = organize_for_publishing(tmp_path, self._fake_clips(tmp_path))
        assert made == {VERTICAL_DIR: 4, HORIZONTAL_DIR: 2}
        assert len(list((tmp_path / VERTICAL_DIR).glob("*.mp4"))) == 4
        assert len(list((tmp_path / HORIZONTAL_DIR).glob("*.mp4"))) == 2

    def test_the_name_keeps_the_score_and_says_which_vertical(self, tmp_path):
        from clip_mvp.pipeline import VERTICAL_DIR, organize_for_publishing

        organize_for_publishing(tmp_path, self._fake_clips(tmp_path))
        names = {p.name for p in (tmp_path / VERTICAL_DIR).glob("*.mp4")}
        assert "75_primeiro_rosto.mp4" in names
        assert "75_primeiro_fixo.mp4" in names

    def test_it_does_not_duplicate_disk_space(self, tmp_path):
        """Hard link: o arquivo aparece nos dois lugares ocupando um espaço só."""
        from clip_mvp.pipeline import HORIZONTAL_DIR, organize_for_publishing

        clips = self._fake_clips(tmp_path)
        organize_for_publishing(tmp_path, clips)
        linked = tmp_path / HORIZONTAL_DIR / "75_primeiro.mp4"
        assert linked.stat().st_nlink >= 2

    def test_running_twice_does_not_pile_up(self, tmp_path):
        from clip_mvp.pipeline import VERTICAL_DIR, organize_for_publishing

        clips = self._fake_clips(tmp_path)
        organize_for_publishing(tmp_path, clips)
        organize_for_publishing(tmp_path, clips)
        assert len(list((tmp_path / VERTICAL_DIR).glob("*.mp4"))) == 4

    def test_a_missing_format_is_skipped_quietly(self, tmp_path):
        from clip_mvp.pipeline import HORIZONTAL_DIR, VERTICAL_DIR, organize_for_publishing

        d = tmp_path / "40_so-horizontal"
        d.mkdir()
        (d / "horizontal_16x9.mp4").write_bytes(b"video")
        made = organize_for_publishing(tmp_path, [{"slug": "so-horizontal", "score": 40, "out_dir": str(d)}])
        assert made == {VERTICAL_DIR: 0, HORIZONTAL_DIR: 1}


class TestDownloadPrefersFullHd:
    """Num podcast com 1080p disponível o `bestvideo` trouxe 720p, e o 9:16
    recorta 9/16 da largura: 720p vira um recorte de 405px esticado 2,7x."""

    def test_the_resolution_preference_is_explicit(self):
        from clip_mvp.download import _format_selection

        sel = _format_selection(1080)
        assert "res:1080" in sel["format_sort"]
        assert "height<=?1080" in sel["format"]

    def test_smaller_files_win_at_equal_resolution(self):
        """AV1 decodificou 1080p60 mais rápido que H.264 nesta máquina e o
        arquivo é 45% menor — não há motivo para preferir o maior."""
        from clip_mvp.download import _format_selection

        assert "+size" in _format_selection(1080)["format_sort"]

    def test_formats_without_a_declared_height_stay_in_the_running(self):
        """`height<=1080` sem `?` exclui arquivo direto e extractor genérico,
        derrubando o job no download."""
        from clip_mvp.download import _format_selection

        assert "<=?" in _format_selection(1080)["format"]
