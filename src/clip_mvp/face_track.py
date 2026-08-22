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

#: Duração da transição do crop quando o falante muda (SPEC §9: "crossfade
#: curto"). Curto o bastante para acompanhar a conversa, longo o bastante para
#: não parecer um corte seco de câmera.
SPEAKER_CROSSFADE_S = 0.4

#: Dois rostos a menos que isto de distância em X são a mesma pessoa entre
#: amostras (a detecção oscila alguns pixels de um frame para o outro).
SLOT_TOLERANCE_X = 0.12

#: Um "slot" de rosto que aparece em menos que esta fração das amostras é ruído
#: de detecção, não uma pessoa sentada na cena.
MIN_SLOT_PRESENCE = 0.08


@dataclass
class FaceCenter:
    t: float  # segundos, relativo ao início da janela
    cx: float  # centro X normalizado (0..1)
    cy: float  # centro Y normalizado (0..1)
    detected: bool = True


@dataclass
class FaceObservation:
    """Um rosto visto numa amostra (coordenadas normalizadas 0..1)."""

    cx: float
    cy: float
    area: float


def fill_gaps(
    raw_samples: list[FaceCenter | None],
    dt: float,
    *,
    hold_s: float = HOLD_LAST_CENTER_S,
    revert_s: float = REVERT_TO_FRAME_CENTER_S,
) -> list[FaceCenter]:
    """Preenche amostras sem rosto detectado (SPEC §9).

    A spec dá dois limites: até ``hold_s`` (0.5s) o crop segura o último centro
    conhecido; passado ``revert_s`` (2s) volta ao centro do frame. No meio, em
    vez de ficar parado e dar um salto seco no segundo 2, o centro caminha
    proporcionalmente até o meio do frame — um buraco de 1.5s não deveria
    terminar em corte de câmera.
    """
    filled: list[FaceCenter] = []
    last_known: FaceCenter | None = None
    gap_elapsed = 0.0
    span = max(1e-6, revert_s - hold_s)

    for i, sample in enumerate(raw_samples):
        t = i * dt
        if sample is not None:
            filled.append(FaceCenter(t=t, cx=sample.cx, cy=sample.cy, detected=True))
            last_known = sample
            gap_elapsed = 0.0
            continue

        gap_elapsed += dt
        if last_known is None or gap_elapsed > revert_s:
            filled.append(FaceCenter(t=t, cx=0.5, cy=0.5, detected=False))
            continue
        # Fração do caminho já percorrido de "segura o último centro" até
        # "recentraliza": 0 enquanto o buraco é curto, 1 no limite de revert_s.
        drift = min(1.0, max(0.0, (gap_elapsed - hold_s) / span))
        filled.append(
            FaceCenter(
                t=t,
                cx=last_known.cx + (0.5 - last_known.cx) * drift,
                cy=last_known.cy + (0.5 - last_known.cy) * drift,
                detected=False,
            )
        )

    return filled


def smooth_centers(
    centers: list[FaceCenter],
    *,
    alpha: float = EMA_ALPHA,
    max_step: float = MAX_STEP_NORM,
    step_allowance: list[float] | None = None,
) -> list[FaceCenter]:
    """EMA + limite de velocidade do crop (SPEC §9), operando em coordenadas
    normalizadas (0..1) — puro e testável sem vídeo/MediaPipe.

    ``step_allowance`` permite afrouxar o limite de velocidade em amostras
    específicas. É o que deixa o crossfade de troca de falante chegar ao rosto
    novo no tempo previsto: com o teto normal, atravessar o enquadramento
    levaria mais de um segundo e a fala já teria voltado para o outro.
    """
    smoothed: list[FaceCenter] = []
    prev_cx: float | None = None
    prev_cy: float | None = None

    for i, c in enumerate(centers):
        if prev_cx is None:
            cx, cy = c.cx, c.cy
        else:
            step = max_step
            if step_allowance is not None and i < len(step_allowance):
                step = max(step, step_allowance[i])
            ema_cx = alpha * c.cx + (1 - alpha) * prev_cx
            ema_cy = alpha * c.cy + (1 - alpha) * prev_cy
            dx = max(-step, min(step, ema_cx - prev_cx))
            dy = max(-step, min(step, ema_cy - prev_cy))
            cx, cy = prev_cx + dx, prev_cy + dy
        smoothed.append(FaceCenter(t=c.t, cx=cx, cy=cy, detected=c.detected))
        prev_cx, prev_cy = cx, cy

    return smoothed


# ---------------------------------------------------------------------------
# Speaker ↔ rosto (SPEC §9 "Falantes (2+ pessoas)", §14.6)
# ---------------------------------------------------------------------------


