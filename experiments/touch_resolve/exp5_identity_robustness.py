# -*- coding: utf-8 -*-
"""实验五：像素归属对「身份假设」有多敏感？（用户 2026-09-13：识别有微小错误不影响，交界处笔画类似就能分开）

    python experiments/touch_resolve/exp5_identity_robustness.py [--limit N]

同一套模板归属（templates.Registrar v2），身份分别取：
  gold   = 金标字对（有整理本的上界）
  top1   = 识别 fused top-1 字对（现役切法切半后认的，无整理本的实际可得）
  rank2  = 每侧故意取识别第 2 名（错但形近）组成的字对
  swap   = 只换一侧为第 2 名（上换 / 下换 各一组，取更差的一组报）
对标签可信 + 带折线的金标（像素意义上可信的那层）报 err_px / blob≥60，并按 top-1 是否等于金标分层。
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict

import numpy as np

from common import INK_TH, Loader, OUT_ROOT, jdump, seam_chosen, seam_gold, window
from exp2_verify_partition import column_char_height
from exp3_partition_eval import err_stats
from templates import Registrar, TemplateBank, owner_from_seam


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    out = OUT_ROOT / "exp5"; out.mkdir(parents=True, exist_ok=True)
    L = Loader(); bank = TemplateBank(n_exemplars=2)
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    cases = []
    for it in L.gold_items(need_chars=True, need_poly=True):
        c, _ = L.resolve(it)
        if c is None or not c.has_chars() or L.image_of(c) is None or c.id not in exp1:
            continue
        rk = exp1[c.id]["rank"]["gold"]
        if rk["fused_above"] and rk["fused_above"] <= 5 and rk["fused_below"] and rk["fused_below"] <= 5:
            cases.append(c)
    if a.limit:
        cases = cases[: a.limit]
    print(f"标签可信 + 带折线 用例 {len(cases)}")

    per = []; t0 = time.time(); agg = defaultdict(list)
    for ci, case in enumerate(cases):
        img = L.image_of(case); win, y0, _ = window(case, img); W = (win < INK_TH).astype(np.uint8)
        reg = Registrar(W); ch_h, _ = column_char_height(L, case)
        exclude = (case.page, case.col, {case.up.pos - 1, case.up.pos, case.dn.pos - 1, case.dn.pos})
        og = owner_from_seam(W, seam_gold(case) - y0)
        tk = exp1[case.id]["topk"]["chosen"]
        fa = tk["above"]["fused"] if tk.get("above") else []; fb = tk["below"]["fused"] if tk.get("below") else []
        hyps = {"gold": (case.char_above, case.char_below)}
        if fa and fb:
            hyps["top1"] = (fa[0], fb[0])
        if len(fa) > 1 and len(fb) > 1:
            hyps["rank2"] = (fa[1], fb[1])
            hyps["swap_a"] = (fa[1], fb[0]); hyps["swap_b"] = (fa[0], fb[1])
        rec = {"id": case.id, "verdict": case.verdict, "pair": case.char_above + case.char_below,
               "top1_correct": bool(fa and fb and fa[0] == case.char_above and fb[0] == case.char_below),
               "hyps": {k: "".join(v) for k, v in hyps.items()}, "err": {}}
        tcache = {}
        for name, (ca, cb) in hyps.items():
            for ch in (ca, cb):
                if ch not in tcache:
                    tcache[ch] = bank.get(ch, ch_h, exclude=exclude)
            TA, TB = tcache[ca], tcache[cb]
            if not TA or not TB:
                continue
            best = None
            for A in TA:
                for B in TB:
                    pa, pb, sc = reg.register(A, B)
                    if best is None or sc > best[0]:
                        best = (sc, A, pa, B, pb)
            owner = reg.partition(best[1], best[2], best[3], best[4])[0]
            n, blob = err_stats(owner, og)
            rec["err"][name] = {"px": n, "blob": blob, "cov": round(best[0], 4)}
        n, blob = err_stats(owner_from_seam(W, seam_chosen(case) - y0), og)
        rec["err"]["chosen"] = {"px": n, "blob": blob}
        if "swap_a" in rec["err"] and "swap_b" in rec["err"]:
            worse = max(("swap_a", "swap_b"), key=lambda k: rec["err"][k]["px"])
            rec["err"]["swap_worse"] = rec["err"][worse]
        per.append(rec)
        if (ci + 1) % 50 == 0:
            print(f"  {ci + 1}/{len(cases)} {time.time() - t0:.0f}s", flush=True)

    def agg_rows(rows, k):
        px = np.array([r["err"][k]["px"] for r in rows if k in r["err"]]); bl = np.array([r["err"][k]["blob"] for r in rows if k in r["err"]])
        return None if px.size == 0 else {"n": int(px.size), "px_mean": round(float(px.mean()), 1), "px_median": float(np.median(px)),
                                          "px_p90": float(np.percentile(px, 90)), "le20px": round(float((px <= 20).mean()), 4),
                                          "blob_ge60": round(float((bl >= 60).mean()), 4)}

    summary = {"n": len(per)}
    strata = {"all": per, "top1_correct": [r for r in per if r["top1_correct"]], "top1_wrong": [r for r in per if not r["top1_correct"]]}
    for sname, rows in strata.items():
        summary[sname] = {k: agg_rows(rows, k) for k in ("gold", "top1", "rank2", "swap_worse", "chosen")}
        print(f"\n== {sname} (n={len(rows)})  err_px mean / median / p90 | ≤20px | blob≥60")
        for k in ("gold", "top1", "rank2", "swap_worse", "chosen"):
            s = summary[sname][k]
            if s:
                print(f"  {k:10s} {s['px_mean']:6.1f} / {s['px_median']:4.0f} / {s['px_p90']:5.0f} | {s['le20px']:6.1%} | {s['blob_ge60']:6.1%}  (n={s['n']})")
    # 形近错身份的例子（rank2 与 gold 差不多）
    ex = [r for r in per if "rank2" in r["err"] and abs(r["err"]["rank2"]["px"] - r["err"]["gold"]["px"]) <= 15][:10]
    print("\n形近错身份也切对的例子：", [(r["id"], r["pair"], "→", r["hyps"]["rank2"], r["err"]["gold"]["px"], r["err"]["rank2"]["px"]) for r in ex])
    jdump(per, out / "per_case.json"); jdump(summary, out / "summary.json")
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
