# -*- coding: utf-8 -*-
"""实验二 + 三：成对校验（先认后切）与模板给像素归属。

    python experiments/touch_resolve/exp2_verify_partition.py [--source glyph|font] [--limit N] [--viz 40]

对每条带上下字的 touching-cuts 金标：
  假设集 = 真字对 ∪ 识别器（实验一 chosen 切法 fused top-3 × top-3）给出的竞争字对；
  每个字对：取模板（本书真刻例排除待测格；字体兜底 / 或只用字体），
  在双格窗口上做联合配准（templates.Registrar），得贴合度 cov。
报：
  A. 成对校验：真字对按 cov 排第一的比例、与最强竞争对的间隔；对照 CNN 概率乘积排序。
  B. 像素归属：真字对配准后的 owner 图 vs 人工金标缝的墨归属一致率，
     对照现役缝 / 直线 / 最优候选；缝表达不了（交叉）的列数；
  C. 归属后识别：按 owner 切出两半再识别，hit@1 vs 现役切法。
产出 out/exp2_<source>/per_case.json、summary.json、viz/*.png。
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

from common import (INK_TH, Loader, OUT_ROOT, Recognizer, half_patch, ink_bbox, jdump, normalize,
                    seam_chosen, seam_gold, seam_straight, seams_candidates, window)
from templates import (Registrar, TemplateBank, owner_agreement, owner_from_seam, per_template_fit, seam_from_owner)


def column_char_height(L, case) -> tuple[float, float]:
    """本列其它字格的墨外接框高的中位数（与宽），估不出来就 0.8×period。"""
    img = L.image_of(case)
    hs, ws = [], []
    for c in case.cc.cells:
        if c.kind != "char" or c.pos in (case.up.pos, case.dn.pos):
            continue
        y0, y1 = int(round(c.y0)), int(round(c.y1))
        crop = img[y0:y1, case.x_lo:case.x_hi] < INK_TH
        bb = ink_bbox(crop)
        if bb is None:
            continue
        h = bb[3] - bb[1]; w = bb[2] - bb[0]
        if 0.4 * case.period < h < 1.1 * case.period:
            hs.append(h); ws.append(w)
    if len(hs) >= 3:
        return float(np.median(hs)), float(np.median(ws))
    return 0.8 * case.period, 0.75 * case.content_w


def viz_case(win_gray, owner, A, pa, B, pb, label, path):
    vis = cv2.cvtColor(win_gray, cv2.COLOR_GRAY2BGR)
    ov = vis.copy()
    ov[owner == 1] = (0, 0, 220)
    ov[owner == 2] = (220, 90, 0)
    vis = cv2.addWeighted(vis, 0.35, ov, 0.65, 0)
    # 模板轮廓
    canvas = np.full_like(win_gray, 255)
    for T, p, col in ((A, pa, (0, 0, 160)), (B, pb, (160, 60, 0))):
        lv = T.levels[p.level]
        ys = lv.ys + p.y; xs = lv.xs + p.x
        ok = (ys >= 0) & (ys < canvas.shape[0]) & (xs >= 0) & (xs < canvas.shape[1])
        canvas[ys[ok], xs[ok]] = 0
    tpl = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    for T, p, col in ((A, pa, (0, 0, 160)), (B, pb, (160, 60, 0))):
        lv = T.levels[p.level]
        ys = lv.ys + p.y; xs = lv.xs + p.x
        ok = (ys >= 0) & (ys < canvas.shape[0]) & (xs >= 0) & (xs < canvas.shape[1])
        tpl[ys[ok], xs[ok]] = col
    sheet = np.concatenate([cv2.cvtColor(win_gray, cv2.COLOR_GRAY2BGR), vis, tpl], axis=1)
    sheet = cv2.resize(sheet, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    cv2.putText(sheet, label.encode("ascii", "ignore").decode(), (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.imwrite(str(path), sheet)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="glyph", choices=("glyph", "font"),
                    help="glyph = 本书真刻例优先、字体兜底；font = 只用字体（模拟没有字形库的新书）")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--competitors", type=int, default=3, help="每侧取识别 top-k 组成竞争字对")
    ap.add_argument("--viz", type=int, default=40)
    ap.add_argument("--books", default="vol01,vol02,vol03")
    ap.add_argument("--tag", default="")
    ap.add_argument("--fitmin", action="store_true", help="每个假设再算分模板贴合度（min(covA,covB)），用它排序")
    a = ap.parse_args()
    out = OUT_ROOT / f"exp2_{a.source}{a.tag}"
    (out / "viz").mkdir(parents=True, exist_ok=True)

    L = Loader()
    R = Recognizer()
    bank = TemplateBank(n_exemplars=2)
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}

    items = L.gold_items(books=a.books.split(","), need_chars=True)
    cases = []
    for it in items:
        c, _ = L.resolve(it)
        if c is not None and c.has_chars() and L.image_of(c) is not None and c.id in exp1:
            cases.append(c)
    if a.limit:
        cases = cases[: a.limit]
    print(f"用例 {len(cases)} 条，模板源 {a.source}")

    per = []
    t0 = time.time()
    n_viz = 0
    norms_after, norms_key = [], []
    agg = defaultdict(list)
    for ci, case in enumerate(cases):
        img = L.image_of(case)
        win, y0, x0 = window(case, img)
        W = (win < INK_TH).astype(np.uint8)
        reg = Registrar(W)
        ch_h, ch_w = column_char_height(L, case)
        exclude = (case.page, case.col, {case.up.pos - 1, case.up.pos, case.dn.pos - 1, case.dn.pos})
        prefer = "glyph" if a.source == "glyph" else "font"

        e1 = exp1[case.id]
        tk = e1["topk"]["chosen"]
        top_a = [c for c in (tk["above"]["fused"] if tk.get("above") else [])][: a.competitors]
        top_b = [c for c in (tk["below"]["fused"] if tk.get("below") else [])][: a.competitors]
        truth = (case.char_above, case.char_below)
        hyps = [truth] + [(x, y) for x in top_a for y in top_b if (x, y) != truth]
        cls_a = dict(tk["above"]["cls"]) if tk.get("above") else {}
        cls_b = dict(tk["below"]["cls"]) if tk.get("below") else {}

        tcache: dict[str, list] = {}

        def templates_for(ch):
            if ch not in tcache:
                tcache[ch] = bank.get(ch, ch_h, exclude=exclude, allow_font=True, prefer=prefer)
            return tcache[ch]

        results = []
        best_true = None
        for hi, (ca, cb) in enumerate(hyps):
            TA, TB = templates_for(ca), templates_for(cb)
            if not TA or not TB:
                results.append({"pair": ca + cb, "cov": None}); continue
            best = None
            for A in TA:
                for B in TB:
                    pa, pb, sc = reg.register(A, B)
                    if best is None or sc > best[0]:
                        best = (sc, A, pa, B, pb)
            entry = {"pair": ca + cb, "cov": round(best[0], 4), "src": f"{best[1].src}+{best[3].src}",
                     "cnn": round(cls_a.get(ca, 0.0) * cls_b.get(cb, 0.0), 4)}
            if a.fitmin:
                ptf = per_template_fit(reg, best[1], best[2], best[3], best[4])
                entry.update({"fitmin": round(ptf["min"], 4), "covA": round(ptf["covA"], 4), "covB": round(ptf["covB"], 4)})
            results.append(entry)
            if hi == 0:
                best_true = best
        rec = {"id": case.id, "verdict": case.verdict, "book": case.book, "pair": "".join(truth),
               "n_hyp": len(hyps), "hyps": results, "ch_h": round(ch_h, 1)}
        scored = [r for r in results if r["cov"] is not None]
        if scored and results[0]["cov"] is not None:
            true_cov = results[0]["cov"]
            wrong = [r["cov"] for r in scored[1:]]
            rec["true_top1_cov"] = bool(not wrong or true_cov > max(wrong))
            rec["margin_cov"] = round(true_cov - (max(wrong) if wrong else 0.0), 4)
            wrong_cnn = [r["cnn"] for r in scored[1:]]
            rec["true_top1_cnn"] = bool(not wrong_cnn or results[0]["cnn"] > max(wrong_cnn))
            if a.fitmin:
                wrong_fm = [r["fitmin"] for r in scored[1:]]
                rec["true_top1_fitmin"] = bool(not wrong_fm or results[0]["fitmin"] > max(wrong_fm))
                rec["margin_fitmin"] = round(results[0]["fitmin"] - (max(wrong_fm) if wrong_fm else 0.0), 4)
                agg["true_top1_fitmin"].append(rec["true_top1_fitmin"])
            rec["true_in_hyps_by_recog"] = bool(truth[0] in top_a and truth[1] in top_b)
            agg["true_top1_cov"].append(rec["true_top1_cov"])
            agg["true_top1_cnn"].append(rec["true_top1_cnn"])
            agg["true_cov"].append(true_cov)
            if wrong:
                agg["best_wrong_cov"].append(max(wrong))
                agg["margin"].append(rec["margin_cov"])
        else:
            rec["true_top1_cov"] = None

        # ── 像素归属 ──
        if best_true is not None:
            sc, A, pa, B, pb = best_true
            owner, dA, dB = reg.partition(A, pa, B, pb)
            og = owner_from_seam(W, seam_gold(case) - y0)
            oc = owner_from_seam(W, seam_chosen(case) - y0)
            os_ = owner_from_seam(W, seam_straight(case) - y0)
            cand_agree = max(owner_agreement(owner_from_seam(W, s - y0), og) for _, s in seams_candidates(case))
            derived, n_inter = seam_from_owner(owner)
            rec["agree"] = {"partition": round(owner_agreement(owner, og), 4),
                            "chosen": round(owner_agreement(oc, og), 4),
                            "straight": round(owner_agreement(os_, og), 4),
                            "best_cand": round(cand_agree, 4),
                            "derived_seam": round(owner_agreement(owner_from_seam(W, derived), og), 4)}
            rec["interleaved_cols"] = int(n_inter)
            for k, v in rec["agree"].items():
                agg[f"agree_{k}"].append(v)
            agg["inter"].append(n_inter)
            # 归属后两半 → 识别
            for side, val in (("above", 1), ("below", 2)):
                hp = half_patch(win, owner == val)
                if hp is not None:
                    norms_after.append(normalize(hp)); norms_key.append((ci, side))
            if n_viz < a.viz and (case.verdict in ("overlap", "moved") or rec["agree"]["chosen"] < 0.97):
                viz_case(win, owner, A, pa, B, pb, f"{case.id} {case.verdict} cov={sc:.3f}",
                         out / "viz" / (case.id.replace(":", "_") + ".png"))
                n_viz += 1
        per.append(rec)
        if (ci + 1) % 50 == 0:
            print(f"  {ci + 1}/{len(cases)}  {time.time() - t0:.0f}s", flush=True)

    # ── 归属后识别 ──
    cls_after, emb_after = [], []
    for i in range(0, len(norms_after), 256):
        cls_after += R.cls_topk(norms_after[i:i + 256], k=5)
        emb_after += R.emb_topk(norms_after[i:i + 256], k=5)
    from open_guji_cv.clustering.cnn_candidates import rrf
    hit_after = Counter(); hit_before = Counter()
    for (ci, side), cl, em in zip(norms_key, cls_after, emb_after):
        case = cases[ci]
        truth = case.char_above if side == "above" else case.char_below
        fused = rrf([c for c, _ in cl], [c for c, _ in em], k=5)
        hit_after["n"] += 1
        hit_after["@1"] += int(bool(fused) and fused[0] == truth)
        hit_after["@5"] += int(truth in fused)
        rk = exp1[case.id]["rank"]["chosen"][f"fused_{side}"]
        hit_before["n"] += 1
        hit_before["@1"] += int(rk == 1)
        hit_before["@5"] += int(rk is not None and rk <= 5)
        per[ci].setdefault("recog_after", {})[side] = fused[:3]

    def mean(xs):
        return float(np.mean(xs)) if xs else float("nan")

    summary = {
        "n": len(per), "source": a.source,
        "A_pair_verify": {
            "n_scored": len(agg["true_top1_cov"]),
            "true_top1_by_cov": round(mean(agg["true_top1_cov"]), 4),
            "true_top1_by_cnn": round(mean(agg["true_top1_cnn"]), 4),
            "true_top1_by_fitmin": round(mean(agg["true_top1_fitmin"]), 4) if agg["true_top1_fitmin"] else None,
            "true_cov_mean": round(mean(agg["true_cov"]), 4),
            "best_wrong_cov_mean": round(mean(agg["best_wrong_cov"]), 4),
            "margin_median": round(float(np.median(agg["margin"])) if agg["margin"] else float("nan"), 4),
            "margin_p10": round(float(np.percentile(agg["margin"], 10)) if agg["margin"] else float("nan"), 4),
        },
        "B_partition_agreement": {k: round(mean(agg[f"agree_{k}"]), 4) for k in ("partition", "derived_seam", "chosen", "straight", "best_cand")},
        "B_partition_lt95": {k: round(float(np.mean(np.array(agg[f"agree_{k}"]) < 0.95)), 4) for k in ("partition", "chosen", "straight", "best_cand")},
        "B_interleaved_cases": round(float(np.mean(np.array(agg["inter"]) > 0)), 4) if agg["inter"] else None,
        "C_recog_after_partition": {"@1": round(hit_after["@1"] / max(1, hit_after["n"]), 4), "@5": round(hit_after["@5"] / max(1, hit_after["n"]), 4), "n": hit_after["n"]},
        "C_recog_chosen_cut": {"@1": round(hit_before["@1"] / max(1, hit_before["n"]), 4), "@5": round(hit_before["@5"] / max(1, hit_before["n"]), 4), "n": hit_before["n"]},
        "seconds": round(time.time() - t0, 1),
    }
    # 按 verdict 分层的归属一致率
    by_v = defaultdict(lambda: defaultdict(list))
    for r in per:
        if "agree" in r:
            for k, v in r["agree"].items():
                by_v[r["verdict"]][k].append(v)
    summary["B_by_verdict"] = {v: {k: round(mean(x), 4) for k, x in d.items()} | {"n": len(d["partition"])} for v, d in by_v.items()}

    jdump(per, out / "per_case.json"); jdump(summary, out / "summary.json")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
