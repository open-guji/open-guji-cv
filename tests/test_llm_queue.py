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


def test_vis_pending_recorded_exported_and_cached(tmp_path, monkeypatch):
    """看图判（vis_llm）：管线不在线问 → trail 记 ask（版本含字块哈希）→ 导出带 vis 标记 → 答案写回后命中缓存。"""
    from types import SimpleNamespace

    import numpy as np

    from open_guji_cv.groups import vis_llm
    from open_guji_cv.groups.flow import FlowConfig, _vis_try
    monkeypatch.delenv(ctx_llm.ENV_ONLINE, raising=False)
    st = RulingStore(tmp_path / "fb")
    cfg = FlowConfig(groups=("zy", "yz"), vis_model="m", vis_cache=RulingCache(st))
    r = SimpleNamespace(id="vol01:1:1:1")
    patch = lambda cid: np.zeros((20, 20), np.uint8)       # noqa: E731
    ch, item = _vis_try("zy", r, [], "千", cfg, lambda c: c, patch, "左", "右")
    assert ch is None and item["why"] == Q.PENDING and item["ask"]["ver"].startswith("vis1:")
    page = {"seed_admit": {"columns": [{"col": 1, "chars": [{"id": r.id, "char": "干", "evidence": {"group": {"id": "zy", "solvers": [item]}}}]}]}}
    f = tmp_path / "p0001.json"
    f.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
    rows = Q.collect([f])
    assert len(rows) == 1 and rows[0]["vis"] is True and rows[0]["cells"] == [r.id]
    assert Q.import_answers([{**rows[0], "char": "千", "conf": "high", "why": "刻形"}], model="session", store=st) == {"written": 1, "skipped": 0}
    ch, item = _vis_try("zy", r, [{"solver": "ids", "char": "千"}], "千", cfg, lambda c: c, patch, "左", "右")
    assert ch == "千" and item["cached"] is True
