# -*- coding: utf-8 -*-
"""用人裁结果标定 L2′ 升级门槛的**上下限**，以及「U-Net 缝何时不该进池」。

    python experiments/touch_resolve/calibrate_escalate.py [--book vol02]

数据：workspace 裁决表里这批升级切点的人裁（`cand` 指向人选中的候选 kind，或 `verdict=ok` = 直线）+ Step3 产物里
每条候选的 `dis_unet`（与 U-Net 归属的分歧最大块）。两个要标的量：

1. **下限**（现 `ESCALATE_BLOB=100`）：所选切法与 U-Net 分歧 < 下限就不升级。太低 → 白出卡（人裁下来发现
   U-Net 与现役差几像素，选谁都对）；太高 → 漏掉真错。用「人把现役切法推翻了没有」当真值：
   `flip` = 人选的 kind ≠ Step3 产物 chosen 的 kind。
2. **上限**（新）：U-Net 自己分歧大到某个程度时它整字翻边（人裁里 13 条「U-Net 整字翻边」），
   此时不该把 `unet_seam` 放进候选池（仍升级出卡给人）。用「人选没选 unet_seam」当真值。

报各门槛下的召回/白卡率，给出推荐值。产出 out/calibrate/<book>.json。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT_ROOT, jdump  # noqa: E402
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.eval.touching import SHARD  # noqa: E402
from open_guji_cv.feedback.consumers import verdict_store  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.store import ProductStore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol02")
    ap.add_argument("--since", default="2026-09-15", help="只取这天之后的人裁（这批升级切点）")
    a = ap.parse_args()
    st = ProductStore()
    # 人裁：id → 选中的 kind（cand，或 verdict=ok → straight）
    picks: dict[str, str] = {}
    for it in verdict_store().list(SHARD):
        if it.anchor.book != a.book or it.status != "active":
            continue
        ex = it.expected
        k = ex.get("cand") or ("straight" if ex.get("verdict") == "ok" else None)
        if k:
            picks[it.id] = k
    rows = []
    cache: dict[int, object] = {}
    for cid, pick in picks.items():
        _, pg, col, slot = cid.split(":")
        pg, col, slot = int(pg), int(col), int(slot)
        if pg not in cache:
            cache[pg] = st.read(a.book, "row_segment", page_key(pg), "cells")
        cells = cache[pg]
        if cells is None:
            continue
        cc = next((c for c in cells.columns if c.col == col and c.ok), None)
        if cc is None:
            continue
        cp = next((cp for cp in (cc.cut_candidates or []) if cp.slot_above == slot), None)
        if cp is None or not cp.escalate:          # 只标定升级切点
            continue
        kinds = {c.kind: c for c in cp.candidates}
        if pick not in kinds:
            continue
        chosen = cp.candidates[cp.chosen]
        u = kinds.get("unet_seam")
        rows.append({"id": cid, "pick": pick, "chosen_kind": chosen.kind,
                     "chosen_dis": chosen.dis_unet, "unet_dis": (u.dis_unet if u else None),
                     "has_unet": u is not None,
                     "flip": pick != chosen.kind,
                     "pick_unet": pick == "unet_seam"})
    n = len(rows)
    print(f"{a.book}：升级切点里有人裁的 {n} 条；人推翻现役的 {sum(r['flip'] for r in rows)}，"
          f"选 U-Net 缝的 {sum(r['pick_unet'] for r in rows)}")

    # ── 下限：所选切法与 U-Net 的分歧块（= 升级判据本身） ──
    print(f"\n【下限】现役切法 dis_unet ≥ T 才升级。真值 = 人推翻了现役（flip）")
    print(f"  {'T':>5s} {'升级数':>6s} {'其中 flip':>9s} {'召回':>6s} {'白卡率':>7s}")
    flips = sum(r["flip"] for r in rows)
    best = None
    for T in (20, 40, 60, 80, 100, 120, 150, 200):
        esc = [r for r in rows if (r["chosen_dis"] or 0) >= T]
        hit = sum(r["flip"] for r in esc)
        rec = hit / max(1, flips)
        waste = 1 - hit / max(1, len(esc))
        print(f"  {T:5d} {len(esc):6d} {hit:9d} {rec:6.1%} {waste:7.1%}")
        if rec >= 0.95 and (best is None or len(esc) < best[1]):
            best = (T, len(esc))
    if best:
        print(f"  → 保 95% 召回的最小出卡量：T={best[0]}（{best[1]} 张）")

    # ── 上限：U-Net 自己的分歧块多大时它不可信 ──
    have_u = [r for r in rows if r["has_unet"] and r["unet_dis"] is not None]
    print(f"\n【上限】U-Net 缝自身 dis_unet ≥ U 时判定它不可信、不进池。真值 = 人没选 unet_seam（{len(have_u)} 条有该候选）")
    pu = np.array([r["unet_dis"] for r in have_u if r["pick_unet"]])
    npu = np.array([r["unet_dis"] for r in have_u if not r["pick_unet"]])
    print(f"  人选了 U-Net 的 {pu.size} 条：dis 分位 25/50/75/90/max = {np.percentile(pu, [25, 50, 75, 90]).round().tolist()} / {int(pu.max()) if pu.size else '-'}")
    print(f"  人没选的   {npu.size} 条：dis 分位 25/50/75/90/max = {np.percentile(npu, [25, 50, 75, 90]).round().tolist()} / {int(npu.max()) if npu.size else '-'}")
    print(f"  {'U':>6s} {'剔除数':>6s} {'误剔(人本要选)':>14s} {'命中(人确实没选)':>16s} {'精度':>6s}")
    for U in (150, 200, 300, 400, 500, 600, 800, 1000, 1200):
        drop = [r for r in have_u if r["unet_dis"] >= U]
        wrong = sum(1 for r in drop if r["pick_unet"])
        right = len(drop) - wrong
        print(f"  {U:6d} {len(drop):6d} {wrong:14d} {right:16d} {right / max(1, len(drop)):6.1%}")
    # 无误剔的最大命中
    cand_u = [U for U in range(150, 2500, 10) if not any(r["pick_unet"] for r in have_u if r["unet_dis"] >= U)]
    if cand_u:
        U0 = min(cand_u)
        drop = [r for r in have_u if r["unet_dis"] >= U0]
        print(f"  → 零误剔的最低上限：U={U0}，剔除 {len(drop)} 条（全部是人确实没选 U-Net 的）")

    # ── 现役 chosen 的 dis 与人裁的关系（诊断用） ──
    print("\n【诊断】按人选了什么分组，U-Net 缝自身 dis 的中位数：")
    g = {}
    for r in have_u:
        g.setdefault(r["pick"], []).append(r["unet_dis"])
    for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])):
        print(f"  {k:12s} n={len(v):3d} 中位 {int(np.median(v)):5d}  p90 {int(np.percentile(v, 90)):6d}")
    jdump({"n": n, "rows": rows}, OUT_ROOT / "calibrate" / f"{a.book}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
