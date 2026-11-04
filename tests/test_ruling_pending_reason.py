"""文意裁定事件带待审原因 pending_reason（不给记 unknown）。"""
from open_guji_cv.feedback.rulings import RulingCache, RulingStore


def test_put_records_pending_reason(tmp_path):
    st = RulingStore(tmp_path)
    p = st.put("日曰", "v1", "子", "學而", char="曰", conf="high", why="引語", model="m", cell="vol01:1:1:1",
               pending_reason="group_abstain")
    assert p["pending_reason"] == "group_abstain"
    ev = [e for e in RulingStore(tmp_path).log.iter_all(raw=True)]
    assert ev and ev[0].payload["pending_reason"] == "group_abstain"


def test_missing_pending_reason_is_unknown(tmp_path):
    st = RulingStore(tmp_path, persist=False)
    RulingCache(st).store("日曰", "v1", "m", "子", "學而", {"char": "曰", "conf": "high", "why": ""})
    assert st.get("日曰", "v1", "子", "學而")["pending_reason"] == "unknown"
