# -*- coding: utf-8 -*-
"""字形库「待纳入」（overview#176，2026-09-28）：候选清单读取、按字分组、裁决回读。

自造清单与事件，全部落 tmp；库用假的 `char_detail`，不碰任何真库。
直调端点函数（同 test_events_autoconsume），不起 TestClient。
"""
from __future__ import annotations

import json

import pytest

from open_guji_cv.console.auth import Identity
from open_guji_cv.feedback import candidates as cand

_ID = Identity(email="cand-test@example.com", role="reviewer", tier="reviewer")

ROWS = [
    {"_meta": {"title": "H#62 形近薄刻例", "source": "H#62"}},
    {"cell_id": "vol03:19:6:18", "char": "仕", "evidence": {"source": "H#62", "margin": 1.0}},
    {"cell_id": "vol04:20:9:10", "char": "河", "evidence": {"source": "H#62", "margin": 0.79},
     "ref_instances": ["v2:vol01:9:1:1"]},
    {"cell_id": "vol04:28:3:18a", "char": "河", "evidence": {"source": "H#62", "margin": 0.7}},
]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from open_guji_cv.console import deps
    from open_guji_cv.console.routers import feedback as fb
    from open_guji_cv.console.routers import glyph_candidates as gc

    for key in ("feedback", "batches", "dataset"):
        monkeypatch.setitem(deps._roots, key, tmp_path / key)
    for cached in ("_log", "_batches", "_gold"):
        monkeypatch.setattr(deps, cached, None)
    d = tmp_path / "feedback" / "candidates"
    d.mkdir(parents=True)
    (d / "h62.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in ROWS) + "\n",
                                 encoding="utf-8")
    # 库：假的，只认「河」；库文件本身要存在（没有库时 n_lib=None）
    db = tmp_path / "glyph.db"
    db.write_bytes(b"")
    monkeypatch.setattr("open_guji_cv.core.workspace.glyph_db_path", lambda *a, **k: db)

    def fake_detail(_db, ch):
        ex = [{"instance_id": f"v2:vol01:9:1:{i}", "provenance": "human" if i == 3 else "align",
               "duplicate": i == 4} for i in range(1, 5)] if ch == "河" else []
        return {"char": ch, "exemplars": ex}
    monkeypatch.setattr("open_guji_cv.clustering.glyph_ledger.char_detail", fake_detail)
    return gc, fb, tmp_path


def _decide(fb, rows, consume=True):
    body = {"batch": cand.batch_of("h62"), "step": cand.STEP, "unit": "cell",
            "kind": cand.KIND, "events": rows, "consume": consume}
    return fb.api_events(fb.EventsIn(**body), identity=_ID)


def test_load_list_skips_bad_rows(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text("\n".join([
        "# 注释行",
        json.dumps({"cell_id": "vol03:19:6:18", "char": "仕"}),
        json.dumps({"cell_id": "vol03:19:6:18", "char": "仕"}),      # 重复
        json.dumps({"cell_id": "bad", "char": "仕"}),                 # 格号认不出
        json.dumps({"cell_id": "vol03:1:1:1", "char": "仕士"}),       # 不是单字
        "{不是 json",
    ]), encoding="utf-8")
    meta, rows, problems = cand.load_list(p)
    assert meta == {} and [r["cell_id"] for r in rows] == ["vol03:19:6:18"]
    assert len(problems) == 4


def test_parse_cell_patch_key():
    assert cand.parse_cell("vol04:28:3:18a") == {"book": "vol04", "page": 28, "col": 3, "slot": 18,
                                                "sub": "a", "patch_key": "p0028c03s18a"}
    assert cand.parse_cell("vol04:28:3") is None


def test_list_id_rejects_path_tricks():
    with pytest.raises(ValueError):
        cand.list_path("../evil")


def test_lists_and_grouping(env):
    gc, _fb, _ = env
    ls = gc.api_candidate_lists()
    assert [x["id"] for x in ls["lists"]] == ["h62"]
    assert ls["lists"][0]["title"] == "H#62 形近薄刻例"
    assert ls["lists"][0]["tally"] == {"admit": 0, "reject": 0, "unclear": 0, "todo": 3}

    d = gc.api_candidate_list("h62")
    assert [g["char"] for g in d["groups"]] == ["仕", "河"]          # 清单首次出现顺序
    shi, he = d["groups"]
    assert shi["n_lib"] == 0 and shi["lib"] == []
    assert [c["patch_key"] for c in he["cells"]] == ["p0020c09s10", "p0028c03s18a"]
    assert he["cells"][0]["book"] == "vol04"
    # 库里同字：副本不算；点名的对照刻例排最前，其次人裁
    assert he["n_lib"] == 3
    assert [e["instance_id"] for e in he["lib"]] == ["v2:vol01:9:1:1", "v2:vol01:9:1:3", "v2:vol01:9:1:2"]
    assert he["lib"][0]["is_ref"] and not he["lib"][1]["is_ref"]


def test_missing_list_404(env):
    from fastapi import HTTPException
    gc, _fb, _ = env
    with pytest.raises(HTTPException) as e:
        gc.api_candidate_list("nope")
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        gc.api_candidate_list("..")
    assert e.value.status_code == 400


def test_decisions_roundtrip_latest_wins_and_no_library_write(env):
    gc, fb, tmp = env
    r = _decide(fb, [{"id": "vol03:19:6:18", "v": "unclear", "char": "仕", "shape": "仕", "t": 1},
                     {"id": "vol04:20:9:10", "v": "admit", "char": "河", "shape": "河", "t": 2}])
    assert r["appended"] == 2
    # 路由表不给 admit_candidate 配消费者：不进库、不写金标，只落事件
    assert not r.get("consumed") and not r.get("consume_error")
    assert not (tmp / "feedback" / "consumed" / "glyphdb_admit.jsonl").exists()
    _decide(fb, [{"id": "vol03:19:6:18", "v": "admit", "char": "仕", "shape": "仕", "t": 3}])

    d = gc.api_candidate_list("h62")
    assert d["tally"] == {"admit": 2, "reject": 0, "unclear": 0, "todo": 1}
    cells = {c["cell_id"]: c for g in d["groups"] for c in g["cells"]}
    assert cells["vol03:19:6:18"]["decision"]["v"] == "admit"          # 改判：最新一条
    assert cells["vol03:19:6:18"]["decision"]["reviewer"] == _ID.email
    assert cells["vol04:28:3:18a"]["decision"] is None

    # 事件带锚与 shape，供 H 道重放按 confirm 口径进库
    evs = fb.deps.event_log().read(cand.batch_of("h62"))
    assert all(e.kind == "admit_candidate" and e.target.unit == "cell" for e in evs)
    assert evs[1].target.book == "vol04" and evs[1].payload["shape"] == "河"


def test_unknown_verdict_ignored(env):
    gc, fb, _ = env
    _decide(fb, [{"id": "vol03:19:6:18", "v": "maybe", "char": "仕"}], consume=False)
    assert gc.api_candidate_list("h62")["tally"]["todo"] == 3
