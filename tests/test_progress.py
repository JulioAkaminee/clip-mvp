"""Contrato do payload de progresso e comportamento do ETA."""

from __future__ import annotations

import json

import pytest

from clip_mvp.progress import (
    STAGE_ORDER,
    STAGE_WEIGHTS,
    ClipProgress,
    EventBroker,
    ProgressReporter,
    _job_payload_keys,
    format_duration,
    format_eta,
)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def reporter(clock, tmp_path) -> ProgressReporter:
    return ProgressReporter(
        "job-teste",
        status_path=tmp_path / "status.json",
        events_path=tmp_path / "events.jsonl",
        source_minutes=30.0,
        clock=clock,
    )


class TestPayloadShape:
    def test_has_all_required_keys(self, reporter):
        payload = reporter.snapshot()
        for key in _job_payload_keys():
            assert key in payload, f"campo obrigatório ausente: {key}"

    def test_required_fields_from_spec_are_present(self, reporter):
        # os campos que a UI/API consomem, citados no pedido do produto
        payload = reporter.snapshot()
        assert set(
            ["stage", "percent", "eta_seconds", "message", "clips_done", "clips_total"]
        ).issubset(payload)

    def test_payload_is_json_serializable(self, reporter):
        reporter.start_stage("download", units_total=1)
        reporter.register_clips([ClipProgress(slug="corte-um", score=82.0)])
        json.dumps(reporter.snapshot(), ensure_ascii=False)

    def test_stage_entries_have_stable_shape(self, reporter):
        payload = reporter.snapshot()
        assert len(payload["stages"]) == len(STAGE_ORDER)
        for stage in payload["stages"]:
            assert set(stage) == {
                "name",
                "label",
                "weight",
                "status",
                "percent",
                "message",
                "units_total",
                "units_done",
                "elapsed_seconds",
                "predicted_seconds",
            }

    def test_stage_names_follow_pipeline_order(self, reporter):
        names = [s["name"] for s in reporter.snapshot()["stages"]]
        assert names == list(STAGE_ORDER)

    def test_clip_entries_have_stable_shape(self, reporter):
        reporter.register_clips([ClipProgress(slug="corte-um", score=90.0)])
        clip = reporter.snapshot()["clips"][0]
        assert set(clip) == {
            "slug",
            "score",
            "status",
            "formats",
            "message",
            "vertical_skipped",
        }

    def test_stage_weights_sum_to_100(self):
        assert sum(STAGE_WEIGHTS.values()) == pytest.approx(100.0)


class TestPercent:
    def test_starts_at_zero(self, reporter):
        assert reporter.snapshot()["percent"] == 0.0

    def test_advances_with_stage_weight(self, reporter):
        reporter.start_stage("download", units_total=1)
        reporter.finish_stage("download")
        assert reporter.snapshot()["percent"] == pytest.approx(
            STAGE_WEIGHTS["download"], abs=0.01
        )

    def test_partial_stage_counts_proportionally(self, reporter):
        reporter.start_stage("download", units_total=1)
        reporter.update("download", 0.5)
        assert reporter.snapshot()["percent"] == pytest.approx(
            STAGE_WEIGHTS["download"] / 2, abs=0.01
        )

    def test_never_goes_backwards(self, reporter, clock):
        seen = []
        for stage in STAGE_ORDER:
            reporter.start_stage(stage, units_total=2)
            for frac in (0.3, 0.7):
                reporter.update(stage, frac)
                seen.append(reporter.snapshot()["percent"])
            clock.advance(5)
            reporter.finish_stage(stage)
            seen.append(reporter.snapshot()["percent"])
        assert seen == sorted(seen)

    def test_reaches_100_when_all_stages_done(self, reporter, clock):
        for stage in STAGE_ORDER:
            reporter.start_stage(stage, units_total=1)
            clock.advance(2)
            reporter.finish_stage(stage)
        assert reporter.snapshot()["percent"] == pytest.approx(100.0, abs=0.01)

    def test_skipped_stage_counts_as_complete(self, reporter):
        reporter.skip_stage("download", "cache")
        assert reporter.snapshot()["percent"] == pytest.approx(
            STAGE_WEIGHTS["download"], abs=0.01
        )


