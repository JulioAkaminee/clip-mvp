"""Render dos formatos de saída: 9:16 center, 16:9, (+ 9:16 facetrack em face_track.py).

SPEC §1, §5, §7, §14.2, §14.5.
"""

from __future__ import annotations

import os
from pathlib import Path

from .audio import AUDIO_ENCODE_ARGS, LOUDNORM_I, LOUDNORM_LRA, LOUDNORM_TP
from .models import Window
from .utils import run_ffmpeg

VERTICAL_SIZE = (1080, 1920)
HORIZONTAL_SIZE = (1920, 1080)

#: Encode de vídeo comum a todos os exports.
#:
#: `-g 120` põe um keyframe a cada ~2s (a 60fps): as plataformas cortam e
#: re-empacotam nos keyframes, e um GOP longo faz o player pular no scrub.
#: `high`/`4.1` é o que TikTok, Reels e Shorts aceitam sem transcodificar de
#: volta para algo pior.
VIDEO_ENCODE_ARGS: list[str] = [
    "-c:v", "libx264",
    "-profile:v", "high",
    "-level", "4.1",
    "-pix_fmt", "yuv420p",
    "-preset", "veryfast",
    "-crf", "20",
    "-g", "120",
    "-movflags", "+faststart",
]

LOUDNORM_FILTER = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"


def _seek_args(video_path: Path, window: Window) -> list[str]:
    """Seek híbrido: -ss grosseiro antes do -i (rápido) + -ss fino depois
    (preciso), evitando decodificar o vídeo inteiro até o ponto de corte."""
    pre_seek = max(0.0, window.start - 2.0)
    offset = window.start - pre_seek
    duration = max(0.05, window.end - window.start)
    return [
        "-ss",
        f"{pre_seek:.3f}",
        "-i",
        str(video_path),
        "-ss",
        f"{offset:.3f}",
        "-t",
        f"{duration:.3f}",
    ]


_SUBTITLES_FILTER_AVAILABLE: bool | None = None


def ffmpeg_has_subtitles_filter() -> bool:
    """Este ffmpeg do Homebrew foi compilado sem libass: o filtro `subtitles` não existe."""
    global _SUBTITLES_FILTER_AVAILABLE
    if _SUBTITLES_FILTER_AVAILABLE is None:
        import subprocess

        probe = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
        )
        blob = f"{probe.stdout}\n{probe.stderr}"
        _SUBTITLES_FILTER_AVAILABLE = "subtitles" in blob
    return _SUBTITLES_FILTER_AVAILABLE


def _subtitles_filter(ass_path: Path | None) -> str | None:
    if ass_path is None or not ffmpeg_has_subtitles_filter():
        return None
    escaped = str(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return f"subtitles=filename='{escaped}'"


#: Taxa de quadros dos exports.
#:
#: Um podcast vem em 60fps e sai em 60fps por inércia, mas TikTok, Reels e
#: Shorts entregam 30fps na maioria dos aparelhos, e cabeça falando não tem
#: movimento que 30 não resolva. Renderizar em 60 dobra o número de quadros
#: que passam por crop, escala e encoder: medido nesta máquina, cair para 30
#: tira **um terço** do tempo de render, com o mesmo CRF e a mesma nitidez por
#: quadro. Suba para 60 em `CLIP_OUTPUT_FPS` se o corte tiver movimento rápido.
DEFAULT_OUTPUT_FPS = 30.0


def output_fps() -> float:
    raw = (os.getenv("CLIP_OUTPUT_FPS") or "").strip()
    try:
        value = float(raw) if raw else DEFAULT_OUTPUT_FPS
    except ValueError:
        return DEFAULT_OUTPUT_FPS
    return value if value > 0 else DEFAULT_OUTPUT_FPS


def probe_video_info(video_path: Path) -> tuple[int, int, float]:
    """(largura, altura, fps) da fonte. Zeros se o ffprobe não souber dizer."""
    import json
    import subprocess

    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate",
                "-of", "json", str(video_path),
            ],
            capture_output=True, text=True, check=True,
        )
        stream = (json.loads(out.stdout).get("streams") or [{}])[0]
        rate = str(stream.get("r_frame_rate") or "0/1")
        num, _, den = rate.partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 0.0
        return int(stream.get("width") or 0), int(stream.get("height") or 0), fps
    except Exception:  # noqa: BLE001 - sem metadados, cai no tamanho nominal
        return 0, 0, 0.0


