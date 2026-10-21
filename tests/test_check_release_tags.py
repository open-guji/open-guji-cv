"""scripts/check_release_tags.py：发进 main 的版本是否都有 tag、tag 是否在 main 主线上。只测判定，不碰远端。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_release_tags import verdict  # noqa: E402

MAIN = [("c3", "发 v0.4.8：rc/v0.4.8 合进 main (#287)"),
        ("c2", "hanzi 库 B2 (#276)"),
        ("c1", "发 v0.4.7：rc/v0.4.7 合进 main (#245)")]
HEADS = ["rc/v0.4.7", "rc/v0.4.8", "rc/v0.4.9"]


def test_all_tagged_rc_in_test_ok():
    code, lines = verdict(MAIN, {"v0.4.7": "c1", "v0.4.8": "c3"}, HEADS)
    assert code == 0
    assert any("v0.4.9" in ln and "测试中" in ln for ln in lines)   # 还没发的 rc 不算缺


def test_released_without_tag():
    code, lines = verdict(MAIN, {"v0.4.7": "c1"}, HEADS)
    assert code == 1 and any(ln.startswith("✗ v0.4.8") and "c3" in ln for ln in lines)


def test_tag_off_main():
    code, lines = verdict(MAIN, {"v0.4.7": "c1", "v0.4.8": "rcsha"}, HEADS)   # 打在 rc 分支上
    assert code == 1 and any("不在 main 主线上" in ln for ln in lines)


def test_rc_branch_deleted_still_checked():
    code, _ = verdict(MAIN, {"v0.4.8": "c3"}, [])                  # rc/v0.4.7 删了，main 上仍提到它
    assert code == 1


def test_rc_tag_ignored():
    code, lines = verdict(MAIN, {"v0.4.7": "c1", "v0.4.8": "c3", "v0.4.9-rc.1": "x"}, HEADS)
    assert code == 0 and not any("rc.1" in ln for ln in lines)
