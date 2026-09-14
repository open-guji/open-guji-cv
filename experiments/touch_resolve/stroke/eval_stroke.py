# -*- coding: utf-8 -*-
"""笔画级归属 vs U-Net v2 逐像素归属（raw / 连通体多数票）vs 现役缝，在金标上三方对比。

    .venv/Scripts/python experiments/touch_resolve/stroke/eval_stroke.py [--limit N] [--variants stroke,stroke_seg,...]

口径（与 restrat.py 一致）：
  评测子集 = frame_ok（金标坐标系与当下列图一致，601）∩ 标签可信（exp1 gold 切法 fused@5 两侧都命中）∩ 带折线，约 181 条；
  尺子 = err_px（错归属墨像素数）、blob≥60 / ≥150（错归属最大连通块），逐条胜负容差 10 px。
产出 out/stroke_eval/{per_case.json, summary.json, summary.md, viz/, viz_debug/}。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_stroke import (STROKE_OUT, UNetV2, cc_vote, err_stats, owner_from_seam,  # noqa: E402
                           raw_owner_from_pred, sheet)
from stroke_partition import DEFAULT_PARAMS, draw_units, stroke_partition  # noqa: E402
from common import INK_TH, OUT_ROOT, Loader, jdump, seam_chosen, seam_gold, window  # noqa: E402

KNOWN = ["vol01:6:2:13", "vol01:8:9:11", "vol01:79:2:7", "vol02:133:9:18"]
VARIANTS = {
    "stroke": {},                                   # 现行默认：链 + 颈劈 + 臂端延伸
    "stroke_seg": {"chain": False},                 # 消融：不接链，纯段级投票
    "stroke_nosplit": {"split_min_gain": 10 ** 9},  # 消融：链内不劈
    "stroke_vote": {"core_rule": "vote"},           # 交叉核心按像素票
    "stroke_nospur": {"spur_len": 0},               # 不剪毛刺
}
BASES = ("unet_raw", "unet", "chosen")


def agg(rows, key):
    px = np.array([r["err"][key]["px"] for r in rows if key in r["err"]])
    bl = np.array([r["err"][key]["blob"] for r in rows if key in r["err"]])
    if px.size == 0:
        return None
    return {"n": int(px.size), "px_mean": round(float(px.mean()), 1), "px_median": float(np.median(px)),
            "px_p90": float(np.percentile(px, 90)), "le20px": round(float((px <= 20).mean()), 4),
            "blob_ge60": round(float((bl >= 60).mean()), 4), "blob_ge150": round(float((bl >= 150).mean()), 4),
            "n_blob_ge60": int((bl >= 60).sum()), "n_blob_ge150": int((bl >= 150).sum())}


def winloss(rows, a, b, tol=10):
    c = Counter()
    for r in rows:
        if a not in r["err"] or b not in r["err"]:
            continue
        d = r["err"][b]["px"] - r["err"][a]["px"]
        c["win" if d > tol else ("loss" if d < -tol else "tie")] += 1
    return dict(win=c["win"], tie=c["tie"], loss=c["loss"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--books", default="vol01,vol02,vol03")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--main", default="stroke")
    ap.add_argument("--no-viz", action="store_true")
    a = ap.parse_args()
    variants = {k: VARIANTS[k] for k in a.variants.split(",") if k in VARIANTS}
    out = STROKE_OUT; (out / "viz").mkdir(parents=True, exist_ok=True); (out / "viz_debug").mkdir(parents=True, exist_ok=True)

    L = Loader(); net = UNetV2()
    frame_ok = set(json.loads((OUT_ROOT / "frame_ok.json").read_text(encoding="utf-8")))
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    cases = []
    for it in L.gold_items(books=a.books.split(",")):
        c, _ = L.resolve(it)
        if c is not None and L.image_of(c) is not None:
            cases.append(c)
    if a.limit:
        cases = cases[: a.limit]
    print(f"用例 {len(cases)} 条（resolve 成功且有列图），frame_ok {sum(c.id in frame_ok for c in cases)}，"
          f"U-Net 设备 {net.dev}，变体 {list(variants)}", flush=True)

    per = []; keep = {}     # id -> (win, owners dict, res)
    t0 = time.time(); t_unet = 0.0; t_stroke = 0.0
    for ci, case in enumerate(cases):
        img = L.image_of(case); win, y0, _ = window(case, img)
        W = (win < INK_TH).astype(np.uint8)
        t1 = time.time(); pred = net.predict(win); t_unet += time.time() - t1
        raw = raw_owner_from_pred(pred, W); voted = cc_vote(raw, W)
        votes = (pred * W).astype(np.uint8)
        og = owner_from_seam(W, seam_gold(case) - y0); oc = owner_from_seam(W, seam_chosen(case) - y0)
        owners = {"unet_raw": raw, "unet": voted, "chosen": oc}
        res_main = None
        for name, prm in variants.items():
            t1 = time.time(); res = stroke_partition(win, votes, prm); t_stroke += time.time() - t1
            owners[name] = res.owner
            if name == a.main:
                res_main = res
        e1 = exp1.get(case.id)
        label_ok = bool(e1 and e1["rank"]["gold"]["fused_above"] and e1["rank"]["gold"]["fused_above"] <= 5
                        and e1["rank"]["gold"]["fused_below"] and e1["rank"]["gold"]["fused_below"] <= 5)
        rec = {"id": case.id, "verdict": case.verdict, "book": case.book, "pair": case.char_above + case.char_below,
               "frame_ok": case.id in frame_ok, "label_ok": label_ok, "poly": bool(case.gold_poly),
               "ink_px": int(W.sum()), "err": {}}
        for k, o in owners.items():
            n, blob = err_stats(o, og); rec["err"][k] = {"px": n, "blob": blob}
        if res_main is not None:
            rec["stroke_info"] = {"segments": len(res_main.segments), "pairs": res_main.n_pairs, "chains": res_main.n_chains,
                                  "splits": res_main.n_splits, "fallback_px": res_main.fallback_px}
        per.append(rec)
        keep[case.id] = (win, owners, og, res_main)
        if (ci + 1) % 100 == 0:
            print(f"  {ci + 1}/{len(cases)}  {time.time() - t0:.0f}s", flush=True)

    # ── 分层 ──
    main_rows = [r for r in per if r["frame_ok"] and r["label_ok"] and r["poly"]]
    strata = {
        "frame_ok+label_ok+poly": main_rows,
        "frame_ok+label_ok+poly/seam_ok": [r for r in main_rows if r["verdict"] == "seam_ok"],
        "frame_ok+label_ok+poly/moved": [r for r in main_rows if r["verdict"] == "moved"],
        "frame_ok+label_ok": [r for r in per if r["frame_ok"] and r["label_ok"]],
        "frame_ok+label_ok/seam_ok": [r for r in per if r["frame_ok"] and r["label_ok"] and r["verdict"] == "seam_ok"],
        "frame_ok+label_ok/moved": [r for r in per if r["frame_ok"] and r["label_ok"] and r["verdict"] == "moved"],
        "frame_ok+label_ok/ok": [r for r in per if r["frame_ok"] and r["label_ok"] and r["verdict"] == "ok"],
        "frame_ok+label_ok/overlap": [r for r in per if r["frame_ok"] and r["label_ok"] and r["verdict"] == "overlap"],
        "frame_ok": [r for r in per if r["frame_ok"]],
    }
    keys = list(BASES) + list(variants)
    summary = {"n_cases": len(per), "variants": variants, "params_default": DEFAULT_PARAMS,
               "seconds": round(time.time() - t0, 1), "ms_unet": round(1000 * t_unet / max(1, len(per)), 1),
               "ms_stroke_per_variant": round(1000 * t_stroke / max(1, len(per) * len(variants)), 1),
               "err": {s: {k: agg(rows, k) for k in keys} for s, rows in strata.items()},
               "winloss": {}}
    for s in ("frame_ok+label_ok+poly", "frame_ok+label_ok+poly/seam_ok", "frame_ok+label_ok+poly/moved", "frame_ok+label_ok"):
        summary["winloss"][s] = {f"{v} vs {b}": winloss(strata[s], v, b) for v in variants for b in BASES}
    known = {}
    for r in per:
        if r["id"] in KNOWN:
            known[r["id"]] = {"pair": r["pair"], "verdict": r["verdict"], "frame_ok": r["frame_ok"], "label_ok": r["label_ok"],
                              "err": r["err"]}
    summary["known"] = known
    jdump(per, out / "per_case.json"); jdump(summary, out / "summary.json")

    # ── 打印 + summary.md ──
    md = []
    def P(line=""):
        print(line); md.append(line)

    P(f"# 笔画级归属评测（{time.strftime('%Y-%m-%d %H:%M')}）")
    P()
    P(f"用例 {len(per)} 条（resolve 成功），主评测子集 frame_ok ∩ label_ok ∩ poly = {len(main_rows)} 条；"
      f"U-Net 推理 {summary['ms_unet']} ms/窗口（{net.dev}），笔画级 {summary['ms_stroke_per_variant']} ms/窗口。")
    P()
    P("尺子：err_px = 相对金标缝归属错的墨像素数；blob≥60 / ≥150 = 错归属最大连通块达到该面积的用例比例（括号内条数）。")
    P()
    for s in ("frame_ok+label_ok+poly", "frame_ok+label_ok+poly/seam_ok", "frame_ok+label_ok+poly/moved",
              "frame_ok+label_ok", "frame_ok+label_ok/moved", "frame_ok+label_ok/ok", "frame_ok+label_ok/overlap"):
        rows = strata[s]
        P(f"## {s}  n={len(rows)}")
        P()
        P("| 归属 | err_px 均值 | 中位 | p90 | ≤20px | blob≥60 | blob≥150 |")
        P("|---|---:|---:|---:|---:|---:|---:|")
        for k in keys:
            x = summary["err"][s][k]
            if x:
                P(f"| {k} | {x['px_mean']:.1f} | {x['px_median']:.0f} | {x['px_p90']:.0f} | {x['le20px']:.1%} | "
                  f"{x['blob_ge60']:.1%} ({x['n_blob_ge60']}) | {x['blob_ge150']:.1%} ({x['n_blob_ge150']}) |")
        P()
    P("## 逐条胜负（err_px 容差 10 px；win = 变体更好）")
    P()
    for s, d in summary["winloss"].items():
        P(f"- **{s}** (n={len(strata[s])})")
        for k, v in d.items():
            P(f"  - {k}: win {v['win']} / tie {v['tie']} / loss {v['loss']}")
    P()
    P("## 四条已知失败例（err_px(blob)）")
    P()
    P("| id | 字对 | verdict | frame_ok | " + " | ".join(keys) + " |")
    P("|---|---|---|---|" + "|".join(["---:"] * len(keys)) + "|")
    for kid in KNOWN:
        r = known.get(kid)
        if r is None:
            P(f"| {kid} | (未 resolve) |"); continue
        P(f"| {kid} | {r['pair']} | {r['verdict']} | {r['frame_ok']} | " +
          " | ".join(f"{r['err'][k]['px']}({r['err'][k]['blob']})" for k in keys) + " |")
    P()

    # 主变体在主子集上的最差 / 修好 / 变坏
    mk = a.main
    worst = sorted(main_rows, key=lambda r: -r["err"][mk]["px"])[:12]
    fixed = sorted([r for r in main_rows if r["err"]["unet"]["px"] - r["err"][mk]["px"] > 10],
                   key=lambda r: -(r["err"]["unet"]["px"] - r["err"][mk]["px"]))[:12]
    broke = sorted([r for r in main_rows if r["err"][mk]["px"] - r["err"]["unet"]["px"] > 10],
                   key=lambda r: -(r["err"][mk]["px"] - r["err"]["unet"]["px"]))[:12]
    for title, rows in (("最差 12（主子集，按 stroke err_px）", worst), ("修好的（unet − stroke > 10 px）", fixed),
                        ("变坏的（stroke − unet > 10 px）", broke)):
        P(f"## {title}")
        P()
        P("| id | 字对 | verdict | unet_raw | unet | stroke | chosen | ink_px |")
        P("|---|---|---|---:|---:|---:|---:|---:|")
        for r in rows:
            e = r["err"]
            P(f"| {r['id']} | {r['pair']} | {r['verdict']} | {e['unet_raw']['px']}({e['unet_raw']['blob']}) | {e['unet']['px']}({e['unet']['blob']}) | "
              f"{e[mk]['px']}({e[mk]['blob']}) | {e['chosen']['px']}({e['chosen']['blob']}) | {r['ink_px']} |")
        P()
    (out / "summary.md").write_text("\n".join(md), encoding="utf-8")

    # ── 对照图 ──
    if not a.no_viz:
        want = {}
        for tag, rows in (("worst", worst), ("fixed", fixed), ("broke", broke)):
            for r in rows:
                want.setdefault(r["id"], tag)
        for kid in KNOWN:
            want.setdefault(kid, "known")
        for cid, tag in want.items():
            if cid not in keep:
                continue
            win, owners, og, res = keep[cid]
            r = next(x for x in per if x["id"] == cid); e = r["err"]
            title = (f"[{tag}] {cid} {r['pair']} {r['verdict']}  err px(blob): unet_raw {e['unet_raw']['px']}({e['unet_raw']['blob']}) "
                     f"unet {e['unet']['px']}({e['unet']['blob']}) stroke {e[mk]['px']}({e[mk]['blob']}) chosen {e['chosen']['px']}({e['chosen']['blob']})")
            sh = sheet(win, [("U-Net 多数票", owners["unet"]), ("笔画级", owners[mk]), ("金标", og)], title)
            cv2.imwrite(str(out / "viz" / f"{tag}_{cid.replace(':', '_')}.png"), sh)
            if res is not None:
                sh2 = sheet(win, [("U-Net raw", owners["unet_raw"]), ("笔画级", owners[mk]), ("金标", og)], title,
                            extra=[draw_units(win, res, 2)])
                cv2.imwrite(str(out / "viz_debug" / f"{tag}_{cid.replace(':', '_')}.png"), sh2)
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
