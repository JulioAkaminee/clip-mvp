"""Testes de face tracking: hold/revert de centro + EMA + render (SPEC §9)."""

from __future__ import annotations

from pathlib import Path

from clip_mvp.face_track import (
    DetectedFace,
    FaceCenter,
    fill_gaps,
    is_wide_table_shot,
    pick_featured_face,
    render_vertical_facetrack,
    smooth_centers,
)
from clip_mvp.models import Window
from clip_mvp.utils import ffprobe_duration


def test_fill_gaps_holds_last_center_for_short_gap():
    dt = 0.1
    samples = [FaceCenter(t=0.0, cx=0.3, cy=0.5)] + [None] * 3  # 0.3s de buraco
    filled = fill_gaps(samples, dt=dt)
    assert filled[-1].cx == 0.3
    assert filled[-1].detected is False


def test_fill_gaps_reverts_to_frame_center_after_2s():
    dt = 0.1
    samples = [FaceCenter(t=0.0, cx=0.3, cy=0.5)] + [None] * 25  # 2.5s de buraco
    filled = fill_gaps(samples, dt=dt)
    assert filled[-1].cx == 0.5
    assert filled[-1].cy == 0.5


def test_fill_gaps_no_known_center_defaults_to_frame_center():
    filled = fill_gaps([None, None, None], dt=0.1)
    assert all(c.cx == 0.5 and c.cy == 0.5 for c in filled)


def test_smooth_centers_limits_velocity_between_samples():
    centers = [FaceCenter(t=0.0, cx=0.1, cy=0.5), FaceCenter(t=0.1, cx=0.9, cy=0.5)]
    smoothed = smooth_centers(centers, max_step=0.05)
    delta = abs(smoothed[1].cx - smoothed[0].cx)
    assert delta <= 0.05 + 1e-9


def test_smooth_centers_first_sample_unchanged():
    centers = [FaceCenter(t=0.0, cx=0.42, cy=0.37)]
    smoothed = smooth_centers(centers)
    assert smoothed[0].cx == 0.42
    assert smoothed[0].cy == 0.37


def test_pick_featured_face_keeps_current_until_someone_is_clearly_larger():
    left = DetectedFace(cx=0.22, cy=0.4, area=0.04)
    mid = DetectedFace(cx=0.50, cy=0.38, area=0.035)
    right = DetectedFace(cx=0.78, cy=0.42, area=0.033)
    picked = pick_featured_face([left, mid, right], last_cx=0.22)
    assert picked is left
    louder = DetectedFace(cx=0.78, cy=0.40, area=0.09)
    switched = pick_featured_face([left, mid, louder], last_cx=0.22)
    assert switched is louder


def test_wide_table_shot_uses_full_frame_when_three_faces_are_spread():
    centers = [
        FaceCenter(t=i * 0.1, cx=0.3, cy=0.4, n_faces=3, spread_x=0.55)
        for i in range(12)
    ]
    assert is_wide_table_shot(centers) is True
    closeup = [FaceCenter(t=0.0, cx=0.5, cy=0.4, n_faces=1, spread_x=0.0, area=0.12)]
    assert is_wide_table_shot(closeup) is False
    table = [FaceCenter(t=0.0, cx=0.45, cy=0.4, n_faces=1, spread_x=0.0, area=0.032)]
    assert is_wide_table_shot(table) is True


def test_render_vertical_facetrack_with_injected_centers(tmp_path: Path, sample_video_path: Path):
    window = Window(start=1.0, end=4.0)
    centers = [FaceCenter(t=t / 10.0, cx=0.5, cy=0.5) for t in range(30)]
    out_path = tmp_path / "vertical_facetrack.mp4"

    render_vertical_facetrack(sample_video_path, window, out_path, centers=centers)

    assert out_path.exists()
    duration = ffprobe_duration(out_path)
    assert abs(duration - window.duration_s) < 0.5
