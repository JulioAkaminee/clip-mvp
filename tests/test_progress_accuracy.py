"""Precisão do progresso: contagem sob paralelismo, ETA honesto e batimento.

Um job de podcast longo passa minutos em estágios que são **uma** chamada
bloqueante. O painel só serve para alguma coisa se, nesses trechos, ele
continuar se movendo e não anunciar que está acabando enquanto o ffmpeg ainda
tem meio minuto de trabalho.
"""

from __future__ import annotations

import json
import threading
import time

from clip_mvp.progress import ProgressReporter


def reporter(**kwargs) -> ProgressReporter:
    return ProgressReporter("job_test", **kwargs)


class TestParallelUnitCounting:
    def test_concurrent_increments_are_not_collapsed(self):
        """Dois workers terminando junto contam dois arquivos, não um.

        `advance_units` recebe valor absoluto: quem lê o contador antes de
        incrementar manda o mesmo número que o vizinho e o `max()` engole um dos
        dois. Com `render_workers=2` a barra de render passava a contar menos
        arquivos do que existem.
        """
        rep = reporter()
        rep.start_stage("render", units_total=6)

        barrier = threading.Barrier(6)

        def work() -> None:
            barrier.wait()
            rep.increment_units("render")

        threads = [threading.Thread(target=work) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert rep.stages["render"].units_done == 6
        assert rep.stages["render"].percent == 100.0

    def test_increment_returns_the_resolved_counter(self):
        rep = reporter()
        rep.start_stage("score", units_total=3)
        assert rep.increment_units("score") == 1.0
        assert rep.increment_units("score") == 2.0

    def test_increment_never_passes_the_total(self):
        rep = reporter()
        rep.start_stage("render", units_total=2)
        for _ in range(5):
            rep.increment_units("render")
        assert rep.stages["render"].units_done == 2

    def test_message_callback_sees_the_resolved_counter(self):
        rep = reporter()
        rep.start_stage("render", units_total=3)
        rep.increment_units("render", message=lambda done, total: f"{int(done)}/{int(total)}")
        assert rep.snapshot()["message"] == "1/3"


class TestEtaHonesty:
    def test_a_running_stage_never_reports_zero_seconds_left(self):
        """Todo estágio acaba passando da previsão; isso não é "finalizando"."""
        clock = [1000.0]
        rep = reporter(clock=lambda: clock[0], source_minutes=1.0)
        rep.start_stage("render", units_total=1)
        # muito além de qualquer previsão do prior
        clock[0] += 6000.0
        payload = rep.snapshot()
        assert payload["eta_seconds"] >= ProgressReporter.MIN_RUNNING_STAGE_REMAINING_S
        assert payload["eta_text"] != "finalizando…"

    def test_the_last_unit_still_costs_time(self):
        """Contador no total mas estágio aberto: o arquivo ainda está sendo escrito."""
        clock = [1000.0]
        rep = reporter(clock=lambda: clock[0], source_minutes=1.0)
        rep.start_stage("render", units_total=2)
        clock[0] += 40.0
        rep.increment_units("render")
        clock[0] += 40.0
        rep.increment_units("render")
        assert rep.stages["render"].units_done == 2
        assert rep.snapshot()["eta_seconds"] > 0

    def test_a_finished_job_reports_zero(self):
        rep = reporter()
        rep.start_stage("render", units_total=1)
        rep.finish_stage("render")
        rep.finish()
        assert rep.snapshot()["eta_seconds"] == 0


class TestTerminalEtaText:
    """Um job terminado não tem "tempo restante" — o texto tem de dizer isso."""

    def test_a_finished_job_says_concluido(self):
        rep = reporter()
        rep.start_stage("render", units_total=1)
        rep.finish_stage("render")
        rep.finish()
        assert rep.snapshot()["eta_text"] == "concluído"

    def test_a_failed_job_does_not_claim_to_be_calculating(self):
        rep = reporter()
        rep.start_stage("score", units_total=3)
        rep.fail(RuntimeError("429 rate limit"), hint="espere um pouco")
        payload = rep.snapshot()
        assert payload["eta_seconds"] is None
        assert payload["eta_text"] == "interrompido"

    def test_a_canceled_job_says_cancelado(self):
        rep = reporter()
        rep.start_stage("download", units_total=1)
        rep.cancel()
        assert rep.snapshot()["eta_text"] == "cancelado"

    def test_a_running_job_still_gets_a_countdown(self):
        clock = [1000.0]
        rep = reporter(clock=lambda: clock[0], source_minutes=30.0)
        rep.start_stage("transcribe", units_total=3)
        clock[0] += 5.0
        assert "restantes" in rep.snapshot()["eta_text"]

    def test_stage_elapsed_is_exposed_for_stages_without_units(self):
        """`candidates` é um prompt só: o tempo do estágio é o único sinal de vida."""
        clock = [1000.0]
        rep = reporter(clock=lambda: clock[0])
        rep.start_stage("candidates", units_total=1)
        clock[0] += 37.0
        assert rep.snapshot()["stage_elapsed_seconds"] == 37.0


class TestHeartbeat:
    def test_the_snapshot_keeps_moving_without_pipeline_calls(self, tmp_path):
        status = tmp_path / "status.json"
        rep = reporter(status_path=status, heartbeat_interval=0.05)
        rep.start_stage("candidates", units_total=1)
        rep.start_heartbeat()
        try:
            first = json.loads(status.read_text("utf-8"))["updated_at"]
            time.sleep(0.3)
            second = json.loads(status.read_text("utf-8"))["updated_at"]
        finally:
            rep.stop_heartbeat()
        assert second > first

    def test_heartbeats_stay_out_of_the_event_history(self, tmp_path):
        """`events.jsonl` é o histórico de transições, não um tique de relógio."""
        events = tmp_path / "events.jsonl"
        rep = reporter(
            status_path=tmp_path / "status.json",
            events_path=events,
            heartbeat_interval=0.05,
        )
        rep.start_stage("candidates", units_total=1)
        before = len(events.read_text("utf-8").splitlines())
        rep.start_heartbeat()
        try:
            time.sleep(0.3)
        finally:
            rep.stop_heartbeat()
        assert len(events.read_text("utf-8").splitlines()) == before

    def test_heartbeats_are_flagged_in_the_payload(self, tmp_path):
        seen: list[dict] = []
        rep = reporter(sinks=[seen.append], heartbeat_interval=0.05)
        rep.start_stage("candidates", units_total=1)
        assert seen[-1]["heartbeat"] is False
        rep.start_heartbeat()
        try:
            time.sleep(0.2)
        finally:
            rep.stop_heartbeat()
        assert any(payload["heartbeat"] for payload in seen)

    def test_the_thread_stops_when_the_job_ends(self, tmp_path):
        rep = reporter(status_path=tmp_path / "status.json", heartbeat_interval=0.05)
        rep.start_stage("candidates", units_total=1)
        rep.start_heartbeat()
        rep.finish()
        assert rep._heartbeat is None
        # e não volta a bater depois do término
        updated = json.loads((tmp_path / "status.json").read_text("utf-8"))["updated_at"]
        time.sleep(0.2)
        assert json.loads((tmp_path / "status.json").read_text("utf-8"))["updated_at"] == updated

    def test_disabled_by_default(self):
        rep = reporter()
        rep.start_heartbeat()
        assert rep._heartbeat is None
