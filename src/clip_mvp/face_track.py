"""Face tracking (MediaPipe) — só para `vertical_facetrack` (SPEC §9).

`vertical_center` e `horizontal_16x9` NUNCA usam tracking (SPEC §9, §12 passo 6).
Roda apenas no(s) trecho(s) `selected`, nunca no vídeo inteiro inteiro.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .audio import AUDIO_ENCODE_ARGS, LOUDNORM_I, LOUDNORM_LRA, LOUDNORM_TP
from .models import Window
from .render import (
    WIDE_SHOT_CROP_ASPECT,
    VERTICAL_SIZE,
    VIDEO_ENCODE_ARGS,
    _seek_args,
    _subtitles_filter,
    fps_filter,
    vertical_blur_filter,
    wide_shot_filter,
)
from .utils import run_ffmpeg

LOUDNORM_FILTER = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"

DEFAULT_SAMPLE_FPS = 12.0
HOLD_LAST_CENTER_S = 0.5  # SPEC §9: sem rosto <0.5s -> segura último centro
REVERT_TO_FRAME_CENTER_S = 2.0  # SPEC §9: >2s -> centro do frame
EMA_ALPHA = 0.18
MAX_STEP_NORM = 0.045  # crop mais estável em podcast (troca de falante sem salto)

#: Diferença média entre dois quadros (0..1) que já é troca de câmera, não
#: movimento de quem fala. Medido em cinza reduzido a 64x36.
SCENE_CUT_DIFF = 0.14

#: Largura para a qual o quadro é reduzido antes de ir para o MediaPipe. O
#: detector trabalha em coordenadas normalizadas, então a precisão do centro não
#: depende de resolução — e 1920px de entrada só gasta CPU.
DETECT_WIDTH = 640


@dataclass
class FaceCenter:
    t: float  # segundos, relativo ao início da janela
    cx: float  # centro X normalizado (0..1)
    cy: float  # centro Y normalizado (0..1)
    detected: bool = True
    area: float = 0.0
    n_faces: int = 0
    spread_x: float = 0.0
    #: O quadro inteiro mudou aqui (troca de câmera), não só o rosto se mexeu.
    scene_cut: bool = False
    #: Todos os rostos vistos neste quadro. Guardados para a passada que liga
    #: falante a rosto poder reescolher sem decodificar o vídeo de novo.
    faces: tuple["DetectedFace", ...] = ()


@dataclass(frozen=True)
class DetectedFace:
    cx: float
    cy: float
    area: float
    #: Quanto a região da boca mudou desde o quadro anterior (0..1). É o proxy
    #: barato de "esta pessoa está falando" quando não há diarização.
    mouth_activity: float = 0.0


SWITCH_RATIO = 1.22  # só troca se o novo for claramente mais forte


def fill_gaps(
    raw_samples: list[FaceCenter | None],
    dt: float,
    *,
    hold_s: float = HOLD_LAST_CENTER_S,
    revert_s: float = REVERT_TO_FRAME_CENTER_S,
) -> list[FaceCenter]:
    """Preenche amostras sem rosto detectado: segura o último centro conhecido
    (buracos curtos) e, se o buraco ultrapassar `revert_s`, volta ao centro do
    frame (0.5, 0.5) — SPEC §9. `hold_s` é aceito para documentar a regra mas
    a semântica efetiva é "segura até `revert_s`, depois recentraliza"."""
    filled: list[FaceCenter] = []
    last_known: FaceCenter | None = None
    gap_elapsed = 0.0

    for i, sample in enumerate(raw_samples):
        t = i * dt
        if sample is not None:
            filled.append(
                FaceCenter(
                    t=t,
                    cx=sample.cx,
                    cy=sample.cy,
                    detected=True,
                    area=sample.area,
                    n_faces=sample.n_faces,
                    spread_x=sample.spread_x,
                    scene_cut=sample.scene_cut,
                )
            )
            last_known = sample
            gap_elapsed = 0.0
            continue

        gap_elapsed += dt
        if last_known is not None and gap_elapsed <= revert_s:
            filled.append(
                FaceCenter(
                    t=t,
                    cx=last_known.cx,
                    cy=last_known.cy,
                    detected=False,
                    area=last_known.area,
                    n_faces=last_known.n_faces,
                    spread_x=last_known.spread_x,
                )
            )
        else:
            filled.append(FaceCenter(t=t, cx=0.5, cy=0.5, detected=False, n_faces=0))

    return filled


def smooth_centers(
    centers: list[FaceCenter],
    *,
    alpha: float = EMA_ALPHA,
    max_step: float = MAX_STEP_NORM,
) -> list[FaceCenter]:
    """EMA + limite de velocidade do crop (SPEC §9), operando em coordenadas
    normalizadas (0..1) — puro e testável sem vídeo/MediaPipe.

    Numa **troca de câmera** o suavizador é reiniciado: o limite de velocidade
    existe para o crop não tremer atrás de quem fala, e aplicá-lo por cima de um
    corte de plano faz o enquadramento atravessar o quadro novo devagar,
    mostrando a parede por um segundo antes de achar o rosto. Corte é
    descontinuidade: o crop tem de saltar junto.
    """
    smoothed: list[FaceCenter] = []
    prev_cx: float | None = None
    prev_cy: float | None = None

    for c in centers:
        if prev_cx is None or c.scene_cut:
            cx, cy = c.cx, c.cy
        else:
            ema_cx = alpha * c.cx + (1 - alpha) * prev_cx
            ema_cy = alpha * c.cy + (1 - alpha) * prev_cy
            dx = max(-max_step, min(max_step, ema_cx - prev_cx))
            dy = max(-max_step, min(max_step, ema_cy - prev_cy))
            cx, cy = prev_cx + dx, prev_cy + dy
        smoothed.append(
            FaceCenter(
                t=c.t,
                cx=cx,
                cy=cy,
                detected=c.detected,
                area=c.area,
                n_faces=c.n_faces,
                spread_x=c.spread_x,
                scene_cut=c.scene_cut,
            )
        )
        prev_cx, prev_cy = cx, cy

    return smoothed


def resample_centers(
    centers: list[FaceCenter], *, sample_dt: float, out_fps: float
) -> list[FaceCenter]:
    """Interpola os centros medidos até a taxa de quadros da saída.

    A detecção roda a ~12 Hz, mas o vídeo sai a 30 ou 60 fps. Emitindo um
    comando de crop por amostra, cada posição segura por 3 a 5 quadros e o
    movimento vira degrau — visível como tranco lateral. Interpolando para a
    taxa real, o mesmo deslocamento total é distribuído por todos os quadros.

    Uma troca de câmera não é interpolada: ali o salto é o comportamento certo.
    """
    if len(centers) < 2 or out_fps <= 0 or sample_dt <= 0:
        return list(centers)

    total = centers[-1].t
    n_out = max(1, int(round(total * out_fps)) + 1)
    out: list[FaceCenter] = []
    for i in range(n_out):
        t = i / out_fps
        pos = min(t / sample_dt, len(centers) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(centers) - 1)
        frac = pos - lo
        a, b = centers[lo], centers[hi]
        if b.scene_cut:
            # Segura o enquadramento antigo até o instante do corte e então
            # entrega o novo inteiro, em vez de deslizar entre os dois.
            chosen = b if frac >= 0.5 else a
            out.append(FaceCenter(t=t, cx=chosen.cx, cy=chosen.cy, detected=chosen.detected,
                                  area=chosen.area, n_faces=chosen.n_faces,
                                  spread_x=chosen.spread_x, scene_cut=b.scene_cut and frac >= 0.5))
            continue
        out.append(
            FaceCenter(
                t=t,
                cx=a.cx + (b.cx - a.cx) * frac,
                cy=a.cy + (b.cy - a.cy) * frac,
                detected=a.detected or b.detected,
                area=a.area + (b.area - a.area) * frac,
                n_faces=a.n_faces,
                spread_x=a.spread_x,
            )
        )
    return out


def featured_face_score(face: DetectedFace, last_cx: float | None) -> float:
    """Pontua o rosto mais “de capa” numa mesa: maior, mais no centro, estável."""
    centrality = 1.0 - min(1.0, abs(face.cx - 0.5) * 1.6)
    talking_head = 1.0 - min(1.0, abs(face.cy - 0.38) * 1.3)
    continuity = 0.0 if last_cx is None else 1.0 - min(1.0, abs(face.cx - last_cx) * 2.4)
    return face.area * 6.5 + centrality * 0.55 + talking_head * 0.2 + continuity * 0.35


def pick_featured_face(
    faces: list[DetectedFace],
    last_cx: float | None,
    *,
    switch_ratio: float = SWITCH_RATIO,
) -> DetectedFace | None:
    """Escolhe o participante em destaque e evita pular entre três cadeiras."""
    if not faces:
        return None
    if last_cx is None:
        return max(faces, key=lambda face: featured_face_score(face, None))
    current = min(faces, key=lambda face: abs(face.cx - last_cx))
    # Desafiante pelo tamanho real do rosto — continuidade não pode esconder quem
    # está claramente mais em destaque na mesa.
    challenger = max(faces, key=lambda face: face.area)
    if challenger is current:
        return current
    if challenger.area >= max(current.area, 1e-6) * switch_ratio:
        return challenger
    return current


def face_spread_x(faces: list[DetectedFace]) -> float:
    if len(faces) < 2:
        return 0.0
    xs = [face.cx for face in faces]
    return max(xs) - min(xs)


#: Quantas amostras um falante precisa ter para a posição dele ser confiável.
MIN_SPEAKER_OBSERVATIONS = 6

#: Diferença mínima de movimento de boca para trocar de rosto por atividade.
MOUTH_ACTIVITY_MARGIN = 1.6


def learn_speaker_positions(
    samples: list[FaceCenter | None],
    speaker_at: Callable[[float], str | None],
) -> dict[str, float]:
    """Aprende em que ponto da tela cada falante costuma estar.

    A diarização diz *quem* fala e *quando*, nunca *onde* — a posição na mesa
    tem de sair do vídeo. Acumulamos, para cada rótulo de falante, o x dos
    rostos escolhidos enquanto ele estava falando, e ficamos com a mediana.

    O escolhedor de base (maior área + continuidade) erra às vezes, então a
    mediana herda algum ruído; ela é robusta a erro ocasional, não a um
    escolhedor sistematicamente errado. Falante com poucas amostras é
    descartado em vez de virar uma posição inventada.
    """
    from statistics import median

    by_speaker: dict[str, list[float]] = {}
    for sample in samples:
        if sample is None:
            continue
        speaker = speaker_at(sample.t)
        if speaker is None:
            continue
        by_speaker.setdefault(speaker, []).append(sample.cx)
    return {
        speaker: median(xs)
        for speaker, xs in by_speaker.items()
        if len(xs) >= MIN_SPEAKER_OBSERVATIONS
    }


def repick_by_speaker(
    samples: list[FaceCenter | None],
    speaker_at: Callable[[float], str | None],
    positions: dict[str, float],
) -> list[FaceCenter | None]:
    """Reescolhe, em cada amostra, o rosto mais perto de quem está falando.

    É a metade que faltava da SPEC §14.6: a diarização já era calculada e
    gravada, mas o resultado era descartado — o crop seguia o rosto maior, não
    quem falava. Com dois ou três participantes isso deixa o Short enquadrando
    a pessoa errada durante respostas inteiras.
    """
    if not positions:
        return samples
    out: list[FaceCenter | None] = []
    for sample in samples:
        if sample is None or len(sample.faces) < 2:
            out.append(sample)
            continue
        target = positions.get(speaker_at(sample.t) or "")
        if target is None:
            out.append(sample)
            continue
        best = min(sample.faces, key=lambda face: abs(face.cx - target))
        out.append(
            FaceCenter(
                t=sample.t,
                cx=best.cx,
                cy=best.cy,
                detected=True,
                area=best.area,
                n_faces=sample.n_faces,
                spread_x=sample.spread_x,
                scene_cut=sample.scene_cut,
                faces=sample.faces,
            )
        )
    return out


def pick_by_mouth_activity(
    faces: list[DetectedFace], fallback: DetectedFace, *, margin: float = MOUTH_ACTIVITY_MARGIN
) -> DetectedFace:
    """Sem diarização, prefere o rosto cuja boca se mexeu mais.

    Só entra em cena com dois ou mais rostos e quando um deles está
    claramente mais ativo que o resto (``margin``). Num plano de uma pessoa só
    — o caso comum — não muda nada, e é de propósito: a medida é grosseira e
    não deve desempatar o que não precisa de desempate.
    """
    if len(faces) < 2:
        return fallback
    ranked = sorted(faces, key=lambda face: face.mouth_activity, reverse=True)
    top, second = ranked[0], ranked[1]
    if top.mouth_activity <= 0:
        return fallback
    if top.mouth_activity >= max(second.mouth_activity, 1e-6) * margin:
        return top
    return fallback


def _mouth_activity(gray, prev_gray, bbox, width: int, height: int) -> float:
    """Quanto a metade de baixo do rosto mudou desde o quadro anterior.

    É um proxy grosseiro de fala — muda também quando a pessoa mexe a cabeça —
    e por isso só é usado para desempatar entre dois rostos, nunca sozinho.
    """
    if prev_gray is None or gray is None:
        return 0.0
    import cv2
    import numpy as np

    x0 = int(max(0, (bbox.xmin + bbox.width * 0.25) * width))
    x1 = int(min(width, (bbox.xmin + bbox.width * 0.75) * width))
    y0 = int(max(0, (bbox.ymin + bbox.height * 0.55) * height))
    y1 = int(min(height, (bbox.ymin + bbox.height * 1.05) * height))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return 0.0
    a = gray[y0:y1, x0:x1]
    b = prev_gray[y0:y1, x0:x1]
    if a.shape != b.shape or a.size == 0:
        return 0.0
    return float(np.mean(cv2.absdiff(a, b))) / 255.0


def detect_face_centers(
    video_path: Path,
    window: Window,
    *,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    preferred_x: float | None = None,
) -> list[FaceCenter | None]:
    """Detecta o centro do rosto principal a `sample_fps` (~8-12fps, SPEC §9)
    dentro da janela. `preferred_x` (0..1) pode ser usado para preferir o
    rosto mais próximo de um speaker ativo (SPEC §14.6 / diarization.py).

    Decodifica **sequencialmente** e só entrega ao MediaPipe um quadro a cada
    ``stride``. Um `cap.set(POS_MSEC)` por amostra parece equivalente e não é:
    cada busca obriga o decoder a voltar ao keyframe anterior e decodificar até
    o alvo, o que em H.264 custa mais do que decodificar tudo uma vez só.

    Também mede a diferença entre quadros consecutivos para marcar troca de
    câmera — é o que permite o crop saltar junto em vez de atravessar o quadro.
    """
    import cv2
    import mediapipe as mp

    cap = cv2.VideoCapture(str(video_path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    dt = 1.0 / sample_fps
    duration = max(0.0, window.end - window.start)
    n_samples = max(1, int(round(duration * sample_fps)))
    stride = max(1, int(round(src_fps / sample_fps)))

    cap.set(cv2.CAP_PROP_POS_MSEC, window.start * 1000.0)

    samples: list[FaceCenter | None] = []
    prev_tiny = None
    prev_gray = None
    with mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.35
    ) as detector:
        for i in range(n_samples):
            frame = None
            for _ in range(stride if i else 1):
                ok, candidate = cap.read()
                if not ok:
                    frame = None
                    break
                frame = candidate
            if frame is None:
                samples.append(None)
                continue

            height, width = frame.shape[:2]
            if width > DETECT_WIDTH:
                scale = DETECT_WIDTH / width
                small = cv2.resize(frame, (DETECT_WIDTH, max(2, int(height * scale))))
            else:
                small = frame

            small_gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            tiny = cv2.resize(small_gray, (64, 36))
            is_cut = False
            if prev_tiny is not None:
                diff = cv2.absdiff(tiny, prev_tiny).mean() / 255.0
                is_cut = diff >= SCENE_CUT_DIFF
            prev_tiny = tiny

            result = detector.process(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
            if not result.detections:
                samples.append(None)
                continue

            faces = []
            sh, sw = small.shape[:2]
            for det in result.detections:
                bbox = det.location_data.relative_bounding_box
                faces.append(
                    DetectedFace(
                        cx=bbox.xmin + bbox.width / 2,
                        cy=bbox.ymin + bbox.height / 2,
                        area=max(0.0, bbox.width * bbox.height),
                        mouth_activity=_mouth_activity(small_gray, prev_gray, bbox, sw, sh),
                    )
                )
            # Depois de um corte, a continuidade com o plano anterior não vale:
            # quem estava à esquerda pode não estar mais em cena.
            last_x = (
                None
                if is_cut
                else next((sample.cx for sample in reversed(samples) if sample is not None), preferred_x)
            )
            if preferred_x is not None and not is_cut:
                best = min(faces, key=lambda face: abs(face.cx - preferred_x))
            else:
                best = pick_featured_face(faces, last_x)
                if best is not None:
                    best = pick_by_mouth_activity(faces, best)
            if best is None:
                samples.append(None)
                continue
            samples.append(
                FaceCenter(
                    t=i * dt,
                    cx=best.cx,
                    cy=best.cy,
                    detected=True,
                    area=best.area,
                    n_faces=len(faces),
                    spread_x=face_spread_x(faces),
                    scene_cut=is_cut,
                    faces=tuple(faces),
                )
            )
            prev_gray = small_gray

    cap.release()
    return samples


def compute_smoothed_centers(
    video_path: Path,
    window: Window,
    *,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    preferred_x: float | None = None,
    speaker_at: Callable[[float], str | None] | None = None,
) -> list[FaceCenter]:
    """Centros prontos para virar crop: detecta, liga falante a rosto, preenche
    buracos e suaviza.

    ``speaker_at`` recebe o tempo **relativo ao início da janela** e devolve o
    rótulo de quem está falando (SPEC §14.6). Com ele, o crop acompanha quem
    fala em vez do rosto maior.
    """
    raw = detect_face_centers(video_path, window, sample_fps=sample_fps, preferred_x=preferred_x)
    if speaker_at is not None:
        raw = repick_by_speaker(raw, speaker_at, learn_speaker_positions(raw, speaker_at))
    filled = fill_gaps(raw, dt=1.0 / sample_fps)
    return smooth_centers(filled)


def _even(value: int) -> int:
    return value if value % 2 == 0 else max(2, value - 1)


def _crop_box(
    center: FaceCenter,
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    *,
    aspect: float | None = None,
) -> tuple[int, int, int, int]:
    """Janela de recorte centrada no rosto.

    ``aspect`` (largura/altura) permite recortar numa proporção mais larga que
    a saída — é o que o plano aberto usa para acompanhar a conversa sem
    decepar quem está na ponta da mesa.
    """
    if aspect is not None and aspect > 0:
        crop_h = _even(src_h)
        crop_w = _even(min(src_w, int(round(crop_h * aspect))))
    else:
        scale = max(out_w / max(src_w, 1), out_h / max(src_h, 1))
        crop_w = _even(min(src_w, int(round(out_w / scale))))
        crop_h = _even(min(src_h, int(round(out_h / scale))))
    cx_px = center.cx * src_w
    face_y = min(0.62, max(0.22, center.cy))
    cy_px = face_y * src_h - crop_h * 0.08
    x0 = int(round(cx_px - crop_w / 2))
    y0 = int(round(cy_px - crop_h / 2))
    x0 = max(0, min(src_w - crop_w, x0))
    y0 = max(0, min(src_h - crop_h, y0))
    return crop_w, crop_h, x0, y0


def _write_crop_sendcmd(
    path: Path,
    centers: list[FaceCenter],
    *,
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    sample_dt: float,
    aspect: float | None = None,
) -> tuple[int, int]:
    """Gera sendcmd do crop 9:16 seguindo o rosto, para o FFmpeg aplicar em GPU/CPU nativo."""
    if not centers:
        centers = [FaceCenter(t=0.0, cx=0.5, cy=0.38)]
    crop_w, crop_h, _, _ = _crop_box(centers[0], src_w, src_h, out_w, out_h, aspect=aspect)
    lines: list[str] = []
    last_x: int | None = None
    for i, center in enumerate(centers):
        _, _, x0, _y0 = _crop_box(center, src_w, src_h, out_w, out_h, aspect=aspect)
        # Só x muda: a altura do recorte é sempre a altura da fonte, então y é
        # constante e vai estático no próprio filtro. Emitir `crop y` por quadro
        # dobrava o arquivo de comandos — e o custo do sendcmd escala com o
        # número de comandos, não com o tempo (medido: 3000 comandos custam
        # 21s de CPU num corte de 50s, 1000 custam 6s).
        if x0 == last_x and i not in (0, len(centers) - 1):
            continue
        lines.append(f"{max(0.0, i * sample_dt):.3f} crop x {x0};")
        last_x = x0
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return crop_w, crop_h


def is_wide_table_shot(centers: list[FaceCenter]) -> bool:
    """Mesa com vários falantes, ou plano aberto: melhor o quadro inteiro + blur."""
    if not centers:
        return True
    faces = sorted(c.n_faces for c in centers)
    spreads = sorted(c.spread_x for c in centers)
    areas = sorted(c.area for c in centers)
    mid_faces = faces[len(faces) // 2]
    mid_spread = spreads[len(spreads) // 2]
    mid_area = areas[len(areas) // 2]
    # Sem rosto ou rosto pequeno = câmera aberta na mesa. Close de um só é área grande.
    no_face = mid_faces <= 0
    far_away = 0 < mid_area < 0.05
    many_people = mid_faces >= 3 or (mid_faces >= 2 and mid_spread >= 0.34)
    return no_face or far_away or many_people


def render_vertical_facetrack(
    video_path: Path,
    window: Window,
    out_path: Path,
    *,
    ass_path: Path | None = None,
    size: tuple[int, int] = VERTICAL_SIZE,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    preferred_x: float | None = None,
    speaker_at: Callable[[float], str | None] | None = None,
    centers: list[FaceCenter] | None = None,
) -> Path:
    """Render 9:16 com crop dinâmico seguindo o rosto (MediaPipe), SPEC §9.

    Só o vertical usa tracking. O 16:9 nunca passa por aqui: é corte limpo.
    `centers` pode ser injetado (ex.: testes) para pular a detecção real.
    """
    import cv2

    out_path = Path(out_path)
    centers = centers or compute_smoothed_centers(
        video_path,
        window,
        sample_fps=sample_fps,
        preferred_x=preferred_x,
        speaker_at=speaker_at,
    )

    cap = cv2.VideoCapture(str(video_path))
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
    src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    cap.release()

    out_w, out_h = size
    sample_dt = 1.0 / sample_fps if sample_fps > 0 else 0.1
    sub = _subtitles_filter(ass_path)
    encode = [
        "-af",
        LOUDNORM_FILTER,
        *VIDEO_ENCODE_ARGS,
        *AUDIO_ENCODE_ARGS,
        "-shortest",
        str(out_path),
    ]

    wide = is_wide_table_shot(centers)
    # Plano aberto recorta mais largo (4:5) para não decepar quem está na ponta
    # da mesa — mas continua seguindo a conversa em vez de virar estático.
    aspect = WIDE_SHOT_CROP_ASPECT if wide else None

    # Um comando de crop por quadro, não por amostra de detecção: é a diferença
    # entre o enquadramento deslizar e ele andar aos trancos de 3 a 5 quadros.
    # "Por quadro" é por quadro **de saída**: gerar 60 comandos por segundo para
    # renderizar 30 quadros dobra o arquivo de comandos e o trabalho do sendcmd
    # sem mudar um pixel.
    from .render import output_fps

    render_fps = min(src_fps, output_fps()) if src_fps > 0 else output_fps()
    command_fps = max(sample_fps, min(render_fps, 60.0))
    frame_centers = resample_centers(centers, sample_dt=sample_dt, out_fps=command_fps)

    cmd_path = out_path.with_name(out_path.stem + ".crop.txt")
    crop_w, crop_h = _write_crop_sendcmd(
        cmd_path,
        frame_centers,
        src_w=src_w,
        src_h=src_h,
        out_w=out_w,
        out_h=out_h,
        sample_dt=1.0 / command_fps,
        aspect=aspect,
    )
    # O sendcmd é indexado por tempo, então funciona igual depois do descarte
    # de quadros — e o crop passa a rodar na metade dos quadros.
    drop = fps_filter(src_fps)
    crop_chain = (
        f"sendcmd=f='{cmd_path.as_posix()}',"
        f"crop={crop_w}:{crop_h}:x={max(0, (src_w - crop_w) // 2)}:y=0"
    )
    try:
        if wide:
            filter_args = [
                "-filter_complex",
                wide_shot_filter(out_w, out_h, crop_chain=crop_chain, extra=sub, prefix=drop),
            ]
        else:
            filter_args = [
                "-vf",
                ",".join(
                    ([drop] if drop else [])
                    + [crop_chain, f"scale={out_w}:{out_h}:flags=lanczos"]
                    + ([sub] if sub else [])
                ),
            ]
        run_ffmpeg(_seek_args(video_path, window) + filter_args + encode)
    finally:
        cmd_path.unlink(missing_ok=True)
    return out_path
