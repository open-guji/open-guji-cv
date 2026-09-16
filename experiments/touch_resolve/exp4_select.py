# -*- coding: utf-8 -*-
"""实验四：身份条件下的**选择**——在 {直线, 窄走廊缝, 宽走廊缝, 模板归属} 里按模板贴合度选一个。

    python experiments/touch_resolve/exp4_select.py [--source glyph|font] [--limit N]

实验三说明模板归属本身不如现役缝稳（现役缝对的地方它会引入新错），但在现役缝错的地方更好。
部署形态因此应是「多候选 + 身份条件选择器」而非替换。这里测选择器：
  对每条金标，配准真字对（模板 A/B 各得一个位置），对每个候选归属 o 算分模板贴合度
  fit(o) = min(covA(o), covB(o))（`templates.per_template_fit`），选 fit 最大者。
报（相对人工金标缝，frame_ok 子集）：chosen（现役规则）/ selected（选择器）/ oracle（事后最优）/ partition 的 err_px 与 blob≥60，
以及选择器选中各候选的分布、选对 oracle 的比例。
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict

import numpy as np

from common import (INK_TH, Loader, OUT_ROOT, jdump, seam_chosen, seam_gold, seam_straight, seams_candidates, window)
from exp2_verify_partition import column_char_height
from exp3_partition_eval import err_stats
from templates import Registrar, TemplateBank, owner_from_seam, per_template_fit, seam_from_owner


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="glyph", choices=("glyph", "font"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--books", default="vol01,vol02,vol03")
    a = ap.parse_args()
    out = OUT_ROOT / f"exp4_{a.source}"; out.mkdir(parents=True, exist_ok=True)
    L = Loader(); bank = TemplateBank(n_exemplars=2)
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    frame_ok = set(json.loads((OUT_ROOT / "frame_ok.json").read_text(encoding="utf-8")))
    cases = []
    for it in L.gold_items(books=a.books.split(","), need_chars=True):
        c, _ = L.resolve(it)
        if c is not None and c.has_chars() and L.image_of(c) is not None and c.id in exp1:
            cases.append(c)
    if a.limit:
        cases = cases[: a.limit]
    print(f"用例 {len(cases)} 条，模板源 {a.source}")
    per = []; t0 = time.time()
    for ci, case in enumerate(cases):
        img = L.image_of(case); win, y0, _ = window(case, img)
        W = (win < INK_TH).astype(np.uint8); reg = Registrar(W)
        ch_h, _ = column_char_height(L, case)
        exclude = (case.page, case.col, {case.up.pos - 1, case.up.pos, case.dn.pos - 1, case.dn.pos})
        prefer = "glyph" if a.source == "glyph" else "font"
        TA = bank.get(case.char_above, ch_h, exclude=exclude, prefer=prefer)
        TB = bank.get(case.char_below, ch_h, exclude=exclude, prefer=prefer)
        rk = exp1[case.id]["rank"]["gold"]
        label_ok = bool(rk["fused_above"] and rk["fused_above"] <= 5 and rk["fused_below"] and rk["fused_below"] <= 5)
        rec = {"id": case.id, "verdict": case.verdict, "pair": case.char_above + case.char_below, "label_ok": label_ok,
               "poly": bool(case.gold_poly), "frame_ok": case.id in frame_ok}
        og = owner_from_seam(W, seam_gold(case) - y0)
        cands = {k: owner_from_seam(W, s - y0) for k, s in seams_candidates(case)}
        cands.setdefault("straight", owner_from_seam(W, seam_straight(case) - y0))
        chosen_o = owner_from_seam(W, seam_chosen(case) - y0)
        if not (TA and TB):
            per.append(rec); continue
        best = None
        for A in TA:
            for B in TB:
                pa, pb, sc = reg.register(A, B)
                if best is None or sc > best[0]:
                    best = (sc, A, pa, B, pb)
        sc, A, pa, B, pb = best
        owner, _, _ = reg.partition(A, pa, B, pb)
        cands["partition"] = owner
        fits = {k: per_template_fit(reg, A, pa, B, pb, owner=o) for k, o in cands.items()}
        errs = {k: err_stats(o, og) for k, o in cands.items()}
        sel_min = max(fits, key=lambda k: fits[k]["min"])
        sel_mean = max(fits, key=lambda k: (fits[k]["covA"] + fits[k]["covB"]) / 2)
        # 只在缝候选里选（不含模板归属）
        seam_keys = [k for k in cands if k != "partition"]
        sel_seam = max(seam_keys, key=lambda k: fits[k]["min"])
        oracle = min(cands, key=lambda k: errs[k][0])
        oracle_seam = min(seam_keys, key=lambda k: errs[k][0])
        rec.update({"cov": round(sc, 4), "fits": {k: {kk: round(v, 4) for kk, v in f.items()} for k, f in fits.items()},
                    "errs": {k: {"px": e[0], "blob": e[1]} for k, e in errs.items()},
                    "err_chosen": {"px": err_stats(chosen_o, og)[0], "blob": err_stats(chosen_o, og)[1]},
                    "sel_min": sel_min, "sel_mean": sel_mean, "sel_seam": sel_seam, "oracle": oracle, "oracle_seam": oracle_seam})
        per.append(rec)
        if (ci + 1) % 100 == 0:
            print(f"  {ci + 1}/{len(cases)}  {time.time() - t0:.0f}s", flush=True)
    jdump(per, out / "per_case.json")

    def report(rows, title):
        rows = [r for r in rows if "errs" in r]
        if not rows:
            return
        print(f"\n== {title} n={len(rows)}   err_px mean / p90 | blob≥60 | blob≥150")
        def line(name, get):
            px = np.array([get(r)["px"] for r in rows]); bl = np.array([get(r)["blob"] for r in rows])
            print(f"  {name:22s} {px.mean():6.1f} / {np.percentile(px, 90):5.0f} | {(bl >= 60).mean():6.1%} | {(bl >= 150).mean():6.1%}")
        line("chosen（现役规则）", lambda r: r["err_chosen"])
        line("straight", lambda r: r["errs"]["straight"])
        line("partition", lambda r: r["errs"]["partition"])
        line("selected: min fit", lambda r: r["errs"][r["sel_min"]])
        line("selected: mean fit", lambda r: r["errs"][r["sel_mean"]])
        line("selected: 只在缝里选", lambda r: r["errs"][r["sel_seam"]])
        line("oracle（含归属）", lambda r: r["errs"][r["oracle"]])
        line("oracle（只缝）", lambda r: r["errs"][r["oracle_seam"]])
        print("  选择器选中分布:", dict(Counter(r["sel_min"] for r in rows)), " 与 oracle 一致:",
              f"{np.mean([r['sel_min'] == r['oracle'] for r in rows]):.1%}",
              " 选中项 err≤oracle+10px:", f"{np.mean([r['errs'][r['sel_min']]['px'] <= r['errs'][r['oracle']]['px'] + 10 for r in rows]):.1%}")

    fo = [r for r in per if r["frame_ok"] and r["label_ok"]]
    report(fo, "frame_ok+label_ok")
    report([r for r in fo if r["poly"]], "frame_ok+label_ok+poly")
    for v in ("seam_ok", "moved", "ok", "overlap"):
        report([r for r in fo if r["verdict"] == v], f"frame_ok+label_ok/{v}")
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
