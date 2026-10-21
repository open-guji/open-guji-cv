# -*- coding: utf-8 -*-
"""scripts/zhengli/wave_report.py（每波归因报告，GUJI-670）：自造 seed_admit／align_ref，不碰真书。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "wave_report.py"
spec = importlib.util.spec_from_file_location("zhengli_wave_report", SCRIPT)
wr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wr)


def _book(root: Path, book: str, cells: list[tuple[str, str, list[str], str | None, str]]):
    """cells: (格号, 字, doubts, 整理本字, align_op)。"""
    seed = {"columns": [{"chars": [{"id": k, "admit": False, "char": ch, "doubts": d, "evidence": {}}
                                   for k, ch, d, _, _ in cells]}]}
    align = {"anchored": True, "coord": [], "coord_fallback": {},
             "chars": [{"id": k, "align_char": r, "align_op": op} for k, _, _, r, op in cells if r]}
    for step, doc in (("seed_admit", seed), ("align_ref", align)):
        f = root / book / step / "p0001.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({step: doc}, ensure_ascii=False), encoding="utf-8")


def test_wave_report_counts_owners_delta(tmp_path):
    w0, w1 = tmp_path / "w0", tmp_path / "w1"
    _book(w0, "va", [("va:1:1:1", "已", [], "已", "equal"), ("va:1:1:2", "巻", ["ref_lib_variant"], "卷", "equal"),
                     ("va:1:1:3", "巻", ["ref_lib_variant"], "卷", "equal"), ("va:1:1:4", "甲", ["occluded"], "甲", "equal")])
    _book(w1, "va", [("va:1:1:2", "巻", ["ref_lib_variant"], "卷", "equal"), ("va:1:1:4", "甲", ["occluded"], "甲", "equal"),
                     ("va:1:1:5", "甲", [], None, "equal")])
    s0, s1 = wr.wave_stats(w0, ["va"]), wr.wave_stats(w1, ["va"])
    assert s0["va"]["by_cause"] == {"B": 2, "C": 1, "D": 1} and s1["va"]["n"] == 3
    own = wr.owners(s0)
    assert own["M7"]["n"] == 3 and own["M7"]["top"][0] == ("B 巻/卷", 2)
    d = wr.delta(s0, s1)
    assert d["by_code"] == {"C": {"va": -1}, "B": {"va": -1}, "A9": {"va": 1}}
    assert (d["gone_cells"], d["new_cells"], d["n_prev"], d["n_cur"]) == (2, 1, 4, 3)
    bench = {"variants": {"A": {"review_rate_body": 0.01}, "B": {"review_rate_body": 0.008, "review_rate_diff": -0.002,
                                                               "new_wrong": [], "fixed_wrong": ["x"]}}}
    md = wr.render_md("1", s1, s0, [bench], str(w1))
    assert "| B | 码位异体 | M7 | 1 | 1 | 33% |" in md and "4 → 3（-1）" in md and "| B | 1.000% → 0.800% | -0.200% | 0 | 1 |" in md
    assert "D（" not in md.split("## 四、下一波目标")[1]          # 遮挡不修，不列目标


def test_kind_groups_seg_details():
    assert wr._kind("A3", "格数少于整理本字数（6 < 11）") == "格数少于整理本字数"
    assert wr._kind("A3", "格与整理本 9 字对不上（格数/类型/几何）") == "格与整理本 N 字对不上"
    assert wr._kind("B", "巻/卷") == "巻/卷"