def face_slots(
    observations: list[list[FaceObservation]],
    *,
    tolerance: float = SLOT_TOLERANCE_X,
    min_presence: float = MIN_SLOT_PRESENCE,
) -> list[float]:
    """Posições X estáveis dos rostos da cena — uma por pessoa enquadrada.

    Num podcast as pessoas ficam sentadas: a posição horizontal de cada rosto é
    quase constante, então agrupar as detecções por X separa "o da esquerda" de
    "o da direita" sem reconhecimento facial nenhum. É a parte "posição" do
    mapeamento speaker→rosto que a SPEC §9 pede.
    """
    xs = sorted(obs.cx for frame in observations for obs in frame)
    if not xs:
        return []

    clusters: list[list[float]] = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][-1] <= tolerance:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    floor = max(1, int(len(observations) * min_presence))
    return [
        round(sum(cluster) / len(cluster), 4) for cluster in clusters if len(cluster) >= floor
    ]


def slot_series(
    observations: list[list[FaceObservation]],
    slots: list[float],
    *,
    tolerance: float = SLOT_TOLERANCE_X,
) -> list[list[FaceObservation | None]]:
    """Para cada slot, o rosto visto naquela posição em cada amostra."""
    series: list[list[FaceObservation | None]] = [[] for _ in slots]
    for frame in observations:
        for s, slot_x in enumerate(slots):
            near = [obs for obs in frame if abs(obs.cx - slot_x) <= tolerance]
            series[s].append(max(near, key=lambda o: o.area) if near else None)
    return series


def _slot_activity(series: list[list[FaceObservation | None]]) -> list[list[float]]:
    """Quanto cada rosto se move entre amostras.

    Quem está falando mexe a boca, a cabeça e o tronco; quem escuta fica quase
    imóvel. Sem landmarks de boca (a detecção só dá bounding box), a variação do
    centro e do tamanho da caixa é o sinal barato disponível — e é o que liga um
    label de falante ao rosto certo quando há dois na cena.
    """
    activity: list[list[float]] = []
    for track in series:
        row = [0.0] * len(track)
        prev: FaceObservation | None = None
        for i, obs in enumerate(track):
            if obs is not None and prev is not None:
                row[i] = (
                    abs(obs.cx - prev.cx)
                    + abs(obs.cy - prev.cy)
                    + abs(obs.area**0.5 - prev.area**0.5)
                )
            if obs is not None:
                prev = obs
        activity.append(row)
    return activity


def assign_speakers_to_slots(
    observations: list[list[FaceObservation]],
    speakers: list[str | None],
    slots: list[float],
    *,
    tolerance: float = SLOT_TOLERANCE_X,
) -> dict[str, int]:
    """Liga cada label de falante ao slot de rosto que se move quando ele fala.

    Mapeamento um-para-um e guloso: o par (falante, rosto) com o sinal mais
    forte fecha primeiro, e os dois saem da disputa. Assim dois falantes nunca
    caem no mesmo rosto — que é justamente o erro que faria o crop ficar parado
    numa pessoa durante a conversa inteira.
    """
    if not slots or not speakers:
        return {}

    series = slot_series(observations, slots, tolerance=tolerance)
    activity = _slot_activity(series)

    scores: dict[tuple[str, int], float] = {}
    for speaker in {s for s in speakers if s}:
        rows = [i for i, label in enumerate(speakers) if label == speaker and i < len(observations)]
        if not rows:
            continue
        for s in range(len(slots)):
            visible = [i for i in rows if i < len(series[s]) and series[s][i] is not None]
            if not visible:
                continue
            # Presença conta: um rosto que aparece em duas amostras pode ter
            # média de movimento alta por acidente.
            mean_activity = sum(activity[s][i] for i in visible) / len(visible)
            scores[(speaker, s)] = mean_activity * (len(visible) / len(rows))

    assignment: dict[str, int] = {}
    used_slots: set[int] = set()
    for (speaker, slot), _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        if speaker in assignment or slot in used_slots:
            continue
        assignment[speaker] = slot
        used_slots.add(slot)
    return assignment


def speaker_targets(
    observations: list[list[FaceObservation]],
    speakers: list[str | None],
    *,
    dt: float,
    tolerance: float = SLOT_TOLERANCE_X,
    crossfade_s: float = SPEAKER_CROSSFADE_S,
) -> tuple[list[FaceCenter | None], list[float]]:
    """Centro-alvo por amostra seguindo quem fala, com crossfade na troca.

    Retorna ``(centros, folga_de_velocidade)``: a folga é maior nas amostras do
    crossfade, para que :func:`smooth_centers` complete a transição dentro de
    ``crossfade_s`` em vez de arrastá-la pelo corte inteiro.

    Sem diarização (``speakers`` todo ``None``) cai no proxy de atividade: o
    rosto de maior área, exatamente o comportamento anterior.
    """
    slots = face_slots(observations, tolerance=tolerance)
    assignment = assign_speakers_to_slots(observations, speakers, slots, tolerance=tolerance)
    series = slot_series(observations, slots, tolerance=tolerance) if slots else []

    def largest(frame: list[FaceObservation]) -> FaceCenter | None:
        if not frame:
            return None
        best = max(frame, key=lambda o: o.area)
        return FaceCenter(t=0.0, cx=best.cx, cy=best.cy)

    targets: list[FaceCenter | None] = []
    active_slot: list[int | None] = []
    for i, frame in enumerate(observations):
        speaker = speakers[i] if i < len(speakers) else None
        slot = assignment.get(speaker) if speaker else None
        obs = series[slot][i] if slot is not None and i < len(series[slot]) else None
        if obs is not None:
            targets.append(FaceCenter(t=i * dt, cx=obs.cx, cy=obs.cy))
            active_slot.append(slot)
            continue
        fallback = largest(frame)
        if fallback is not None:
            fallback.t = i * dt
        targets.append(fallback)
        # Sem o rosto do falante no frame, quem manda é o proxy: não há troca
        # de falante a marcar.
        active_slot.append(None)

    allowance = _crossfade_allowance(
        targets, active_slot, dt=dt, crossfade_s=crossfade_s
    )
    return targets, allowance