def probe_video_shape(video_path: Path) -> tuple[int, int]:
    """(largura, altura) da fonte. (0, 0) se o ffprobe não souber dizer."""
    w, h, _ = probe_video_info(video_path)
    return w, h


def fps_filter(source_fps: float, target_fps: float | None = None) -> str | None:
    """Filtro `fps` a aplicar, ou ``None`` quando não há o que reduzir.

    Só entra quando a fonte é mais rápida que o alvo: forçar 30 numa fonte de
    24 duplicaria quadros, gastando tempo para piorar a cadência.
    """
    target = target_fps if target_fps is not None else output_fps()
    if source_fps <= 0 or target <= 0 or source_fps <= target + 0.01:
        return None
    return f"fps={target:g}"


def fit_output_size(src_w: int, src_h: int, target: tuple[int, int]) -> tuple[int, int]:
    """Tamanho de saída que não amplia a fonte além do que ela tem.

    Ampliar 640x360 para 1920x1080 não cria detalhe: gera um arquivo três vezes
    maior, borrado do mesmo jeito, que demora três vezes mais para renderizar e
    subir. Quando a fonte é menor que o alvo, a saída acompanha a fonte,
    preservando a proporção do alvo e mantendo as dimensões pares (exigência do
    yuv420p).
    """
    tw, th = target
    if src_w <= 0 or src_h <= 0:
        return target
    scale = min(1.0, src_h / th, src_w / tw) if (src_w < tw or src_h < th) else 1.0
    # Só encolhe quando a fonte realmente não tem pixels para o alvo; a decisão
    # é pela menor dimensão relativa, para nunca ampliar em nenhum eixo.
    limit = min(src_w / tw, src_h / th)
    scale = min(1.0, limit) if limit < 1.0 else 1.0
    if scale >= 1.0:
        return target
    w = max(2, int(round(tw * scale)) // 2 * 2)
    h = max(2, int(round(th * scale)) // 2 * 2)
    return w, h


def source_matches_aspect(src_w: int, src_h: int, target: tuple[int, int], *, tol: float = 0.02) -> bool:
    """A fonte já está na proporção do alvo (dentro de uma tolerância)?"""
    if src_w <= 0 or src_h <= 0:
        return True
    tw, th = target
    return abs((src_w / src_h) - (tw / th)) <= tol * (tw / th)


#: Divisor de resolução do fundo desfocado.
#:
#: Borrar em 1080x1920 é desperdício: um gblur pesado destrói justamente o
#: detalhe que a resolução carrega. Reduzir 6x, borrar com sigma proporcional e
#: ampliar de volta dá um resultado visualmente igual por ~1/36 do trabalho.
BLUR_DOWNSCALE = 6


def _blurred_background(width: int, height: int) -> str:
    """Cadeia que produz o fundo desfocado de uma tela `width x height`."""
    small_w = max(2, width // BLUR_DOWNSCALE // 2 * 2)
    small_h = max(2, height // BLUR_DOWNSCALE // 2 * 2)
    return (
        f"scale={small_w}:{small_h}:force_original_aspect_ratio=increase,"
        f"crop={small_w}:{small_h},gblur=sigma=4,eq=brightness=-0.06,"
        f"scale={width}:{height}:flags=bilinear"
    )


def blur_pad_filter(
    width: int,
    height: int,
    *,
    extra: str | None = None,
    fg_scale: float = 1.0,
    fg_y: str | None = None,
) -> str:
    """Encaixa o quadro inteiro em ``width x height`` com o próprio vídeo
    desfocado atrás, em vez de barra preta.

    ``fg_scale`` amplia o vídeo em primeiro plano além do que caberia (o que
    recorta um pouco das laterais mas enche mais a tela) e ``fg_y`` define a
    posição vertical do overlay — no 9:16 vale subir a imagem para a legenda
    ocupar a faixa de baixo sem tapar ninguém.
    """
    w, h = width, height
    tail = f",{extra}" if extra else ""
    fg_w = max(2, int(round(w * max(0.5, fg_scale))) // 2 * 2)
    y_expr = fg_y if fg_y is not None else "(H-h)/2"
    return (
        f"split=2[bg][fg];"
        f"[bg]{_blurred_background(w, h)}[bg2];"
        f"[fg]scale={fg_w}:-2[fg2];"
        f"[bg2][fg2]overlay=(W-w)/2:{y_expr}{tail}"
    )


#: Proporção do recorte usado no 9:16 de plano aberto. 4:5 é mais alto que
#: 16:9 (o assunto fica grande) e mais largo que 9:16 (ninguém na mesa é
#: decepado). O que sobra vira faixa desfocada fina, não metade da tela.
WIDE_SHOT_CROP_ASPECT = 4 / 5


def vertical_fill_filter(width: int, height: int, *, extra: str | None = None) -> str:
    """9:16 preenchendo a tela: recorte central, sem faixa e sem blur.

    É o enquadramento padrão de quem fala num podcast — rosto grande, imagem
    nítida de ponta a ponta. Encaixar o 16:9 inteiro num 9:16 deixava o vídeo
    numa tira de 31% da altura, com o rosto minúsculo e dois terços de tela
    desperdiçados em borrão.
    """
    tail = f",{extra}" if extra else ""
    return f"crop='min(iw,ih*{width}/{height})':ih,scale={width}:{height}:flags=lanczos{tail}"


def wide_shot_filter(
    width: int,
    height: int,
    *,
    crop_chain: str,
    extra: str | None = None,
    prefix: str | None = None,
) -> str:
    """Plano aberto 9:16 com o recorte 4:5 **acompanhando a conversa**.

    ``crop_chain`` é a cadeia de filtros que posiciona o recorte (normalmente
    ``sendcmd`` + ``crop``, vindos do face tracking). Antes, um plano aberto
    descartava o tracking inteiro e virava enquadramento fixo; agora o crop é
    mais largo — ninguém na ponta da mesa é decepado — mas ainda segue quem
    fala.
    """
    w, h = width, height
    tail = f",{extra}" if extra else ""
    fg_h = max(2, int(round(w / WIDE_SHOT_CROP_ASPECT)) // 2 * 2)
    # `prefix` (tipicamente o corte de taxa de quadros) vai **antes do split**:
    # posto só no ramo do primeiro plano, o `overlay` continuava seguindo a
    # taxa do fundo e o arquivo saía em 60fps mesmo com fps=30 na cadeia.
    head = f"{prefix}," if prefix else ""
    return (
        f"{head}split=2[bg][fg];"
        f"[bg]{_blurred_background(w, h)}[bg2];"
        f"[fg]{crop_chain},scale={w}:{fg_h}:flags=lanczos[fg2];"
        f"[bg2][fg2]overlay=(W-w)/2:(H-h)*0.34{tail}"
    )


def vertical_blur_filter(width: int, height: int, *, extra: str | None = None) -> str:
    """9:16 de plano aberto: recorte 4:5 grande, com fundo desfocado só nas
    sobras, empurrado para cima para a legenda ocupar a faixa de baixo.

    Usado quando um recorte fechado perderia gente em cena (mesa com vários
    participantes, câmera aberta). Continua mostrando bem mais do quadro que o
    recorte 9:16, sem reduzir o assunto a uma tira.
    """
    w, h = width, height
    tail = f",{extra}" if extra else ""
    fg_h = max(2, int(round(w / WIDE_SHOT_CROP_ASPECT)) // 2 * 2)
    return (
        f"split=2[bg][fg];"
        f"[bg]{_blurred_background(w, h)}[bg2];"
        f"[fg]crop='min(iw,ih*{WIDE_SHOT_CROP_ASPECT:.4f})':ih,"
        f"scale={w}:{fg_h}:flags=lanczos[fg2];"
        f"[bg2][fg2]overlay=(W-w)/2:(H-h)*0.34{tail}"
    )


def render_vertical_center(
    video_path: Path,
    window: Window,
    out_path: Path,
    *,
    ass_path: Path | None = None,
    size: tuple[int, int] = VERTICAL_SIZE,
) -> Path:
    """Render 9:16 com recorte central fixo — SEM face tracking (SPEC §9).

    Preenche a tela inteira: é o enquadramento que dá o maior rosto possível
    sem tracking. A versão com fundo desfocado ficou reservada para plano
    aberto, onde recortar perderia gente em cena.
    """
    w, h = size
    extra = _subtitles_filter(ass_path)
    _, _, src_fps = probe_video_info(video_path)
    # Reduzir a taxa antes de escalar: cada quadro descartado é um crop, uma
    # escala e um quadro de encoder que não acontecem.
    chain = [f for f in (fps_filter(src_fps), vertical_fill_filter(w, h, extra=extra)) if f]

    args = _seek_args(video_path, window) + [
        "-vf",
        ",".join(chain),
        "-af",
        LOUDNORM_FILTER,
        *VIDEO_ENCODE_ARGS,
        *AUDIO_ENCODE_ARGS,
        str(out_path),
    ]
    run_ffmpeg(args)
    return Path(out_path)


def render_horizontal_16x9(
    video_path: Path,
    window: Window,
    out_path: Path,
    *,
    ass_path: Path | None = None,
    size: tuple[int, int] = HORIZONTAL_SIZE,
) -> Path:
    """Render 16:9 trim limpo. Face tracking é exclusivo do 9:16 (SPEC §9).

    Duas correções de enquadramento em relação a um `scale+crop` cego:

    * a saída nunca é maior que a fonte — ampliar 360p para 1080p só produz
      arquivo grande e borrado;
    * fonte que não é 16:9 (4:3, vertical, gravação de tela) ganha o quadro
      inteiro com o fundo desfocado, em vez de ter as laterais decepadas.
    """
    src_w, src_h, src_fps = probe_video_info(video_path)
    w, h = fit_output_size(src_w, src_h, size)
    sub = _subtitles_filter(ass_path)
    drop = fps_filter(src_fps)

    if source_matches_aspect(src_w, src_h, size):
        vf_parts = [
            f"scale={w}:{h}:force_original_aspect_ratio=increase",
            f"crop={w}:{h}",
        ]
        if sub:
            vf_parts.append(sub)
        if drop:
            vf_parts.insert(0, drop)
        filter_args = ["-vf", ",".join(vf_parts)]
    else:
        chain = blur_pad_filter(w, h, extra=sub)
        filter_args = ["-filter_complex", f"{drop},{chain}" if drop else chain]

    args = _seek_args(video_path, window) + [
        *filter_args,
        "-af",
        LOUDNORM_FILTER,
        *VIDEO_ENCODE_ARGS,
        *AUDIO_ENCODE_ARGS,
        str(out_path),
    ]
    run_ffmpeg(args)
    return Path(out_path)


def cut_raw(video_path: Path, window: Window, out_path: Path) -> Path:
    """Corte simples por timestamp, sem crop/legendas (usado por testes de
    fronteira e como utilitário de baixo nível, SPEC §12 passo 1)."""
    args = _seek_args(video_path, window) + [
        *VIDEO_ENCODE_ARGS,
        *AUDIO_ENCODE_ARGS,
        str(out_path),
    ]
    run_ffmpeg(args)
    return Path(out_path)
