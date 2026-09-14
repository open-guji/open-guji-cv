# -*- coding: utf-8 -*-
"""实验三：模板给像素归属，换更锋利的尺子量。

    python experiments/touch_resolve/exp3_partition_eval.py [--source glyph|font] [--limit N]

只配准**真字对**（有整理本的情形），对每条金标比四种归属：
  partition = 模板配准后的逐像素归属；chosen = 现役缝；straight = 直线；best_cand = 候选里离金标最近的。
尺子（都相对人工金标缝定义的归属，只算墨像素）：
  err_px   = 归属错的墨像素数（绝对数，不是比例——一整笔 ~100px 只占两字墨的 1%）
  err_blob = 错归属像素里最大连通块的面积（≥60 基本就是一笔被划错边）
  recog@1  = 按该归属切出两半再识别（fused），两侧都命中真字的比例
另报按 verdict 分层、按「标签可信」（实验一 gold 切法 fused@5 两侧都命中）分层、partition 对 chosen 的逐条胜负。
产出 out/exp3_<source>/per_case.json、summary.json、viz/（partition 错得最多的 30 条）。
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict

import cv2
import numpy as np

from common import (INK_TH, Loader, OUT_ROOT, Recognizer, half_patch, jdump, normalize,
                    seam_chosen, seam_gold, seam_straight, seams_candidates, window)
from exp2_verify_partition import column_char_height, viz_case
from templates import Registrar, TemplateBank, owner_from_seam, seam_from_owner


def err_stats(o: np.ndarray, og: np.ndarray) -> tuple[int, int]:
    m = (og > 0) & (o > 0) & (o != og)
    n = int(m.sum())
    if n == 0:
        return 0, 0
    k, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    return n, int(stats[1:, cv2.CC_STAT_AREA].max())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="glyph", choices=("glyph", "font"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--books", default="vol01,vol02,vol03")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    out = OUT_ROOT / f"exp3_{a.source}{a.tag}"
    (out / "viz").mkdir(parents=True, exist_ok=True)

    L = Loader(); R = Recognizer(); bank = TemplateBank(n_exemplars=2)
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    cases = []
    for it in L.gold_items(books=a.books.split(","), need_chars=True):
        c, _ = L.resolve(it)
        if c is not None and c.has_chars() and L.image_of(c) is not None and c.id in exp1:
            cases.append(c)
    if a.limit:
        cases = cases[: a.limit]
    print(f"用例 {len(cases)} 条，模板源 {a.source}")

    per = []; t0 = time.time()
    norms, keys = [], []
    kept = []   # (case, win, owner, A, pa, B, pb, cov)
    for ci, case in enumerate(cases):
        img = L.image_of(case)
        win, y0, _ = window(case, img)
        W = (win < INK_TH).astype(np.uint8)
        reg = Registrar(W)
        ch_h, _ = column_char_height(L, case)
        exclude = (case.page, case.col, {case.up.pos - 1, case.up.pos, case.dn.pos - 1, case.dn.pos})
        prefer = "glyph" if a.source == "glyph" else "font"
        TA = bank.get(case.char_above, ch_h, exclude=exclude, prefer=prefer)
        TB = bank.get(case.char_below, ch_h, exclude=exclude, prefer=prefer)
        e1 = exp1[case.id]
        rk_gold = e1["rank"]["gold"]; rk_chosen = e1["rank"]["chosen"]
        label_ok = bool(rk_gold["fused_above"] and rk_gold["fused_above"] <= 5 and rk_gold["fused_below"] and rk_gold["fused_below"] <= 5)
        rec = {"id": case.id, "verdict": case.verdict, "book": case.book, "pair": case.char_above + case.char_below,
               "label_ok": label_ok, "poly": bool(case.gold_poly), "has_templates": bool(TA and TB)}
        og = owner_from_seam(W, seam_gold(case) - y0)
        owners = {"chosen": owner_from_seam(W, seam_chosen(case) - y0),
                  "straight": owner_from_seam(W, seam_straight(case) - y0)}
        cands = [(k, owner_from_seam(W, s - y0)) for k, s in seams_candidates(case)]
        owners["best_cand"] = min(cands, key=lambda kv: err_stats(kv[1], og)[0])[1]
        if TA and TB:
            best = None
            for A in TA:
                for B in TB:
                    pa, pb, sc = reg.register(A, B)
                    if best is None or sc > best[0]:
                        best = (sc, A, pa, B, pb)
            sc, A, pa, B, pb = best
            owner, _, _ = reg.partition(A, pa, B, pb)
            owners["partition"] = owner
            dseam, n_inter = seam_from_owner(owner)
            owners["derived_seam"] = owner_from_seam(W, dseam)
            rec["cov"] = round(sc, 4); rec["src"] = f"{A.src}+{B.src}"; rec["interleaved_cols"] = int(n_inter)
            kept.append((case, win, owner, A, pa, B, pb, sc))
            for side, val in (("above", 1), ("below", 2)):
                hp = half_patch(win, owner == val)
                if hp is not None:
                    norms.append(normalize(hp)); keys.append((ci, "partition", side))
        rec["err"] = {}
        for k, o in owners.items():
            n, blob = err_stats(o, og)
            rec["err"][k] = {"px": n, "blob": blob}
        rec["recog_chosen"] = {"above": rk_chosen["fused_above"], "below": rk_chosen["fused_below"]}
        rec["recog_gold"] = {"above": rk_gold["fused_above"], "below": rk_gold["fused_below"]}
        per.append(rec)
        if (ci + 1) % 100 == 0:
            print(f"  {ci + 1}/{len(cases)}  {time.time() - t0:.0f}s", flush=True)

    # 归属后识别
    from open_guji_cv.clustering.cnn_candidates import rrf
    cls_all, emb_all = [], []
    for i in range(0, len(norms), 256):
        cls_all += R.cls_topk(norms[i:i + 256], k=5); emb_all += R.emb_topk(norms[i:i + 256], k=5)
    for (ci, which, side), cl, em in zip(keys, cls_all, emb_all):
        truth = cases[ci].char_above if side == "above" else cases[ci].char_below
        fused = rrf([c for c, _ in cl], [c for c, _ in em], k=5)
        r = 1 + fused.index(truth) if truth in fused else None
        per[ci].setdefault("recog_partition", {})[side] = r

    # ── 汇总 ──
    def agg(rows, key):
        px = np.array([r["err"][key]["px"] for r in rows if key in r["err"]])
        bl = np.array([r["err"][key]["blob"] for r in rows if key in r["err"]])
        if px.size == 0:
            return None
        return {"n": int(px.size), "px_mean": round(float(px.mean()), 1), "px_median": float(np.median(px)),
                "px_p90": float(np.percentile(px, 90)), "le20px": round(float((px <= 20).mean()), 4),
                "blob_ge60": round(float((bl >= 60).mean()), 4), "blob_ge150": round(float((bl >= 150).mean()), 4)}

    def recog_both(rows, key):
        vals = []
        for r in rows:
            d = r.get(key)
            if not d or "above" not in d or "below" not in d:
                continue
            vals.append(int(d["above"] == 1 and d["below"] == 1))
        return round(float(np.mean(vals)), 4) if vals else None, len(vals)

    summary = {"n": len(per), "source": a.source, "seconds": round(time.time() - t0, 1)}
    strata = {"all": per, "label_ok": [r for r in per if r["label_ok"]],
              "label_ok+poly": [r for r in per if r["label_ok"] and r["poly"]]}
    for v in ("seam_ok", "ok", "overlap", "moved"):
        strata[f"label_ok/{v}"] = [r for r in per if r["label_ok"] and r["verdict"] == v]
    summary["err"] = {sname: {k: agg(rows, k) for k in ("partition", "derived_seam", "chosen", "straight", "best_cand")}
                      for sname, rows in strata.items()}
    summary["recog_both_top1"] = {sname: {"partition": recog_both(rows, "recog_partition"),
                                          "chosen": recog_both(rows, "recog_chosen"),
                                          "gold": recog_both(rows, "recog_gold")} for sname, rows in strata.items()}
    # 逐条胜负（label_ok 子集）：partition vs chosen，按 err_px，容差 10
    wl = Counter()
    for r in strata["label_ok"]:
        if "partition" not in r["err"]:
            continue
        d = r["err"]["chosen"]["px"] - r["err"]["partition"]["px"]
        wl["win" if d > 10 else ("loss" if d < -10 else "tie")] += 1
    summary["partition_vs_chosen_label_ok"] = dict(wl)
    jdump(per, out / "per_case.json"); jdump(summary, out / "summary.json")

    # 打印
    print(f"\n== 错归属（label_ok 子集 n={len(strata['label_ok'])}）  px_mean / median / p90 | ≤20px | blob≥60 | blob≥150")
    for k in ("partition", "derived_seam", "chosen", "straight", "best_cand"):
        s = summary["err"]["label_ok"][k]
        if s:
            print(f"  {k:13s} {s['px_mean']:6.1f} / {s['px_median']:4.0f} / {s['px_p90']:5.0f} | {s['le20px']:6.1%} | {s['blob_ge60']:6.1%} | {s['blob_ge150']:6.1%}")
    print("== 按 verdict（label_ok）px_mean  partition / chosen / straight / best_cand")
    for v in ("seam_ok", "ok", "overlap", "moved"):
        s = summary["err"][f"label_ok/{v}"]
        if s["partition"]:
            print(f"  {v:8s} n={s['partition']['n']:3d}  {s['partition']['px_mean']:6.1f} / {s['chosen']['px_mean']:6.1f} / {s['straight']['px_mean']:6.1f} / {s['best_cand']['px_mean']:6.1f}"
                  f"   blob≥60: {s['partition']['blob_ge60']:5.1%} / {s['chosen']['blob_ge60']:5.1%} / {s['straight']['blob_ge60']:5.1%} / {s['best_cand']['blob_ge60']:5.1%}")
    print("== 两侧都 top-1 命中真字：", json.dumps(summary["recog_both_top1"]["label_ok"], ensure_ascii=False))
    print("== partition vs chosen（label_ok，err_px 容差 10）：", summary["partition_vs_chosen_label_ok"])

    # viz：partition 错得最多的 30 条（label_ok）
    worst = sorted([r for r in strata["label_ok"] if "partition" in r["err"]], key=lambda r: -r["err"]["partition"]["px"])[:30]
    wid = {r["id"] for r in worst}
    for case, win, owner, A, pa, B, pb, sc in kept:
        if case.id in wid:
            r = next(x for x in worst if x["id"] == case.id)
            viz_case(win, owner, A, pa, B, pb, f"{case.id} {case.verdict} err={r['err']['partition']['px']} chosen={r['err']['chosen']['px']} cov={sc:.3f}",
                     out / "viz" / (case.id.replace(":", "_") + ".png"))
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
