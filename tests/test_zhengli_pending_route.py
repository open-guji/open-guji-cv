# -*- coding: utf-8 -*-
"""scripts/zhengli/pending_route.py（M10·D1 待审分流，GUJI-688）：自造数据，不碰真书。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PR_PATH = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "pending_route.py"
spec = importlib.util.spec_from_file_location("pending_route_under_test", PR_PATH)
pr = importlib.util.module_from_spec(spec)
sys.modules["pending_route_under_test"] = pr
spec.loader.exec_module(pr)


def ev(cell, v, ts, *, kind="confirm", shape=None, quality=None, source=None, book="vol01"):
    pl = {"v": v}
    if shape is not None:
        pl["shape"] = shape
    if quality is not None:
        pl["quality"] = quality
    if source is not None:
        pl["source"] = source
    return {"id": f"e-{cell}-{ts}", "ts": ts, "kind": kind, "actor": "user", "payload": pl,
            "target": {"step": "seed_admit", "unit": "cell", "key": f"{book}:{cell}", "book": book}}


def test_deciding_kinds():
    assert pr.deciding(ev("1:1:1", "confirm", "t", shape="臼")) == "char"
    assert pr.deciding(ev("1:1:1", "confirm", "t")) is None                       # 没给字
    assert pr.deciding(ev("1:1:1", "not_a_char", "t")) == "not_a_char"
    assert pr.deciding(ev("1:1:1", "seg_defect", "t", quality="truncated")) == "seg_defect"
    assert pr.deciding(ev("1:1:1", "seg_defect", "t", quality="clean")) is None   # 切分没问题≠定字
    assert pr.deciding(ev("1:1:1", "confirm", "t", shape="臼", source="vision")) is None
    assert pr.deciding(ev("1:1:1", None, "t", kind="cutline")) is None


def test_route_vol01_like(tmp_path):
    pending = {"rev": "001-r2", "cv_version": None, "cv_commit": "x", "cells": [
        {"cell": "9:7:17", "review": "pending", "cls": "near_form", "why": ["near_form"]},
        {"cell": "10:7:10", "review": "pending", "cls": "lib_miss", "why": ["ctx_garble_shape"]},
        {"cell": "10:7:16", "review": "pending", "cls": "replace_align", "why": ["replace_align"]},
        {"cell": "53:2:1", "review": "pending", "cls": "near_form", "why": ["near_form"], "stale": {"c": "定", "ts": "2026-10-10T00:00:00Z"}},
        {"cell": "196:1:4", "review": "pending", "cls": "other", "why": ["none"]},
    ]}
    events = [
        ev("10:7:10", "seg_defect", "2026-10-16T17:57:54Z", quality="truncated"),     # 已裁 → 扣掉
        ev("10:7:16", "seg_defect", "2026-09-12T04:10:17Z", quality="clean"),         # clean 不算
        ev("9:7:17", "confirm", "2026-10-18T06:07:55Z", shape="臼"),                  # 截止之后 → 不扣
        ev("53:2:1", "confirm", "2026-10-01T00:00:00Z", shape="定"),                  # 早于 stale.ts → 不扣
        ev("1:1:1", "confirm", "2026-10-01T00:00:00Z", shape="甲", book="vol02"),     # 别册
    ]
    p = tmp_path / "001.pending.json"
    p.write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8")
    e = tmp_path / "events"
    e.mkdir()
    (e / "b.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in events), encoding="utf-8")
    out = tmp_path / "out"
    rc = pr.main(["--pending", str(p), "--book", "vol01", "--events", str(e), "--as-of", "2026-10-17T20:00:00Z",
                  "--team-pages", "196", "--db-rev", "12063", "--out", str(out)])
    assert rc == 0
    pub = json.loads((out / "001.pending.json").read_text(encoding="utf-8"))
    team = json.loads((out / "001.team.pending.json").read_text(encoding="utf-8"))
    assert [c["cell"] for c in pub["cells"]] == ["9:7:17", "10:7:16", "53:2:1"]
    assert [c["cell"] for c in team["cells"]] == ["196:1:4"]
    assert {c["audience"] for c in pub["cells"]} == {"public"} and team["cells"][0]["audience"] == "team"
    assert pub["rev"] == "001-r2" and pub["based_on_db_rev"] == "12063"


def test_reflow_groups_and_hold(tmp_path):
    cells = [{"cell": f"5:1:{i}", "review": "pending", "cls": "occluded", "why": ["occluded"]} for i in range(1, 4)]
    cells += [{"cell": f"6:1:{i}", "review": "pending", "cls": "other", "why": ["none"]} for i in range(1, 5)]
    res = pr.route({"cells": cells}, {}, set(), reflow_min=3, reflow_hold=False)
    assert [c["cell"] for c in res["reflow"]] == ["5:1:1", "5:1:2", "5:1:3"]     # other/none 不算一个原因
    assert res["stats"]["public"] == 7
    held = pr.route({"cells": cells}, {}, set(), reflow_min=3, reflow_hold=True)
    assert held["stats"]["public"] == 4 and held["stats"]["reflow"] == 3


def test_parse_pages():
    assert pr.parse_pages("89-91,196，200") == {89, 90, 91, 196, 200}
    assert pr.parse_pages("") == set()


def test_keep_list_not_deducted(tmp_path):
    """人裁绑到了别的格（重切后格号顺移）：--keep 名单上的格不按格号扣。"""
    pending = {"rev": "004-r4", "cells": [{"cell": "216:4:9a", "review": "pending", "cls": "x", "why": ["human_unbound"]},
                                          {"cell": "216:4:10", "review": "pending", "cls": "x", "why": ["x"]}]}
    p = tmp_path / "004.pending.json"
    p.write_text(json.dumps(pending), encoding="utf-8")
    e = tmp_path / "e.jsonl"
    e.write_text("\n".join(json.dumps(ev(c, "confirm", "2026-10-01T00:00:00Z", shape="啟", book="vol04"))
                           for c in ("216:4:9a", "216:4:10")), encoding="utf-8")
    keep = tmp_path / "keep.txt"
    keep.write_text("vol04:216:4:9a\n", encoding="utf-8")
    out = tmp_path / "out"
    assert pr.main(["--pending", str(p), "--book", "vol04", "--events", str(e), "--keep", str(keep), "--out", str(out)]) == 0
    assert [c["cell"] for c in json.loads((out / "004.pending.json").read_text(encoding="utf-8"))["cells"]] == ["216:4:9a"]


def test_recheck_cells_not_deducted(tmp_path):
    """复审格（pending_list --recheck 放回来的）本来就是要推翻或重定的：已有人裁也不扣。"""
    pending = {"rev": "006-r5", "cells": [{"cell": "83:5:9", "review": "pending", "recheck": True, "note": "旧裁 山，新票 由"},
                                          {"cell": "83:5:10", "review": "pending"}]}
    p = tmp_path / "006.pending.json"
    p.write_text(json.dumps(pending), encoding="utf-8")
    e = tmp_path / "e.jsonl"
    e.write_text("\n".join(json.dumps(ev(c, "confirm", "2026-10-01T00:00:00Z", shape="山", book="vol06"))
                           for c in ("83:5:9", "83:5:10")), encoding="utf-8")
    out = tmp_path / "out"
    assert pr.main(["--pending", str(p), "--book", "vol06", "--events", str(e), "--out", str(out)]) == 0
    cells = json.loads((out / "006.pending.json").read_text(encoding="utf-8"))["cells"]
    assert [c["cell"] for c in cells] == ["83:5:9"] and cells[0]["note"] == "旧裁 山，新票 由"
