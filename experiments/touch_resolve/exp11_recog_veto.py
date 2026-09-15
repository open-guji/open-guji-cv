# -*- coding: utf-8 -*-
"""实验十一（L4 预研）：识别置信「否决票」能替人裁掉多少条？

    python experiments/touch_resolve/exp11_recog_veto.py [--book vol02]

真值 = 用户 2026-09-15 裁的 147 条（`cand` / `verdict=ok`）。对每条的**每个候选**按该切法切两半 → CNN
（分类头 + embedding，RRF 融合）→ 取 top-1 置信，算「上×下」乘积。判据不是「取乘积最大」（10 卡第三节已证：
在像样的候选之间排序不行，20 条上只对 11 条），而是**只在决定性时出手**：

    最高乘积 ≥ PROD_MIN 且 ≥ RATIO × 次高  →  采纳最高者；否则弃权（交人）

扫 (PROD_MIN, RATIO) 网格，报：出手率、出手时命中人裁的比例（精度）、以及「弃权但人其实选了 U-Net 缝」的比例
（这部分将来可由「U-Net 缝优先」的默认值兜住）。产出 out/exp11/<book>.json。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INK_TH, Loader, OUT_ROOT, Recognizer, half_patch, jdump, normalize, window  # noqa: E402
from open_guji_cv.core.spec import column_key  # noqa: E402
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.eval.touching import SHARD  # noqa: E402
from open_guji_cv.feedback.consumers import verdict_store  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.utils.cut_select import owner_from_seam  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol02")
    ap.add_argument("--events", default=None, help="事件日志（缺省 workspace feedback/events/<book>-cutline.jsonl）")
    ap.add_argument("--since", default="2026-09-15")
    a = ap.parse_args()
    ev_path = Path(a.events) if a.events else Path(
        __import__("open_guji_cv.core.workspace", fromlist=["x"]).feedback_root()) / "events" / f"{a.book}-cutline.jsonl"
    picks: dict[str, str] = {}
    for line in ev_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") != "cutline" or r["ts"] < a.since:
            continue
        p = r["payload"]
        k = p.get("cand") or ("straight" if p.get("verdict") == "ok" else None)
        if k:
            picks[r["target"]["key"]] = k
    print(f"人裁真值 {len(picks)} 条")
    # 候选池：人裁已经把产物收敛了，原池要从 exp10 的快照取

    st, ic = ProductStore(), ImageCache()
    R = Recognizer()
    # 产物里这些切点已被人裁收敛成单候选，原池看不到了 → **关掉 resolved_cuts 重跑该列**拿原池。
    # 与 Step3 同一套入参（verify_prod_judge.run_column 已封装），judge 传真裁判，扩池照跑。
    from open_guji_cv.core.book import load_book
    from open_guji_cv.steps.row_segment import RowSegmentParams
    from open_guji_cv.utils.cut_select import get_judge
    from verify_prod_judge import run_column
    bk = load_book(a.book)
    rp = RowSegmentParams()
    judge = get_judge()
    gate_cache: dict = {}
    col_cache: dict = {}

    def repool(pg: int, col: int):
        """重算该列（不套人裁）→ {slot_above: CutPointCandidates}。"""
        key = (pg, col)
        if key in col_cache:
            return col_cache[key]
        if pg not in gate_cache:
            gate_cache[pg] = st.read(a.book, "column_gate", page_key(pg), "gate_manifest")
        gate = gate_cache[pg]
        out = {}
        if gate is not None and gate.period is not None:
            gc = next((g for g in gate.columns if g.col == col), None)
            path_ = ic.get(a.book, "column_image", column_key(pg, col))
            img_ = cv2.imread(str(path_), cv2.IMREAD_GRAYSCALE) if path_ else None
            if gc is not None and img_ is not None:
                r_ = run_column(bk, gate, gc, img_, rp, judge)
                if r_ is not None:
                    out = {cp.slot_above: cp for cp in r_.cut_candidates}
        col_cache[key] = out
        return out
    from open_guji_cv.clustering.cnn_candidates import rrf
    rows = []
    norms: list = []
    keys: list = []
    cache: dict = {}
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
        cp = repool(pg, col).get(slot)          # 原池（不套人裁）
        if cp is None:
            continue
        cm = {c.slot: c for c in cc.cells if c.sub is None}
        up, dn = cm.get(cp.slot_above), cm.get(cp.slot_below)
        if up is None or dn is None:
            continue
        path = ic.get(a.book, "column_image", column_key(pg, col))
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path else None
        if img is None:
            continue
        x_lo, x_hi = [int(round(v)) for v in cc.content_x]
        y0, y1 = int(round(up.y0)), int(round(dn.y1))
        win = img[y0:y1, x_lo:x_hi]
        W = (win < INK_TH).astype(np.uint8)
        w = x_hi - x_lo
        y_line = int(round(cp.y))
        ci = len(rows)
        cands = [{"kind": c.kind, "agree": c.agree, "dis_unet": c.dis_unet} for c in cp.candidates]
        rows.append({"id": cid, "pick": pick, "n_cand": len(cands), "cands": cands})
        for mi, pc in enumerate(cp.candidates):
            seam = np.full(w, y_line) if pc.y is None else np.asarray(pc.y, dtype=int)
            if len(seam) != w:
                continue
            o = owner_from_seam(W, seam - y0)
            for side, val in (("a", 1), ("b", 2)):
                hp = half_patch(win, o == val)
                if hp is None:
                    continue
                norms.append(normalize(hp))
                keys.append((ci, mi, side))
    print(f"用例 {len(rows)}，半字图 {len(norms)}")
    if not norms:
        print("没有可比样本（产物已被人裁收敛，池里只剩一条）——改用 exp10 快照里的 err 做代理")
        jdump({"n": 0}, OUT_ROOT / "exp11" / f"{a.book}.json")
        return 0
    cls_all, emb_all = [], []
    for i in range(0, len(norms), 256):
        cls_all += R.cls_topk(norms[i:i + 256], k=5)
        emb_all += R.emb_topk(norms[i:i + 256], k=5)
    for (ci, mi, side), cl, em in zip(keys, cls_all, emb_all):
        rows[ci]["cands"][mi][f"cls_{side}"] = float(cl[0][1]) if cl else 0.0
        rows[ci]["cands"][mi][f"top_{side}"] = cl[0][0] if cl else None
    for r in rows:
        for c in r["cands"]:
            c["prod"] = (c.get("cls_a") or 0.0) * (c.get("cls_b") or 0.0)
    ok = [r for r in rows if any("prod" in c for c in r["cands"])]
    print(f"\n判据扫描（真值 = 人裁；{len(ok)} 条有识别结果）")
    print(f"{'PROD_MIN':>9s} {'RATIO':>6s} {'出手':>5s} {'出手率':>7s} {'命中':>5s} {'精度':>7s} {'弃权中人选U':>11s}")
    best = []
    for pmin in (0.2, 0.3, 0.4, 0.5, 0.6):
        for ratio in (2.0, 3.0, 5.0, 10.0):
            act = 0
            hit = 0
            abst_u = 0
            for r in ok:
                cs = sorted([c for c in r["cands"] if "prod" in c], key=lambda c: -c["prod"])
                if len(cs) < 2:
                    continue
                if cs[0]["prod"] >= pmin and cs[0]["prod"] >= ratio * max(cs[1]["prod"], 1e-9):
                    act += 1
                    hit += (cs[0]["kind"] == r["pick"])
                else:
                    abst_u += (r["pick"] == "unet_seam")
            if act:
                prec = hit / act
                print(f"{pmin:9.2f} {ratio:6.1f} {act:5d} {act / len(ok):7.1%} {hit:5d} {prec:7.1%} {abst_u:11d}")
                best.append((prec, act, pmin, ratio))
    if best:
        best.sort(key=lambda t: (-t[0], -t[1]))
        print(f"\n最高精度：PROD_MIN={best[0][2]} RATIO={best[0][3]} → 出手 {best[0][1]} 条，精度 {best[0][0]:.1%}")
    jdump({"rows": rows}, OUT_ROOT / "exp11" / f"{a.book}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
