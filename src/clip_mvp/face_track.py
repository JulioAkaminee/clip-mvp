"""Face tracking (MediaPipe) — só para `vertical_facetrack` (SPEC §9).

`vertical_center` e `horizontal_16x9` NUNCA usam tracking (SPEC §9, §12 passo 6).
Roda apenas no(s) trecho(s) `selected`, nunca no vídeo inteiro inteiro.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .audio import LOUDNORM_I, LOUDNORM_LRA, LOUDNORM_TP
from .models import Window
from .render import VERTICAL_SIZE, _seek_args, _subtitles_filter
from .utils import run_ffmpeg

LOUDNORM_FILTER = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"

DEFAULT_SAMPLE_FPS = 10.0
HOLD_LAST_CENTER_S = 0.5  # SPEC §9: sem rosto <0.5s -> segura último centro
REVERT_TO_FRAME_CENTER_S = 2.0  # SPEC §9: >2s -> centro do frame
EMA_ALPHA = 0.25
MAX_STEP_NORM = 0.06  # limite de velocidade do crop (fração da largura por amostra)


@dataclass
class FaceCenter:
    t: float  # segundos, relativo ao início da janela
    cx: float  # centro X normalizado (0..1)
    cy: float  # centro Y normalizado (0..1)
    detected: bool = True


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
            filled.append(FaceCenter(t=t, cx=sample.cx, cy=sample.cy, detected=True))
            last_known = sample
            gap_elapsed = 0.0
            continue

        gap_elapsed += dt
        if last_known is not None and gap_elapsed <= revert_s:
            filled.append(FaceCenter(t=t, cx=last_known.cx, cy=last_known.cy, detected=False))
        else:
            filled.append(FaceCenter(t=t, cx=0.5, cy=0.5, detected=False))

    return filled


def smooth_centers(
    centers: list[FaceCenter],
    *,
    alpha: float = EMA_ALPHA,
    max_step: float = MAX_STEP_NORM,
) -> list[FaceCenter]:
    """EMA + limite de velocidade do crop (SPEC §9), operando em coordenadas
    normalizadas (0..1) — puro e testável sem vídeo/MediaPipe."""
    smoothed: list[FaceCenter] = []
    prev_cx: float | None = None
    prev_cy: float | None = None

    for c in centers:
        if prev_cx is None:
            cx, cy = c.cx, c.cy
        else:
            ema_cx = alpha * c.cx + (1 - alpha) * prev_cx
            ema_cy = alpha * c.cy + (1 - alpha) * prev_cy
            dx = max(-max_step, min(max_step, ema_cx - prev_cx))
            dy = max(-max_step, min(max_step, ema_cy - prev_cy))
            cx, cy = prev_cx + dx, prev_cy + dy
        smoothed.append(FaceCenter(t=c.t, cx=cx, cy=cy, detected=c.detected))
        prev_cx, prev_cy = cx, cy

    return smoothed


def detect_face_centers(
    video_path: Path,
    window: Window,
    *,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    preferred_x: float | None = None,
) -> list[FaceCenter | None]:
    """Detecta o centro do rosto principal a `sample_fps` (~8-12fps, SPEC §9)
    dentro da janela. `preferred_x` (0..1) pode ser usado para preferir o
    rosto mais próximo de um speaker ativo (SPEC §14.6 / diarization.py)."""
    import cv2
    import mediapipe as mp

    cap = cv2.VideoCapture(str(video_path))
    dt = 1.0 / sample_fps
    duration = max(0.0, window.end - window.start)
    n_samples = max(1, int(round(duration * sample_fps)))

    samples: list[FaceCenter | None] = []
    with mp.solutions.face_detection.FaceDetection(
        model_selection=0, min_detection_confidence=0.5
    ) as detector:
        for i in range(n_samples):
            t_rel = i * dt
            cap.set(cv2.CAP_PROP_POS_MSEC, (window.start + t_rel) * 1000.0)
            ok, frame = cap.read()
            if not ok:
                samples.append(None)
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = detector.process(rgb)
            if not result.detections:
                samples.append(None)
                continue

            def face_center(det):
                bbox = det.location_data.relative_bounding_box
                return bbox.xmin + bbox.width / 2, bbox.ymin + bbox.height / 2, bbox.width * bbox.height

            if preferred_x is not None:
                best = min(
                    result.detections,
                    key=lambda d: abs(face_center(d)[0] - preferred_x),
                )
            else:
                best = max(result.detections, key=lambda d: face_center(d)[2])

            cx, cy, _ = face_center(best)
            samples.append(FaceCenter(t=t_rel, cx=cx, cy=cy, detected=True))

    cap.release()
    return samples


def compute_smoothed_centers(
    video_path: Path,
    window: Window,
    *,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    preferred_x: float | None = None,
) -> list[FaceCenter]:
    raw = detect_face_centers(video_path, window, sample_fps=sample_fps, preferred_x=preferred_x)
    filled = fill_gaps(raw, dt=1.0 / sample_fps)
    return smooth_centers(filled)


def render_vertical_facetrack(
    video_path: Path,
    window: Window,
    out_path: Path,
    *,
    ass_path: Path | None = None,
    size: tuple[int, int] = VERTICAL_SIZE,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    preferred_x: float | None = None,
    centers: list[FaceCenter] | None = None,
) -> Path:
    """Render 9:16 com crop dinâmico seguindo o rosto (MediaPipe), SPEC §9.

    `centers` pode ser injetado (ex.: testes) para pular a detecção real.
    """
    import cv2

    out_path = Path(out_path)
    centers = centers or compute_smoothed_centers(
        video_path, window, sample_fps=sample_fps, preferred_x=preferred_x
    )

    cap = cv2.VideoCapture(str(video_path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.set(cv2.CAP_PROP_POS_MSEC, window.start * 1000.0)

    crop_h = src_h
    crop_w = min(src_w, int(round(crop_h * 9 / 16)))
    out_w, out_h = size

    tmp_silent = out_path.with_name(out_path.stem + ".silent.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(tmp_silent), fourcc, src_fps, (out_w, out_h))

    duration = max(0.0, window.end - window.start)
    n_frames = max(1, int(round(duration * src_fps)))
    sample_dt = 1.0 / sample_fps if sample_fps > 0 else 1.0 / src_fps

    def center_at(t: float) -> FaceCenter:
        if not centers:
            return FaceCenter(t=t, cx=0.5, cy=0.5)
        idx = min(int(t / sample_dt), len(centers) - 1)
        return centers[max(0, idx)]

    try:
        for i in range(n_frames):
            ok, frame = cap.read()
            if not ok:
                break
            t = i / src_fps
            c = center_at(t)
            cx_px = c.cx * src_w
            x0 = int(round(cx_px - crop_w / 2))
            x0 = max(0, min(src_w - crop_w, x0))
            cropped = frame[0:crop_h, x0 : x0 + crop_w]
            resized = cv2.resize(cropped, (out_w, out_h))
            writer.write(resized)
    finally:
        writer.release()
        cap.release()

    tmp_audio = out_path.with_name(out_path.stem + ".audio.m4a")
    try:
        audio_args = _seek_args(video_path, window) + [
            "-vn",
            "-af",
            LOUDNORM_FILTER,
            "-c:a",
            "aac",
            str(tmp_audio),
        ]
        run_ffmpeg(audio_args)

        mux_args = ["-i", str(tmp_silent), "-i", str(tmp_audio)]
        sub = _subtitles_filter(ass_path)
        if sub:
            mux_args += ["-vf", sub, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
        else:
            mux_args += ["-c:v", "copy"]
        mux_args += ["-c:a", "aac", "-shortest", "-movflags", "+faststart", str(out_path)]
        run_ffmpeg(mux_args)
    finally:
        tmp_silent.unlink(missing_ok=True)
        tmp_audio.unlink(missing_ok=True)

    return out_path