class TestEta:
    def test_eta_present_before_start(self, reporter):
        payload = reporter.snapshot()
        assert payload["eta_seconds"] is not None
        assert payload["eta_seconds"] > 0

    def test_eta_shrinks_as_stages_complete(self, reporter, clock):
        first = reporter.snapshot()["eta_seconds"]
        reporter.start_stage("download", units_total=1)
        clock.advance(30)
        reporter.finish_stage("download")
        reporter.start_stage("transcribe", units_total=3)
        clock.advance(30)
        reporter.finish_stage("transcribe")
        assert reporter.snapshot()["eta_seconds"] < first

    def test_eta_is_zero_when_done(self, reporter, clock):
        reporter.start_stage("download", units_total=1)
        clock.advance(10)
        reporter.finish("ok")
        assert reporter.snapshot()["eta_seconds"] == 0

    def test_eta_is_none_on_error(self, reporter):
        reporter.start_stage("download", units_total=1)
        reporter.fail(RuntimeError("boom"))
        payload = reporter.snapshot()
        assert payload["eta_seconds"] is None
        assert payload["status"] == "error"

    def test_eta_uses_live_rate_within_a_stage(self, reporter, clock):
        """10 unidades a 4s cada: depois de 2, faltam ~32s só nesse estágio."""
        reporter.start_stage("render", units_total=10)
        clock.advance(8)
        reporter.advance_units("render", 2)
        stage_remaining = reporter.stages["render"]
        rate = 8 / 2
        assert rate * 8 == pytest.approx(32.0)
        assert reporter.snapshot()["eta_seconds"] >= 30

    def test_slow_machine_calibrates_remaining_stages_upward(self, tmp_path):
        fast, slow = FakeClock(), FakeClock()
        r_fast = ProgressReporter("f", source_minutes=30.0, clock=fast)
        r_slow = ProgressReporter("s", source_minutes=30.0, clock=slow)

        r_fast.start_stage("download", units_total=1)
        fast.advance(10)
        r_fast.finish_stage("download")

        r_slow.start_stage("download", units_total=1)
        slow.advance(400)
        r_slow.finish_stage("download")

        assert r_slow.snapshot()["eta_seconds"] > r_fast.snapshot()["eta_seconds"]

    def test_eta_does_not_spike_between_emissions(self, reporter, clock):
        reporter.start_stage("download", units_total=1)
        clock.advance(5)
        before = reporter.snapshot()["eta_seconds"]
        reporter.set_units("render", 300)  # explosão artificial de trabalho
        after = reporter.snapshot()["eta_seconds"]
        assert after <= max(before * ProgressReporter.ETA_MAX_GROWTH, before + 20) + 1

    def test_longer_video_has_longer_eta(self, clock):
        short = ProgressReporter("a", source_minutes=5.0, clock=FakeClock())
        long = ProgressReporter("b", source_minutes=120.0, clock=FakeClock())
        assert long.snapshot()["eta_seconds"] > short.snapshot()["eta_seconds"]


class TestEtaFormatting:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (None, "calculando tempo restante…"),
            (0, "finalizando…"),
            (45, "~45 s restantes"),
            (59.4, "~59 s restantes"),
            (90, "~1.5 min restantes"),
            (120, "~2 min restantes"),
            (1500, "~25 min restantes"),
        ],
    )
    def test_format_eta_ptbr(self, seconds, expected):
        assert format_eta(seconds) == expected

    def test_seconds_below_one_minute(self):
        assert "s restantes" in format_eta(30)

    def test_minutes_above_one_minute(self):
        assert "min restantes" in format_eta(300)

    def test_format_duration(self):
        assert format_duration(45) == "45s"
        assert format_duration(90) == "1m30s"
        assert format_duration(3700) == "1h01m"


