"""Face tracking do `vertical_facetrack` (SPEC 9).

Roda **apenas** nos trechos selecionados, a ~10 fps, com suavização EMA e
limite de velocidade do crop. `vertical_center` e `horizontal_16x9` não usam
tracking. Sem MediaPipe instalado, o método volta como `center_fallback`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .diarize import SpeakerTurn, speaker_at

SAMPLE_FPS = 10.0
EMA_ALPHA = 0.22
MAX_SPEED_PX_PER_S = 260.0
HOLD_LAST_S = 0.5
"""Sem rosto por menos de 0,5s: segura o último centro."""
RECENTER_AFTER_S = 2.0
"""Sem rosto por mais de 2s: volta ao centro do frame."""


@dataclass
class TrackResult:
    method: str
    keyframes: list[tuple[float, float]]
    """(t relativo ao início do clip, centro x em px na fonte)."""
    faces_detected: int = 0
    speakers: int = 0

    @property
    def available(self) -> bool:
        return bool(self.keyframes)


def track(
    source: Path,
    start: float,
    end: float,
    frame_width: int,
    turns: list[SpeakerTurn] | None = None,
) -> TrackResult:
    turns = turns or []
    try:
        import cv2  # type: ignore
        import mediapipe as mp  # type: ignore
    except Exception:
        return TrackResult(method="center_fallback", keyframes=[], speakers=len(turns))

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        return TrackResult(method="center_fallback", keyframes=[], speakers=0)

    detector = mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.5
    )
    step = 1.0 / SAMPLE_FPS
    samples: list[tuple[float, float | None, list[float]]] = []
    t = start
    try:
        while t < end:
            capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = capture.read()
            if not ok:
                break
            height, width = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = detector.process(rgb)
            centers: list[float] = []
            if result and result.detections:
                for detection in result.detections:
                    box = detection.location_data.relative_bounding_box
                    centers.append((box.xmin + box.width / 2.0) * width)
            samples.append((t - start, _pick_center(centers, turns, t), centers))
            t += step
    finally:
        capture.release()
        detector.close()

    if not samples:
        return TrackResult(method="center_fallback", keyframes=[], speakers=0)

    keyframes = _smooth(samples, frame_width)
    detected = sum(1 for _, center, _ in samples if center is not None)
    speakers = len({turn.speaker for turn in turns})
    method = "mediapipe+diarization" if speakers > 1 else "mediapipe"
    if detected == 0:
        return TrackResult(method="center_fallback", keyframes=[], speakers=speakers)
    return TrackResult(
        method=method, keyframes=keyframes, faces_detected=detected, speakers=speakers
    )


def _pick_center(
    centers: list[float], turns: list[SpeakerTurn], t: float
) -> float | None:
    """Escolhe o rosto: quem está falando (diarização) ou o rosto principal."""
    if not centers:
        return None
    if len(centers) == 1 or not turns:
        return centers[0] if len(centers) == 1 else sorted(centers)[len(centers) // 2]
    speaker = speaker_at(turns, t)
    if speaker is None:
        return sorted(centers)[len(centers) // 2]
    ordered_speakers = sorted({turn.speaker for turn in turns})
    ordered_centers = sorted(centers)
    try:
        index = ordered_speakers.index(speaker)
    except ValueError:
        return ordered_centers[len(ordered_centers) // 2]
    return ordered_centers[min(index, len(ordered_centers) - 1)]


def _smooth(
    samples: list[tuple[float, float | None, list[float]]], frame_width: int
) -> list[tuple[float, float]]:
    """EMA + limite de velocidade + regra de perda de rosto."""
    center_default = frame_width / 2.0
    smoothed: list[tuple[float, float]] = []
    current = None
    last_seen_t: float | None = None
    last_center = center_default
    prev_t = samples[0][0]

    for t, raw_center, _ in samples:
        if raw_center is not None:
            target = raw_center
            last_seen_t = t
            last_center = raw_center
        else:
            gap = t - last_seen_t if last_seen_t is not None else RECENTER_AFTER_S + 1
            if gap <= HOLD_LAST_S:
                target = last_center
            elif gap >= RECENTER_AFTER_S:
                target = center_default
            else:
                # transição suave entre segurar e recentralizar
                ratio = (gap - HOLD_LAST_S) / (RECENTER_AFTER_S - HOLD_LAST_S)
                target = last_center + (center_default - last_center) * ratio

        if current is None:
            current = target
        else:
            current += (target - current) * EMA_ALPHA
            max_delta = MAX_SPEED_PX_PER_S * max(1e-3, t - prev_t)
            delta = current - smoothed[-1][1]
            if abs(delta) > max_delta:
                current = smoothed[-1][1] + max_delta * (1 if delta > 0 else -1)
        smoothed.append((round(t, 3), round(current, 1)))
        prev_t = t
    return smoothed
