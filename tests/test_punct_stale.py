"""待重标清单（republish.punct_stale_update）：只登记单字替换，多轮累积保留最早的 base 与 old。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "zhengli"))
import republish as rp  # noqa: E402


def test_replace_registered():
    doc, others = rp.punct_stale_update(None, {"1:1:1": "□", "1:1:2": "甲"}, {"1:1:1": "確", "1:1:2": "甲"},
                                        volume=7, base_commit="abc", base_text_version="0.3.0")
    assert others == []
    assert doc["base_commit"] == "abc" and doc["items"] == [{"anchor": "1:1:1", "old": "□", "new": "確", "commit": ""}]


def test_accumulate_keeps_earliest_and_reverts():
    first, _ = rp.punct_stale_update(None, {"1:1:1": "甲"}, {"1:1:1": "乙"}, volume=7, base_commit="a", base_text_version="0.3.0")
    second, _ = rp.punct_stale_update(first, {"1:1:1": "乙"}, {"1:1:1": "丙"}, volume=7, base_commit="b", base_text_version="0.4.0")
    assert second["base_commit"] == "a" and second["base_text_version"] == "0.3.0"
    assert second["items"][0]["old"] == "甲" and second["items"][0]["new"] == "丙"
    third, _ = rp.punct_stale_update(second, {"1:1:1": "丙"}, {"1:1:1": "甲"}, volume=7, base_commit="c", base_text_version="0.5.0")
    assert third is None            # 改回原字，清单里撤掉


def test_insert_delete_not_registered():
    doc, others = rp.punct_stale_update(None, {"1:1:1": "甲", "1:1:2": ""}, {"1:1:1": "", "1:1:2": "乙"},
                                        volume=7, base_commit="a", base_text_version="0.3.0")
    assert doc is None and len(others) == 2