def _crossfade_allowance(
    targets: list[FaceCenter | None],
    active_slot: list[int | None],
    *,
    dt: float,
    crossfade_s: float,
) -> list[float]:
    """Folga de velocidade nas amostras logo após uma troca de falante."""
    n_samples = max(1, int(round(crossfade_s / dt))) if dt > 0 else 1
    allowance = [0.0] * len(targets)
    previous: int | None = None
    previous_center: FaceCenter | None = None

    for i, slot in enumerate(active_slot):
        target = targets[i]
        if slot is None or target is None:
            if target is not None:
                previous_center = target
            continue
        if previous is not None and slot != previous and previous_center is not None:
            distance = max(
                abs(target.cx - previous_center.cx), abs(target.cy - previous_center.cy)
            )
            step = distance / n_samples
            for j in range(i, min(len(allowance), i + n_samples)):
                allowance[j] = max(allowance[j], step)
        previous = slot
        previous_center = target
    return allowance


def detect_face_observations(
    video_path: Path,
    window: Window,
    *,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
) -> list[list[FaceObservation]]:
    """Detecta **todos** os rostos a `sample_fps` (~8-12fps, SPEC §9) na janela.

    Guardar a cena inteira, e não só o rosto "principal", é o que permite ligar
    um falante ao rosto dele: com uma detecção por amostra não há como saber que
    existe outra pessoa em quadro para onde o crop deveria ir.
    """
    import cv2
    import mediapipe as mp

    cap = cv2.VideoCapture(str(video_path))
    dt = 1.0 / sample_fps
    duration = max(0.0, window.end - window.start)
    n_samples = max(1, int(round(duration * sample_fps)))

    frames: list[list[FaceObservation]] = []
    with mp.solutions.face_detection.FaceDetection(
        model_selection=0, min_detection_confidence=0.5
    ) as detector:
        for i in range(n_samples):
            cap.set(cv2.CAP_PROP_POS_MSEC, (window.start + i * dt) * 1000.0)
            ok, frame = cap.read()
            if not ok:
                frames.append([])
                continue
            result = detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            observations: list[FaceObservation] = []
            for det in result.detections or []:
                bbox = det.location_data.relative_bounding_box
                observations.append(
                    FaceObservation(
                        cx=bbox.xmin + bbox.width / 2,
                        cy=bbox.ymin + bbox.height / 2,
                        area=max(0.0, bbox.width * bbox.height),
                    )
                )
            frames.append(observations)

    cap.release()
    return frames


def compute_smoothed_centers(
    video_path: Path,
    window: Window,
    *,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    speakers: list[str | None] | None = None,
) -> list[FaceCenter]:
    """Centros suavizados do crop, seguindo o falante ativo quando há timeline.

    ``speakers`` é a timeline de diarização amostrada no mesmo ritmo da detecção
    (ver :func:`clip_mvp.diarization.speaker_timeline`). Sem ela, o alvo é o
    rosto de maior área — o ``activity_proxy`` documentado na SPEC §14.6.
    """
    dt = 1.0 / sample_fps
    observations = detect_face_observations(video_path, window, sample_fps=sample_fps)
    targets, allowance = speaker_targets(
        observations, speakers or [None] * len(observations), dt=dt
    )
    filled = fill_gaps(targets, dt=dt)
    return smooth_centers(filled, step_allowance=allowance)


def render_vertical_facetrack(
    video_path: Path,
    window: Window,
    out_path: Path,
    *,
    ass_path: Path | None = None,
    size: tuple[int, int] = VERTICAL_SIZE,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    speakers: list[str | None] | None = None,
    centers: list[FaceCenter] | None = None,
) -> Path:
    """Render 9:16 com crop dinâmico seguindo o rosto (MediaPipe), SPEC §9.

    ``speakers`` (timeline de diarização, uma entrada por amostra) faz o crop
    acompanhar quem está falando, com crossfade curto na troca (SPEC §14.6).

    `centers` pode ser injetado (ex.: testes) para pular a detecção real.
    """
    import cv2

    out_path = Path(out_path)
    centers = centers or compute_smoothed_centers(
        video_path, window, sample_fps=sample_fps, speakers=speakers
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
