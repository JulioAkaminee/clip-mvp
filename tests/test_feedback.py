"""Testes de `clip rate` -> work/feedback.jsonl (SPEC §14.7)."""

from __future__ import annotations

import json
from pathlib import Path

from clip_mvp.feedback import load_recent_feedback, rate_clip, write_selected_index


def test_rate_clip_appends_jsonl_record(tmp_path: Path):
    work_dir = tmp_path / "work"
    write_selected_index(
        work_dir,
        "job_abc",
        [{"slug": "piada-do-treino", "score": 87, "reason": "punchline forte", "out_dir": "out/87_piada"}],
    )

    record = rate_clip(work_dir, "job_abc", "piada-do-treino", "good", note="ótimo corte")

    feedback_path = work_dir / "feedback.jsonl"
    assert feedback_path.exists()
    lines = feedback_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["verdict"] == "good"
    assert saved["score"] == 87
    assert saved["note"] == "ótimo corte"
    assert record == saved


def test_rate_clip_without_selected_index_still_records(tmp_path: Path):
    work_dir = tmp_path / "work"
    record = rate_clip(work_dir, "job_xyz", "clip-desconhecido", "bad", note="fraco")
    assert record["score"] is None
    assert record["verdict"] == "bad"


def test_load_recent_feedback_respects_n(tmp_path: Path):
    work_dir = tmp_path / "work"
    for i in range(10):
        rate_clip(work_dir, "job_abc", f"clip-{i}", "good" if i % 2 == 0 else "bad")

    recent = load_recent_feedback(work_dir, n=3)
    assert len(recent) == 3
    assert recent[-1]["slug"] == "clip-9"
