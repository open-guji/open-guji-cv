# -*- coding: utf-8 -*-
"""`guji audit admitted|jys` 的清单逻辑（overview#413 C2）：tmp 里现造对勘 JSON 与导出文件。"""
from __future__ import annotations

import json

from open_guji_cv.ops import audit as A


def _diff(id_, char, ref, kind, witness="W1", admit=True, human=False, grade="", channel="match_ref"):
    p, c, s = id_.split(":")[1:4]
    return {"id": id_, "page": int(p), "col": int(c), "slot": int(s), "kind": kind, "char": char, "ref": ref,
            "witness": witness, "admit": admit, "human": human, "grade": grade, "channel": channel,
            "hyp_ctx": f"甲【{char}】乙"}


def test_admitted_tiers(tmp_path):
    diffs = [
        _diff("v:1:1:1", "未", "末", "sub.other"),                         # 认字差异
        _diff("v:1:1:1", "未", "末", "sub.other", witness="W2"),           # 同格另一证人，合并
        _diff("v:1:1:2", "卽", "即", "variant.to_orthodox"),              # 异体
        _diff("v:1:1:3", "㫖", "旨", "sub.other", grade="systematic"),     # 系统性
        _diff("v:1:1:4", "己", "已", "sub.other", human=True),            # 人裁过 → 不列
        _diff("v:1:1:5", "己", "已", "sub.other", admit=False),           # 未放行 → 不列
    ]
    col = tmp_path / "collation_x.json"
    col.write_text(json.dumps({"book": "v", "diffs": diffs}, ensure_ascii=False), encoding="utf-8")
    res = A.admitted(col)
    assert (res["n"], res["n_non_systematic"], res["n_variant"], res["n_systematic"]) == (3, 1, 1, 1)
    real = [r for r in res["rows"] if r["tier"] == "real"][0]
    assert real["witness"] == {"W1": "末", "W2": "末"}
    md = A.admitted_md(res)
    assert "`v:1:1:1`" in md and "卽 ← 证人 即：1 格" in md and "v:1:1:4" not in md
    assert A.latest_collation(tmp_path) == col


def test_jys_list_and_muse_input(tmp_path):
    (tmp_path / "009.lines.md").write_text("<!-- p1 -->\n甲子己未治人則人而已\n", encoding="utf-8")
    text = "甲子己未治人則人而已"
    cells = [{"a": f"1:1:{i + 1}", "o": i, "c": ch} for i, ch in enumerate(text)]
    (tmp_path / "009.pages.json").write_text(json.dumps({"pages": [{"cells": cells}]}, ensure_ascii=False),
                                             encoding="utf-8")
    proof = {"cells": [{"a": "1:1:3", "review": "auto"}, {"a": "1:1:10", "review": "human"}]}
    (tmp_path / "009.proof.json").write_text(json.dumps(proof), encoding="utf-8")
    res = A.jys(tmp_path, width=3, book="v")
    assert res["n"] == 2 and res["by_char"] == {"己": 1, "已": 1} and res["n_human"] == 1
    r0 = res["rows"][0]
    assert (r0["id"], r0["left"], r0["right"]) == ("v:1:1:3", "甲子", "未治人")
    lines = A.jys_muse_jsonl(res).splitlines()
    assert len(lines) == 1                                   # 人裁过的不再交 muse
    assert json.loads(lines[0]) == {"id": "v:1:1:3", "left": "甲子", "right": "未治人"}  # 不含现字、证人
    assert "| `v:1:1:10` | 已 | human |" in A.jys_md(res, "v")


def test_review_count(tmp_path):
    ev = tmp_path / "events"
    ev.mkdir()
    def e(key, ts, anchor=True, book="v", actor="user", v="confirm"):
        t = {"book": book, "key": key}
        if anchor:
            t["anchor"] = {"product_key": {"step": "seed_admit"}}
        return json.dumps({"actor": actor, "kind": "confirm", "payload": {"v": v}, "target": t, "ts": ts})
    (ev / "b1.jsonl").write_text("\n".join([
        e("v:1:1:1", "2026-10-06T09:00:00Z"),
        e("v:1:1:1", "2026-10-06T09:01:00Z"),                 # 同格两次
        e("v:1:1:2", "2026-10-06T09:02:00Z", anchor=False),   # 没锚点
        e("v:1:1:3", "2026-10-05T09:00:00Z"),                 # 早于 since
        e("w:1:1:1", "2026-10-06T09:00:00Z", book="w"),       # 别的册
    ]) + "\n", encoding="utf-8")
    res = A.review_count(ev, "v", "2026-10-06T00:00", expect=["v:1:1:1", "v:1:1:9"])
    assert (res["n_events"], res["n_cells"]) == (3, 2)
    assert res["repeated"] == ["v:1:1:1"] and res["no_anchor"] == ["v:1:1:2"]
    assert res["missing"] == ["v:1:1:9"] and res["extra"] == ["v:1:1:2"]


def test_review_sheet_sections():
    md = A.review_sheet("v", {"ji_yi_si": 3, "other": 1},
                        [{"id": "v:9:8:4", "shape": "困", "excluded": False}],
                        [{"id": "v:22:4:20", "shape": "璹", "char": "邢", "kind": "main"},
                         {"id": "v:1:1:1", "shape": "已", "char": "巳", "kind": "jys"}])
    assert "共 6 格" in md                                     # 4 待审 + 1 失效老裁 + 1 正文不一致（己已巳族不列）
    assert "| 己已巳 | 3 |" in md and "| `v:9:8:4` | 困 |" in md and "| `v:22:4:20` | 璹 | 邢 |" in md
    assert "v:1:1:1" not in md
    assert md.count("不审的默认") >= 4