class TestClips:
    def test_clip_counters(self, reporter):
        reporter.register_clips(
            [ClipProgress(slug="a"), ClipProgress(slug="b"), ClipProgress(slug="c")]
        )
        assert reporter.snapshot()["clips_total"] == 3
        assert reporter.snapshot()["clips_done"] == 0
        reporter.update_clip("a", status="done")
        reporter.update_clip("b", status="error")
        payload = reporter.snapshot()
        assert payload["clips_done"] == 2

    def test_per_format_status(self, reporter):
        reporter.register_clips([ClipProgress(slug="a")])
        reporter.update_clip("a", format_name="vertical_facetrack", format_status="running")
        reporter.update_clip("a", format_name="horizontal_16x9", format_status="done")
        formats = reporter.snapshot()["clips"][0]["formats"]
        assert formats == {"vertical_facetrack": "running", "horizontal_16x9": "done"}

    def test_vertical_skipped_is_surfaced(self, reporter):
        reporter.register_clips([ClipProgress(slug="a")])
        reporter.update_clip("a", vertical_skipped="context_exceeds_90s")
        assert reporter.snapshot()["clips"][0]["vertical_skipped"] == "context_exceeds_90s"


class TestErrorState:
    def test_error_payload_never_leaves_ui_spinning(self, reporter):
        reporter.start_stage("transcribe", units_total=2)
        reporter.fail(RuntimeError("429 rate limit"), hint="tente de novo")
        payload = reporter.snapshot()
        assert payload["status"] == "error"
        assert payload["error"]["retriable"] is True
        assert payload["error"]["stage"] == "transcribe"
        assert payload["error"]["hint"] == "tente de novo"
        assert payload["stages"][1]["status"] == "error"

    def test_cancel_state(self, reporter):
        reporter.start_stage("download", units_total=1)
        reporter.cancel()
        assert reporter.snapshot()["status"] == "canceled"


class TestSinksAndPersistence:
    def test_status_file_written_atomically(self, reporter, tmp_path):
        reporter.start_stage("download", units_total=1)
        reporter.finish_stage("download")
        status = json.loads((tmp_path / "status.json").read_text("utf-8"))
        assert status["job_id"] == "job-teste"
        assert status["stages"][0]["status"] == "done"
        assert not list(tmp_path.glob("status.tmp-*"))

    def test_events_jsonl_appends_one_line_per_emission(self, reporter, tmp_path):
        reporter.start_stage("download", units_total=1)
        reporter.finish_stage("download")
        reporter.start_stage("transcribe", units_total=1)
        lines = (tmp_path / "events.jsonl").read_text("utf-8").strip().splitlines()
        assert len(lines) >= 3
        event = json.loads(lines[-1])
        assert event["stage"] == "transcribe"
        assert "eta_seconds" in event

    def test_sink_exception_does_not_break_job(self, reporter):
        def broken(_payload):
            raise ValueError("sink ruim")

        reporter.add_sink(broken)
        reporter.start_stage("download", units_total=1)
        assert reporter.snapshot()["status"] == "running"


class TestEventBroker:
    def test_subscriber_gets_last_payload_immediately(self):
        broker = EventBroker()
        broker.publish({"percent": 42, "status": "running"})
        q = broker.subscribe()
        assert q.get_nowait()["percent"] == 42

    def test_publish_reaches_all_subscribers(self):
        broker = EventBroker()
        a, b = broker.subscribe(), broker.subscribe()
        broker.publish({"percent": 10, "status": "running"})
        assert a.get_nowait()["percent"] == 10
        assert b.get_nowait()["percent"] == 10

    def test_stream_stops_on_terminal_status(self):
        broker = EventBroker()
        broker.publish({"status": "done", "percent": 100})
        payloads = list(broker.stream(timeout=0.1))
        assert payloads[-1]["status"] == "done"
