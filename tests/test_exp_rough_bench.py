# -*- coding: utf-8 -*-
"""粗校基准（`open_guji_cv/exp/rough_bench.py`、`scripts/eval_rough_bench.py`，GUJI-669）。

产物与事件全部自造（seed_admit／border_detect_gate 的形状），不跑管线、不联网：测选页、标签冻结与
回读、看图标签的「现行字＝当时显示字」过滤、人裁走绑定表、两个数的算法、回归门、按册给页。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from open_guji_cv.exp import config as EC
from open_guji_cv.exp import labels as LB
from open_guji_cv.exp import rough_bench as RB
from open_guji_cv.exp import runner as RN

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval_rough_bench.py"
spec = importlib.util.spec_from_file_location("eval_rough_bench", SCRIPT)
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def _seed(root: Path, book: str, cells: dict[str, tuple[str, str]], types: dict[int, str]):
    """cells: 格号 → (状态 admit/review/human, 字)；types: 页 → 页型。"""
    by_page: dict[int, list] = {}
    for k, (st, ch) in cells.items():
        by_page.setdefault(int(k.split(":")[1]), []).append(
            {"id": k, "char": ch, "admit": st in ("admit", "human"), "channel": "match_ref",
             "provenance": "human" if st == "human" else "auto", "doubts": []})
    for p, t in types.items():
        chars = by_page.get(p, [])
        f = root / book / "seed_admit" / f"p{p:04d}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"seed_admit": {"columns": [{"chars": chars}]}}, ensure_ascii=False), encoding="utf-8")
        g = root / book / "border_detect_gate" / f"p{p:04d}.json"
        g.parent.mkdir(parents=True, exist_ok=True)
        g.write_text(json.dumps({"border_detect_gate_manifest": {"page_type": t}}), encoding="utf-8")


def _lab(cell, origin="human", sel="picked", **kw):
    return {"cell": cell, "origin": origin, "selection": sel, "event": f"e-{cell}", **kw}


def test_pick_pages_hard_weighted_random_seeded(tmp_path):
    types = {p: "body" for p in range(1, 21)} | {21: "toc"}
    _seed(tmp_path, "vb", {f"vb:{p}:1:1": ("admit", "甲") for p in types}, types)
    labels = [_lab("vb:3:1:1"), _lab("vb:5:1:1", "vision"), _lab("vb:5:1:2", "vision"),
              _lab("vb:21:1:1"), _lab("vb:9:1:1", "vision")]
    pp = RB.pick_pages(tmp_path, ["vb"], labels, n_random=4, n_hard=2, seed=0)["vb"]
    assert pp["hard"] == [3, 5]                       # 人裁 3 分 > 看图 2 格；目录页不进
    assert len(pp["random"]) == 4 and not set(pp["random"]) & {3, 5, 21}
    assert pp == RB.pick_pages(tmp_path, ["vb"], labels, n_random=4, n_hard=2, seed=0)["vb"]


def test_gold_items_roundtrip_through_load_gold(tmp_path):
    labels = [_lab("vb:3:1:1", char="甲", bbox=[1, 2, 3, 4]), _lab("vb:3:1:2a", "vision", "random", char="乙"),
              _lab("vb:3:1:3", "vision", wrong=["丙"]), _lab("vb:3:1:4", defect=True), _lab("vb:7:1:1", char="丁")]
    items = RB.gold_items(labels, {"vb": {"random": [], "hard": [3]}}, {"vb": "pk1"}, "t")
    assert [i["id"] for i in items] == ["vb:3:1:1", "vb:3:1:2a", "vb:3:1:3", "vb:3:1:4"]   # p7 不在选中页
    assert items[0]["anchor"]["bbox"] == [1, 2, 3, 4] and items[0]["pipeline_version"] == "pk1"
    f = tmp_path / "items.jsonl"
    f.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    got = {x.cell: x for x in LB.load_gold({"source": "gold", "path": str(f)}, ["vb"])}
    assert got["vb:3:1:1"].truth == "甲" and got["vb:3:1:1"].selection == LB.PICKED
    assert got["vb:3:1:2a"].truth == "乙" and got["vb:3:1:2a"].selection == LB.RANDOM   # 出口抽样
    assert got["vb:3:1:3"].wrong == {"丙"} and got["vb:3:1:4"].defect


def test_vision_labels_keep_only_same_char(tmp_path):
    _seed(tmp_path, "vb", {"vb:1:1:1": ("admit", "甲"), "vb:1:1:2": ("admit", "乙"), "vb:1:1:3": ("admit", "日")},
          {1: "body"})
    rows = [("vb:1:1:1", {"v": "ok", "shown": "甲", "note": "[S8] 抽样"}),
            ("vb:1:1:2", {"v": "ok", "shown": "丙"}),                       # 现行字变了：可能已不是同一格
            ("vb:1:1:3", {"v": "wrong", "shown": "日", "char": "曰"}),
            ("vb:1:1:3", {"v": "unsure", "shown": "日"})]                  # 后到的 unsure 盖掉，不当标签
    f = tmp_path / "vision.jsonl"
    f.write_text("".join(json.dumps({"id": f"v{i}", "target": {"unit": "cell", "book": "vb", "key": k},
                                     "payload": p, "ts": f"2026-10-0{i + 1}"}, ensure_ascii=False) + "\n"
                         for i, (k, p) in enumerate(rows)), encoding="utf-8")
    got = {x["cell"]: x for x in RB.vision_labels(tmp_path, ["vb"], [f])}
    assert list(got) == ["vb:1:1:1"] and got["vb:1:1:1"]["selection"] == "random"
    rows[3] = ("vb:1:1:9", {"v": "ok", "shown": "甲"})
    f.write_text("".join(json.dumps({"id": f"v{i}", "target": {"unit": "cell", "book": "vb", "key": k},
                                     "payload": p, "ts": f"2026-10-0{i + 1}"}, ensure_ascii=False) + "\n"
                         for i, (k, p) in enumerate(rows)), encoding="utf-8")
    got = {x["cell"]: x for x in RB.vision_labels(tmp_path, ["vb"], [f])}
    assert got["vb:1:1:3"]["char"] == "曰" and got["vb:1:1:1"]["char"] == "甲" and "vb:1:1:2" not in got


def test_human_labels_use_bindings(tmp_path, monkeypatch):
    def e(i, key, payload, ts):
        return SimpleNamespace(id=f"ev{i}", kind="confirm", ts=ts, batch="H-x", seq=i, payload=payload,
                               target=SimpleNamespace(unit="cell", key=key, step="seed_admit", anchor={"bbox": [0, 0, 1, 1]}))
    evs = [e(1, "vb:2:1:1", {"v": "confirm", "shape": "甲"}, "1"), e(2, "vb:2:1:2", {"v": "seg_defect"}, "2"),
           e(3, "vb:2:1:3", {"v": "confirm", "shape": "乙"}, "3"), e(4, "zz:2:1:1", {"v": "confirm", "shape": "丙"}, "4")]
    import open_guji_cv.feedback.bindings as BD
    import open_guji_cv.feedback.events as EV
    monkeypatch.setattr(EV, "iter_events_readonly", lambda log: iter(evs))
    monkeypatch.setattr(EV, "counts_as_human", lambda ev: True)
    monkeypatch.setattr(EV, "EventLog", lambda: None)
    status = {"ev1": ("rebound", "vb:2:1:2"), "ev2": ("valid", "vb:2:1:9"), "ev3": ("review", "vb:2:1:3")}
    monkeypatch.setattr(BD, "compute_page", lambda book, page, events, **kw: [
        {"event": x.id, "status": status[x.id][0], "bound": status[x.id][1]} for x in events])
    got = {x["cell"]: x for x in RB.human_labels(tmp_path, ["vb"])}
    assert got["vb:2:1:2"]["char"] == "甲" and got["vb:2:1:2"]["from_key"] == "vb:2:1:1"   # 改绑到新格号
    assert got["vb:2:1:9"]["defect"] and "vb:2:1:3" not in got and len(got) == 2         # review 不收


def _exp(tmp_path):
    edir = tmp_path / "exps" / "rb"
    types = {1: "body", 2: "body", 3: "toc"}
    base = {"vb:1:1:1": ("admit", "甲"), "vb:1:1:2": ("review", "乙"), "vb:1:1:3": ("admit", "曰"),
            "vb:2:1:1": ("admit", "丙"), "vb:3:1:1": ("review", "丁")}
    var = dict(base) | {"vb:1:1:2": ("admit", "己"), "vb:1:1:3": ("admit", "日")}
    _seed(edir / "A", "vb", base, types)
    _seed(edir / "B", "vb", var, types)
    _seed(edir / RN.UPSTREAM, "vb", {}, types)
    items = RB.gold_items([_lab("vb:1:1:1", char="甲"), _lab("vb:1:1:2", char="已"), _lab("vb:1:1:3", char="日")],
                          {"vb": {"random": [1], "hard": []}}, {"vb": "pk"}, "t")
    f = tmp_path / "items.jsonl"
    f.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    cfg = EC.from_dict({"name": "rb", "books": ["vb"], "variants": {"B": {}},
                        "labels": [{"source": "gold", "path": str(f)}]})
    return edir, cfg


def test_summarize_two_numbers(tmp_path):
    edir, cfg = _exp(tmp_path)
    res = RB.summarize(edir, cfg, ["A", "B"])
    a, b = res["variants"]["A"], res["variants"]["B"]
    assert (a["cells_body"], a["review_body"], b["review_body"]) == (4, 1, 0)        # 目录页不算
    assert a["wrong_cells"] == ["vb:1:1:3"] and b["wrong_cells"] == ["vb:1:1:2"]
    assert b["new_wrong"] == ["vb:1:1:2"] and b["fixed_wrong"] == ["vb:1:1:3"] and not b["passed"]
    assert b["review_rate_diff"] == -0.25
    assert ev.regressions(res, None) == ["B 新增错放 1 格：vb:1:1:2"]
    only_a = RB.summarize(edir, cfg, ["A"])
    ref = {"variants": {"A": dict(a, review_rate_body=0.25, wrong_admits=0, wrong_cells=[])}}
    assert ev.regressions(only_a, ref) == ["有标签的错放 0 → 1（新的：vb:1:1:3）"]
    assert ev.regressions(only_a, {"variants": {"A": dict(a, review_rate_body=0.2)}}) == ["正文送审率 20.0000% → 25.0000%"]


def test_exp_config_per_book_pages(tmp_path):
    bench = {"books": ["vb", "vc"], "pages": {"vb": {"random": [4, 2], "hard": [2, 9]}, "vc": {"random": [1], "hard": []}},
             "labels": "items.jsonl", "guardrails": [{"metric": "flips.right_to_wrong", "op": "==", "value": 0}]}
    cfg = RB.exp_config(bench, tmp_path, {}, name="x")
    assert cfg.pages == {"vb": [2, 4, 9], "vc": [1]} and [v.name for v in cfg.variants] == ["A", "B"]
    assert cfg.labels[0]["path"].endswith("items.jsonl")
    snap = tmp_path / "snap"
    for p in (1, 2, 4, 5):
        (snap / "vb" / "align_ref").mkdir(parents=True, exist_ok=True)
        (snap / "vb" / "align_ref" / f"p{p:04d}.json").write_text("{}", encoding="utf-8")
    pl = SimpleNamespace(steps=["align_ref", "seed_admit"])
    assert RN.select_pages(cfg, snap, "vb", pl, ["seed_admit"], book_spec=SimpleNamespace(
        resolve_pages=lambda sel: sorted(sel))) == [2, 4]
    assert RN.select_pages(cfg, snap, "vd", pl, ["seed_admit"]) == []                 # 没点名的册 = all


def test_bench_yaml_written(tmp_path, monkeypatch):
    monkeypatch.setattr(RB, "human_labels", lambda snap, books: [_lab("vb:1:1:1", char="甲")])
    monkeypatch.setattr(RB, "vision_labels", lambda snap, books, files: [_lab("vb:1:1:1", "vision", char="乙")])
    _seed(tmp_path / "snap", "vb", {"vb:1:1:1": ("admit", "甲"), "vb:2:1:1": ("admit", "乙")}, {1: "body", 2: "body"})
    res = RB.build(tmp_path / "snap", tmp_path / "out", {"vb": "pk"}, books=["vb"], n_random=1, n_hard=1)
    b = yaml.safe_load((tmp_path / "out" / RB.BENCH_YAML).read_text(encoding="utf-8"))
    assert b["pages"] == {"vb": {"random": [2], "hard": [1]}} and b["snapshot_packs"] == {"vb": "pk"}
    assert res["items"] == 1 and res["conflicts"] == [{"cell": "vb:1:1:1", "human": "甲", "vision": "乙"}]


def test_drifted_labels_not_scored(tmp_path, monkeypatch):
    edir, cfg = _exp(tmp_path)
    boxes = {"snap": {"vb:1:1:2": [0, 0, 10, 10], "vb:1:1:3": [0, 10, 10, 20]},
             "A": {"vb:1:1:2": [0, 0, 10, 10], "vb:1:1:3": [0, 10, 10, 20]},
             "B": {"vb:1:1:2": [0, 5, 10, 15], "vb:1:1:3": [0, 10, 10, 20]}}       # B 重切：1:1:2 挪了半格
    monkeypatch.setattr(RB, "cell_boxes", lambda root, keys: boxes[Path(root).name])
    res = RB.summarize(edir, cfg, ["A", "B"], snapshot=tmp_path / "snap")
    b = res["variants"]["B"]
    assert b["label_drift"] == 1 and b["wrong_cells"] == [] and b["new_wrong"] == []
    assert b["fixed_wrong"] == ["vb:1:1:3"] and res["variants"]["A"]["label_drift"] == 0
