# -*- coding: utf-8 -*-
"""北行刻本（bxgb）对账：用户裁决当金标，量当下 `rare_candidates` 产物的候选命中。

与 04 卡「全书重跑后的实测」同口径：金标 = `feedback/events` 里 actor=user &
kind=confirm 的裁决；预测 = 该字位 `rare_candidates` 产物里的候选顺序。

分类内 / 类外两档报（类外 = 金标字不在 CNN `classes` 里）——这两档的
承重路不同（类内靠分类头+emb，类外只有 emb），混在一起看不出换 checkpoint 的效果。

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \
        experiments/metric_loss/reconcile_bxgb.py [--json <出口>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

WS = Path(os.environ.get("GUJI_WORKSPACE", "D:/workspace/guji-workspace/988g7gsqhd-北行日錄清乾隆道光間長塘鮑氏刊知不足齋叢書之一"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="bxgb")
    ap.add_argument("--json", default=None)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    from open_guji_cv.eval.round_check import load_verdicts

    gold = load_verdicts(a.book, WS)
    print(f"{a.tag} 裁决金标 {len(gold)} 条")
    if not gold:
        print("没有裁决，退出"); return 1

    # 产物：products/<book>/rare_candidates/p####.json
    prod = WS / "products" / a.book / "rare_candidates"
    cand: dict[str, list[str]] = {}
    for f in sorted(prod.glob("p*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for key, rec in _iter_cells(d):
            chars = _cand_chars(rec)
            if chars:
                cand[key] = chars
    print(f"{a.tag} 产物候选字位 {len(cand)}")

    import torch
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT
    classes = set(torch.load(DEFAULT_CKPT, map_location="cpu",
                             weights_only=False)["classes"])
    print(f"{a.tag} checkpoint {DEFAULT_CKPT}  类数 {len(classes)}")

    strata = {"全体": [], "类内": [], "类外": []}
    miss_key = 0
    for key, shape in gold.items():
        lst = cand.get(key)
        if lst is None:
            miss_key += 1
            continue
        rec = (shape, lst)
        strata["全体"].append(rec)
        strata["类内" if shape in classes else "类外"].append(rec)
    print(f"{a.tag} 对上 {len(strata['全体'])} 条，产物里找不到字位 {miss_key} 条\n")

    res = {}
    print(f"{a.tag} {'档':6s} {'n':>5s} {'top-1':>8s} {'top-5':>8s} {'top-10':>8s}")
    for nm, rows in strata.items():
        if not rows:
            continue
        n = len(rows)
        t = {k: sum(1 for s, l in rows if s in l[:k]) / n for k in (1, 5, 10)}
        res[nm] = {"n": n, **{f"top{k}": t[k] for k in (1, 5, 10)}}
        print(f"{a.tag} {nm:6s} {n:5d} {t[1]:7.1%} {t[5]:7.1%} {t[10]:7.1%}")

    if a.json:
        Path(a.json).write_text(json.dumps(
            {"ckpt": str(DEFAULT_CKPT), "result": res}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print("\n→", a.json)
    return 0


def _iter_cells(d):
    """产物结构（2026-09-17 实测）：

        {"rare_candidates": {"columns": [{"col": 1, "ok": true,
            "chars": [{"id": "bxgb:20:1:1", "slot": 1,
                       "candidates": [{"char": "錫", "font": "emb", "score": 0.978}, ...]}]}]}}

    字位键就是 `chars[].id`（`<book>:<page>:<col>:<slot>`），与
    `load_verdicts` 的 `target.key` 同一套。
    """
    rc = d.get("rare_candidates") or {}
    for col in rc.get("columns") or []:
        for cell in col.get("chars") or []:
            key = cell.get("id")
            if key:
                yield key, cell


def _cand_chars(rec) -> list[str]:
    return [it["char"] for it in (rec.get("candidates") or [])
            if isinstance(it, dict) and it.get("char")]


if __name__ == "__main__":
    raise SystemExit(main())
