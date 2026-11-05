"""待裁清单（`feedback/llm_queue`）：产物里记下的问题导出去重，对话的答案写回裁定库后管线命中缓存。数据自造。"""
import json

from open_guji_cv.feedback import llm_queue as Q
from open_guji_cv.feedback.rulings import RulingCache, RulingStore
from open_guji_cv.groups import ctx_llm


def _page(cells):
    return {"seed_admit": {"columns": [{"col": 1, "chars": cells}]}}


def _cell(cid, l, r, why=Q.PENDING):
    return {"id": cid, "char": "日", "evidence": {"group": {"id": "ry", "solvers": [
        {"solver": "ctx", "char": None, "why": why, "ask": {"ver": "ry-l2-2", "l": l, "r": r}}]}}}


def test_export_dedup_and_import_roundtrip(tmp_path, monkeypatch):
    pages = tmp_path / "vol20" / "seed_admit"
    pages.mkdir(parents=True)
    (pages / "p0001.json").write_text(json.dumps(_page([_cell("vol20:1:1:1", "子", "學而"), _cell("vol20:1:1:2", "子", "學而"),
                                                          _cell("vol20:1:1:3", "甲", "乙", why="abstain:low_conf")]),
                                                 ensure_ascii=False), encoding="utf-8")
    rows = Q.collect(sorted(pages.glob("p*.json")))
    assert len(rows) == 1 and rows[0]["cells"] == ["vol20:1:1:1", "vol20:1:1:2"] and rows[0]["members"] == ["日", "曰"]
    ans = [{**rows[0], "char": "曰", "conf": "high", "why": "引語"}, {**rows[0], "char": "天", "conf": "high", "why": "x"}]
    st = RulingStore(tmp_path / "fb")
    assert Q.import_answers(ans, model="session", batch="llm-session-t", store=st) == {"written": 1, "skipped": 1}
    monkeypatch.delenv(ctx_llm.ENV_ONLINE, raising=False)
    v = ctx_llm.judge("ry", "提示詞", "ry-l2-2", "子", "學而", frozenset("日曰"), cache=RulingCache(RulingStore(tmp_path / "fb")))
    assert v.char == "曰" and v.extra.get("cached")
