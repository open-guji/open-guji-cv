"""scripts/check_rc_target.py：合 PR 前核对目标 rc 是否已发版（GUJI-657）。只测判定，不碰远端。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_rc_target import verdict  # noqa: E402

HEADS = ["rc/v0.4.6", "rc/v0.4.7", "rc/v0.4.8"]


def test_unreleased_newest_ok():
    code, _ = verdict("rc/v0.4.8", {"v0.4.6", "v0.4.7", "v0.4.8-rc.1"}, HEADS)
    assert code == 0                                   # rc tag 不算发版


def test_released_points_to_dev():
    code, msg = verdict("rc/v0.4.7", {"v0.4.6", "v0.4.7"}, HEADS)
    assert code == 1 and "改投 dev" in msg


def test_dev_ok_main_refused():
    assert verdict("dev", set(), HEADS)[0] == 0
    assert verdict("main", set(), HEADS)[0] == 4


def test_not_newest_rc():
    code, msg = verdict("rc/v0.4.6", {"v0.4.5"}, HEADS)
    assert code == 2 and "rc/v0.4.8" in msg


def test_not_dev_or_rc():
    assert verdict("feat/x", set(), HEADS)[0] == 3
