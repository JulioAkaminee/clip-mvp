"""Modelo de progresso, ETA e emissão de eventos estruturados.

Todo estágio do pipeline reporta progresso por aqui. O objetivo é que a CLI, a
API HTTP e a UI web consumam exatamente o mesmo payload:

    {stage, percent, eta_seconds, message, clips_done, clips_total, ...}

O ETA é calculado com um modelo de custo por estágio (calibrado para o hardware
alvo: MacBook Pro i5 16GB) que se re-calibra durante o job conforme os estágios
reais terminam.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Estágios
# ---------------------------------------------------------------------------

#: Ordem canônica dos estágios do pipeline.
STAGE_ORDER: tuple[str, ...] = (
    "download",
    "transcribe",
    "candidates",
    "score",
    "select",
    "captions",
    "render",
    "meta",
)

#: Rótulos PT-BR exibidos na CLI e na UI.
STAGE_LABELS: dict[str, str] = {
    "queued": "Na fila",
    "download": "Baixando vídeo",
    "transcribe": "Transcrevendo áudio (PT-BR)",
    "candidates": "Procurando momentos com contexto fechado",
    "score": "Avaliando potencial de viralização",
    "select": "Selecionando os melhores cortes",
    "captions": "Gerando legendas",
    "render": "Renderizando cortes",
    "meta": "Escrevendo títulos, hashtags e captions",
    "done": "Concluído",
    "error": "Erro",
    "canceled": "Cancelado",
}

#: Estados em que um job diz estar trabalhando.
ACTIVE_STATUSES = frozenset({"queued", "running"})

#: Um job vivo reescreve ``status.json`` a cada batimento (2s por padrão),
#: inclusive quando roda na CLI em outro processo. Passado este tempo sem
#: nenhuma escrita e sem processo conhecido, o job morreu: `kill`, reboot, ou o
#: laptop fechou no meio do render. Sem isso a UI (e o `clip status`) herdavam um
#: "rodando" eterno, com ETA congelado e nenhum caminho para sair do lugar.
STALE_JOB_AFTER_S = 45.0


def is_snapshot_fresh(
    snapshot: dict[str, Any] | None, *, now: float, after_s: float = STALE_JOB_AFTER_S
) -> bool:
    """O job escreveu progresso recentemente, ou seja, está vivo em algum lugar.

    É o que distingue "morreu" de "está rodando em outro processo": um job da CLI
    é invisível para o servidor, mas o frescor do ``status.json`` não é.
    """
    if not snapshot or snapshot.get("status") not in ACTIVE_STATUSES:
        return False
    updated_at = snapshot.get("updated_at")
    if not isinstance(updated_at, (int, float)):
        return False
    return (now - updated_at) <= after_s


def mark_stale_if_dead(
    snapshot: dict[str, Any], *, running: bool, now: float, after_s: float = STALE_JOB_AFTER_S
) -> dict[str, Any]:
    """Converte um job abandonado em estado de erro retriável.

    O objetivo é honestidade: "interrompido" com um botão de retomar é
    informação; um spinner que gira para sempre não é.
    """
    snapshot.setdefault("stale", False)
    if running or snapshot.get("status") not in ACTIVE_STATUSES:
        return snapshot
    if is_snapshot_fresh(snapshot, now=now, after_s=after_s):
        return snapshot

    updated_at = snapshot.get("updated_at")
    if not isinstance(updated_at, (int, float)):
        return snapshot

    stage = snapshot.get("stage") or "queued"
    idle_min = max(1, int((now - updated_at) // 60))
    snapshot["status"] = "error"
    snapshot["stale"] = True
    snapshot["eta_seconds"] = None
    snapshot["eta_text"] = "interrompido"
    snapshot["message"] = f"Job interrompido em {snapshot.get('stage_label', stage)}"
    snapshot["error"] = {
        "stage": stage,
        "stage_label": snapshot.get("stage_label", stage),
        "type": "JobInterrupted",
        "message": (
            f"O job parou de responder há ~{idle_min} min (processo encerrado, "
            "reinício do servidor ou máquina suspensa)."
        ),
        "retriable": True,
        "hint": (
            "Rode `clip resume <job_id>` (ou clique em Tentar de novo na UI): o cache "
            "em work/ é reaproveitado, sem re-baixar nem re-transcrever."
        ),
    }
    return snapshot


#: Peso relativo de cada estágio no percentual global (soma 100).
#:
#: Os pesos são re-normalizados em runtime quando estágios são pulados (por
#: exemplo, ``resume`` reaproveita download e transcrição do cache).
STAGE_WEIGHTS: dict[str, float] = {
    "download": 14.0,
    "transcribe": 26.0,
    "candidates": 6.0,
    "score": 16.0,
    "select": 1.0,
    "captions": 4.0,
    "render": 28.0,
    "meta": 5.0,
}


@dataclass(frozen=True)
class StageCostModel:
    """Previsão de duração de um estágio, em segundos.

    ``base`` é o custo fixo, ``per_source_minute`` escala com a duração do vídeo
    de origem e ``per_unit`` escala com o número de unidades de trabalho do
    estágio (chunks de STT, candidatos avaliados, clipes renderizados...).
    """

    base: float
    per_source_minute: float = 0.0
    per_unit: float = 0.0

    def predict(self, source_minutes: float, units: float) -> float:
        return (
            self.base
            + self.per_source_minute * max(0.0, source_minutes)
            + self.per_unit * max(0.0, units)
        )


#: Priors medidos em um MacBook Pro 2020 i5 16GB com rede doméstica.
#: São apenas o ponto de partida: :class:`ProgressReporter` re-calibra tudo com
#: o tempo real de cada estágio concluído.
STAGE_COSTS: dict[str, StageCostModel] = {
    # yt-dlp 720p: dominado pela banda, escala com a duração do vídeo.
    "download": StageCostModel(base=6.0, per_source_minute=2.6),
    # STT remoto em chunks de ~10 min, com paralelismo limitado.
    "transcribe": StageCostModel(base=8.0, per_source_minute=3.4),
    # 1 chamada de LLM de texto sobre a transcrição inteira.
    "candidates": StageCostModel(base=12.0, per_source_minute=0.35),
    # vision: extração de frames + 1 chamada por candidato.
    "score": StageCostModel(base=6.0, per_unit=7.5),
    "select": StageCostModel(base=0.5),
    "captions": StageCostModel(base=1.0, per_unit=0.6),
    # ffmpeg local: face tracking domina (MediaPipe a ~8-12fps).
    "render": StageCostModel(base=4.0, per_unit=52.0),
    # 1 chamada de LLM por clipe (em paralelo limitado).
    "meta": StageCostModel(base=4.0, per_unit=3.0),
}


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage)


# ---------------------------------------------------------------------------
# Formatação PT-BR do ETA
# ---------------------------------------------------------------------------


#: Texto de ETA para job que já terminou: nesses estados não há tempo restante,
#: e "finalizando…" num job concluído ou "calculando tempo restante…" num job que
#: falhou é simplesmente mentira (SPEC: rótulos honestos em PT-BR).
TERMINAL_ETA_TEXT: dict[str, str] = {
    "done": "concluído",
    "error": "interrompido",
    "canceled": "cancelado",
}


def format_eta(eta_seconds: float | None, status: str | None = None) -> str:
    """Formata o ETA em PT-BR: ``~3 min restantes`` / ``~45 s restantes``.

    ``status`` terminal manda no texto: um job concluído não está "finalizando"
    e um job que falhou não está "calculando tempo restante".
    """
    if status in TERMINAL_ETA_TEXT:
        return TERMINAL_ETA_TEXT[status]
    if eta_seconds is None:
        return "calculando tempo restante…"
    if eta_seconds <= 0:
        return "finalizando…"
    if eta_seconds < 60:
        return f"~{int(round(eta_seconds))} s restantes"
    minutes = eta_seconds / 60.0
    if minutes < 10:
        # abaixo de 10 min meio minuto ainda é informação útil
        rounded = round(minutes * 2) / 2
        if rounded < 1:
            return f"~{int(round(eta_seconds))} s restantes"
        text = f"{rounded:.1f}".rstrip("0").rstrip(".")
        return f"~{text} min restantes"
    return f"~{int(round(minutes))} min restantes"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, secs = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


@dataclass
class ClipProgress:
    """Estado de um clipe individual durante os estágios por clipe."""

    slug: str
    score: float | None = None
    status: str = "pending"  # pending | running | done | skipped | error
    formats: dict[str, str] = field(default_factory=dict)
    message: str = ""
    vertical_skipped: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StageState:
    name: str
    label: str
    weight: float
    status: str = "pending"  # pending | running | done | skipped | error
    percent: float = 0.0
    started_at: float | None = None
    ended_at: float | None = None
    message: str = ""
    units_total: float = 0.0
    units_done: float = 0.0
    predicted_seconds: float | None = None
    #: Mesmo relógio do reporter. Sem isso o tempo decorrido de um estágio em
    #: andamento mistura o relógio injetado (``started_at``) com o relógio real,
    #: e todo o cálculo de ETA e de calibração fica intestável.
    clock: Callable[[], float] = field(default=time.time, repr=False, compare=False)

    @property
    def elapsed(self) -> float | None:
        if self.started_at is None:
            return None
        return (self.ended_at or self.clock()) - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "weight": self.weight,
            "status": self.status,
            "percent": round(self.percent, 2),
            "message": self.message,
            "units_total": self.units_total,
            "units_done": self.units_done,
            "elapsed_seconds": (
                round(self.elapsed, 2) if self.elapsed is not None else None
            ),
            "predicted_seconds": (
                round(self.predicted_seconds, 2)
                if self.predicted_seconds is not None
                else None
            ),
        }


def _job_payload_keys() -> tuple[str, ...]:
    """Chaves obrigatórias do payload — usado pelos testes de contrato."""
    return (
        "schema_version",
        "job_id",
        "status",
        "stage",
        "stage_label",
        "stage_percent",
        "stage_elapsed_seconds",
        "percent",
        "eta_seconds",
        "eta_text",
        "message",
        "clips_done",
        "clips_total",
        "clips",
        "stages",
        "elapsed_seconds",
        "updated_at",
        "heartbeat",
        "error",
    )


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------


class ProgressReporter:
    """Acumula o estado do job e emite eventos estruturados.

    Uso típico::

        reporter.start_stage("download", units_total=1)
        reporter.update("download", 0.5, "50% baixado")
        reporter.finish_stage("download")

    Thread-safe: os estágios por clipe podem rodar em pool de threads.
    """

    #: suavização exponencial do ETA (evita número pulando na tela)
    ETA_SMOOTHING = 0.35
    #: teto de crescimento do ETA entre duas emissões (evita saltos absurdos)
    ETA_MAX_GROWTH = 1.35
    #: Um estágio que ainda está rodando nunca vale 0s restantes. Sem esse piso,
    #: qualquer estágio que passe da própria previsão (e todo estágio passa, em
    #: máquina lenta ou rede ruim) faz o painel anunciar "finalizando…" enquanto
    #: o ffmpeg ainda tem meio minuto de trabalho.
    MIN_RUNNING_STAGE_REMAINING_S = 3.0

    def __init__(
        self,
        job_id: str,
        *,
        status_path: Path | None = None,
        events_path: Path | None = None,
        source_minutes: float = 0.0,
        sinks: list[Callable[[dict[str, Any]], None]] | None = None,
        clock: Callable[[], float] = time.time,
        heartbeat_interval: float = 0.0,
    ) -> None:
        self.job_id = job_id
        self.status_path = Path(status_path) if status_path else None
        self.events_path = Path(events_path) if events_path else None
        self.source_minutes = source_minutes
        self._sinks: list[Callable[[dict[str, Any]], None]] = list(sinks or [])
        self._clock = clock
        self._lock = threading.RLock()
        self._heartbeat_interval = max(0.0, float(heartbeat_interval))
        self._heartbeat_stop = threading.Event()
        self._heartbeat: threading.Thread | None = None

        self.started_at = clock()
        self.status = "queued"
        self.current_stage = "queued"
        self.message = ""
        self.error: dict[str, Any] | None = None
        self.result: dict[str, Any] | None = None

        self.stages: dict[str, StageState] = {
            name: StageState(
                name=name,
                label=stage_label(name),
                weight=STAGE_WEIGHTS[name],
                clock=clock,
            )
            for name in STAGE_ORDER
        }
        self.clips: dict[str, ClipProgress] = {}
        self._clip_order: list[str] = []

        # calibração
        self._speed_factor = 1.0
        self._calibration_weight = 0.0
        self._eta_smoothed: float | None = None
        self._last_emit = 0.0
        self._last_percent = -1
        self._percent_high_water = 0.0
        self._predict_all()

    # -- batimento ------------------------------------------------------

    def start_heartbeat(self, interval: float | None = None) -> None:
        """Reemite o snapshot periodicamente enquanto o job roda.

        Sem isso o progresso só se move quando o pipeline chama o reporter, e
        vários estágios são uma única chamada bloqueante: ``candidates`` é um
        prompt sobre a transcrição inteira, ``render`` gasta ~1 min por arquivo.
        Nesses trechos o ETA congelava e não havia como distinguir "trabalhando"
        de "travou" — que é justamente a pergunta que o painel existe para
        responder.

        Batimentos não entram em ``events.jsonl``: aquele arquivo é o histórico
        de transições do job, não um tick de relógio.
        """
        if interval is not None:
            self._heartbeat_interval = max(0.0, float(interval))
        if self._heartbeat_interval <= 0 or self._heartbeat is not None:
            return

        def beat() -> None:
            while not self._heartbeat_stop.wait(self._heartbeat_interval):
                with self._lock:
                    running = self.status in {"queued", "running"}
                if not running:
                    return
                self._emit(force=True, heartbeat=True)

        self._heartbeat_stop.clear()
        self._heartbeat = threading.Thread(
            target=beat, name=f"clip-heartbeat-{self.job_id}", daemon=True
        )
        self._heartbeat.start()

    def stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        thread, self._heartbeat = self._heartbeat, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    # -- configuração -------------------------------------------------

    def add_sink(self, sink: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._sinks.append(sink)

    def set_source_minutes(self, minutes: float) -> None:
        with self._lock:
            self.source_minutes = max(0.0, float(minutes))
            self._predict_all()

    def set_units(self, stage: str, units_total: float) -> None:
        """Informa quantas unidades de trabalho o estágio terá (clipes, chunks…)."""
        with self._lock:
            st = self.stages[stage]
            st.units_total = max(0.0, float(units_total))
            self._predict_all()
        self._emit()

    def skip_stage(self, stage: str, message: str = "") -> None:
        """Marca um estágio como pulado (cache/resume) e redistribui o peso."""
        with self._lock:
            st = self.stages[stage]
            st.status = "skipped"
            st.percent = 100.0
            st.message = message
            st.predicted_seconds = 0.0
        self._emit(message=message or f"{stage_label(stage)}: reaproveitado do cache")

    # -- ciclo de vida dos estágios ------------------------------------

    def start_stage(
        self, stage: str, *, units_total: float | None = None, message: str = ""
    ) -> None:
        with self._lock:
            st = self.stages[stage]
            st.status = "running"
            st.started_at = self._clock()
            st.percent = 0.0
            st.units_done = 0.0
            if units_total is not None:
                st.units_total = max(0.0, float(units_total))
            st.message = message or stage_label(stage)
            self.current_stage = stage
            self.status = "running"
            self._predict_all()
        self._emit(message=st.message, force=True)

    def update(
        self,
        stage: str,
        fraction: float,
        message: str = "",
        *,
        units_done: float | None = None,
    ) -> None:
        with self._lock:
            st = self.stages[stage]
            if st.status == "pending":
                st.status = "running"
                st.started_at = self._clock()
            st.percent = max(st.percent, min(100.0, max(0.0, fraction * 100.0)))
            if units_done is not None:
                st.units_done = max(st.units_done, float(units_done))
            if message:
                st.message = message
            self.current_stage = stage
        self._emit(message=message)

    def advance_units(self, stage: str, done: float, message: str = "") -> None:
        """Avança o progresso do estágio pelo número de unidades concluídas."""
        with self._lock:
            st = self.stages[stage]
            st.units_done = max(st.units_done, float(done))
            total = st.units_total or 0.0
            fraction = (st.units_done / total) if total > 0 else 0.0
        self.update(stage, fraction, message, units_done=done)

    def increment_units(
        self, stage: str, delta: float = 1.0, message: Callable[[float, float], str] | str = ""
    ) -> float:
        """Soma ``delta`` unidades concluídas e devolve o novo total.

        :meth:`advance_units` recebe um valor absoluto, então dois workers que
        terminam ao mesmo tempo leem o mesmo contador e mandam o mesmo número —
        ``max()`` colapsa os dois em um. Com ``render_workers=2`` a barra de
        render passava a contar menos arquivos do que existem e só se acertava
        no fim do estágio. Incrementar sob o lock resolve.

        ``message`` pode ser um callable ``(done, total) -> str`` para que o
        texto use o contador já resolvido, sem outra leitura de fora do lock.
        """
        with self._lock:
            st = self.stages[stage]
            total = st.units_total or 0.0
            st.units_done = min(total, st.units_done + float(delta)) if total > 0 else st.units_done + float(delta)
            done = st.units_done
            fraction = (done / total) if total > 0 else 0.0
        text = message(done, total) if callable(message) else message
        self.update(stage, fraction, text, units_done=done)
        return done

    def finish_stage(self, stage: str, message: str = "") -> None:
        with self._lock:
            st = self.stages[stage]
            st.status = "done"
            st.percent = 100.0
            st.ended_at = self._clock()
            if message:
                st.message = message
            self._calibrate(st)
        self._emit(message=message, force=True)

    # -- clipes ---------------------------------------------------------

    def register_clips(self, clips: list[ClipProgress]) -> None:
        with self._lock:
            for clip in clips:
                if clip.slug not in self.clips:
                    self._clip_order.append(clip.slug)
                self.clips[clip.slug] = clip
        self._emit(force=True)

    def update_clip(
        self,
        slug: str,
        *,
        status: str | None = None,
        message: str | None = None,
        format_name: str | None = None,
        format_status: str | None = None,
        vertical_skipped: str | None = None,
        score: float | None = None,
    ) -> None:
        with self._lock:
            clip = self.clips.get(slug)
            if clip is None:
                clip = ClipProgress(slug=slug)
                self.clips[slug] = clip
                self._clip_order.append(slug)
            if status is not None:
                clip.status = status
            if message is not None:
                clip.message = message
            if format_name is not None and format_status is not None:
                clip.formats[format_name] = format_status
            if vertical_skipped is not None:
                clip.vertical_skipped = vertical_skipped
            if score is not None:
                clip.score = score
        self._emit(message=message or "")

    @property
    def clips_done(self) -> int:
        with self._lock:
            return sum(
                1 for c in self.clips.values() if c.status in {"done", "skipped", "error"}
            )

    @property
    def clips_total(self) -> int:
        with self._lock:
            return len(self.clips)

    # -- término --------------------------------------------------------

    def finish(self, result: dict[str, Any] | None = None, message: str = "") -> None:
        self.stop_heartbeat()
        with self._lock:
            self.status = "done"
            self.current_stage = "done"
            self.result = result
            self.message = message or "Concluído"
            for st in self.stages.values():
                if st.status == "running":
                    st.status = "done"
                    st.percent = 100.0
                    st.ended_at = self._clock()
            self._eta_smoothed = 0.0
        self._emit(message=self.message, force=True)

    def fail(
        self,
        error: BaseException | str,
        *,
        stage: str | None = None,
        retriable: bool = True,
        hint: str = "",
    ) -> None:
        """Marca o job como erro. Nunca deixa a UI presa girando."""
        self.stop_heartbeat()
        with self._lock:
            stage = stage or self.current_stage
            self.status = "error"
            st = self.stages.get(stage)
            if st is not None:
                st.status = "error"
                st.ended_at = self._clock()
            self.error = {
                "stage": stage,
                "stage_label": stage_label(stage),
                "type": type(error).__name__ if isinstance(error, BaseException) else "Error",
                "message": str(error),
                "retriable": retriable,
                "hint": hint,
            }
            self.message = f"Falhou em {stage_label(stage)}: {error}"
            self._eta_smoothed = None
        self._emit(message=self.message, force=True)

    def cancel(self, message: str = "Cancelado pelo usuário") -> None:
        self.stop_heartbeat()
        with self._lock:
            self.status = "canceled"
            self.current_stage = "canceled"
            self.message = message
            self._eta_smoothed = None
        self._emit(message=message, force=True)

    # -- cálculo --------------------------------------------------------

    def _stage_units(self, stage: str) -> float:
        st = self.stages[stage]
        return st.units_total

    def _predict_all(self) -> None:
        """(Re)calcula a previsão de duração de cada estágio ainda pendente."""
        for name, st in self.stages.items():
            if st.status in {"done", "skipped"}:
                if st.status == "skipped":
                    st.predicted_seconds = 0.0
                elif st.elapsed is not None:
                    st.predicted_seconds = st.elapsed
                continue
            model = STAGE_COSTS[name]
            st.predicted_seconds = model.predict(self.source_minutes, self._stage_units(name))

    def _calibrate(self, st: StageState) -> None:
        """Aprende o quão rápida esta máquina/rede é comparada aos priors."""
        elapsed = st.elapsed
        predicted = STAGE_COSTS[st.name].predict(self.source_minutes, st.units_total)
        if elapsed is None or predicted <= 0.5:
            return
        observed = elapsed / predicted
        # damping: um estágio anômalo não pode dominar a estimativa
        observed = min(max(observed, 0.2), 5.0)
        weight = st.weight
        total = self._calibration_weight + weight
        self._speed_factor = (
            self._speed_factor * self._calibration_weight + observed * weight
        ) / total
        self._calibration_weight = total

    def _percent(self) -> float:
        total_weight = sum(st.weight for st in self.stages.values()) or 1.0
        done = 0.0
        for st in self.stages.values():
            done += st.weight * (st.percent / 100.0)
        percent = min(100.0, 100.0 * done / total_weight)
        # A barra nunca anda para trás: reprocessar um estágio já concluído
        # (retry parcial) não pode fazer o número cair na cara do usuário.
        self._percent_high_water = max(self._percent_high_water, percent)
        return self._percent_high_water

    def _raw_eta(self) -> float | None:
        """Segundos restantes = estágio atual + estágios futuros, calibrados."""
        if self.status in {"done", "canceled"}:
            return 0.0
        if self.status == "error":
            return None

        remaining = 0.0
        saw_any = False
        for name in STAGE_ORDER:
            st = self.stages[name]
            if st.status in {"done", "skipped"}:
                continue
            predicted = (st.predicted_seconds or 0.0) * self._speed_factor
            if st.status == "running":
                saw_any = True
                elapsed = st.elapsed or 0.0
                frac = st.percent / 100.0
                if st.units_total > 0 and st.units_done > 0:
                    # taxa medida ao vivo: mais confiável que o prior
                    rate = elapsed / st.units_done
                    live = rate * max(0.0, st.units_total - st.units_done)
                    predicted_remaining = live
                elif frac > 0.08 and elapsed > 3.0:
                    predicted_remaining = elapsed * (1.0 - frac) / frac
                else:
                    predicted_remaining = max(0.0, predicted - elapsed)
                # Enquanto o estágio não terminou, ele custa algo: a última
                # unidade ainda está sendo escrita quando o contador já bateu no
                # total, e todo estágio eventualmente passa da própria previsão.
                remaining += max(predicted_remaining, self.MIN_RUNNING_STAGE_REMAINING_S)
            else:
                saw_any = True
                remaining += max(0.0, predicted)
        if not saw_any:
            return 0.0
        return remaining

    def _smooth_eta(self, raw: float | None) -> float | None:
        if raw is None:
            return None
        if self._eta_smoothed is None:
            self._eta_smoothed = raw
            return raw
        prev = self._eta_smoothed
        smoothed = prev + self.ETA_SMOOTHING * (raw - prev)
        # nunca deixar o ETA explodir de uma emissão para outra
        ceiling = max(prev * self.ETA_MAX_GROWTH, prev + 20.0)
        smoothed = min(smoothed, ceiling)
        self._eta_smoothed = max(0.0, smoothed)
        return self._eta_smoothed

    # -- snapshot / emissão ---------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            stage = self.current_stage
            st = self.stages.get(stage)
            eta = self._smooth_eta(self._raw_eta())
            stage_elapsed = st.elapsed if st is not None else None
            payload: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "job_id": self.job_id,
                "status": self.status,
                "stage": stage,
                "stage_label": stage_label(stage),
                "stage_percent": round(st.percent, 2) if st else 0.0,
                # Quanto tempo o estágio atual já leva: é o número que separa
                # "está trabalhando" de "travou" quando não há unidades para
                # contar (um único prompt, um único ffmpeg).
                "stage_elapsed_seconds": (
                    round(stage_elapsed, 2) if stage_elapsed is not None else None
                ),
                "percent": round(self._percent(), 2),
                "eta_seconds": (int(round(eta)) if eta is not None else None),
                "eta_text": format_eta(eta, self.status),
                "message": self.message,
                "clips_done": self.clips_done,
                "clips_total": self.clips_total,
                "clips": [self.clips[s].to_dict() for s in self._clip_order],
                "stages": [self.stages[n].to_dict() for n in STAGE_ORDER],
                "elapsed_seconds": round(self._clock() - self.started_at, 2),
                "updated_at": self._clock(),
                "heartbeat": False,
                "error": self.error,
                "source_minutes": round(self.source_minutes, 2),
                "result": self.result,
            }
            return payload

    #: Intervalo mínimo entre emissões que não mudam o percentual inteiro.
    EMIT_MIN_INTERVAL = 0.15

    def _emit(self, message: str = "", *, force: bool = False, heartbeat: bool = False) -> None:
        now = self._clock()
        if not force:
            with self._lock:
                percent_now = int(self._percent())
            # Mudou o percentual inteiro? Sempre emite: são no máximo ~100
            # eventos por job e é isso que faz a barra andar de verdade em
            # estágios rápidos. O throttle vale só para repetição de mensagem.
            if percent_now == self._last_percent and (now - self._last_emit) < self.EMIT_MIN_INTERVAL:
                return
            self._last_percent = percent_now
        self._last_emit = now
        with self._lock:
            if message:
                self.message = message
            payload = self.snapshot()
            payload["heartbeat"] = heartbeat
        self._write_status(payload)
        if not heartbeat:
            self._append_event(payload)
        for sink in list(self._sinks):
            try:
                sink(payload)
            except Exception:  # noqa: BLE001 - um sink ruim não derruba o job
                pass

    def _write_status(self, payload: dict[str, Any]) -> None:
        if self.status_path is None:
            return
        try:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.status_path.with_suffix(f".tmp-{uuid.uuid4().hex[:8]}")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
            os.replace(tmp, self.status_path)
        except OSError:
            pass

    def _append_event(self, payload: dict[str, Any]) -> None:
        if self.events_path is None:
            return
        try:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            slim = {
                k: payload[k]
                for k in (
                    "job_id",
                    "status",
                    "stage",
                    "stage_label",
                    "percent",
                    "stage_percent",
                    "eta_seconds",
                    "eta_text",
                    "message",
                    "clips_done",
                    "clips_total",
                    "updated_at",
                )
            }
            with self.events_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(slim, ensure_ascii=False) + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Pub/sub em memória (usado pelo SSE da API)
# ---------------------------------------------------------------------------


class EventBroker:
    """Distribui snapshots de progresso para assinantes (SSE/websocket)."""

    def __init__(self, maxsize: int = 256) -> None:
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._last: dict[str, Any] | None = None
        self._maxsize = maxsize

    def publish(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._last = payload
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._maxsize)
        with self._lock:
            if self._last is not None:
                q.put_nowait(self._last)
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def stream(self, timeout: float = 15.0) -> Iterator[dict[str, Any]]:
        q = self.subscribe()
        try:
            while True:
                try:
                    payload = q.get(timeout=timeout)
                except queue.Empty:
                    yield {"type": "heartbeat"}
                    continue
                yield payload
                if payload.get("status") in {"done", "error", "canceled"}:
                    return
        finally:
            self.unsubscribe(q)
