# -*- coding: utf-8 -*-
"""用 sheldon 第一轮复审裁决（review_round1_verdicts.jsonl）改正金标后，重算 L1 / haiku / L1→haiku 的准确率。
金标改正：复审过且裁成组内字 → 以裁决为准；裁成「其他字」或「拿不准」→ 该格出分母（成员字外 / 无法判定）。
可评格：有字块图、前后文各 ≥ MIN_SIDE 字（页首页尾的短上下文是建集的人为现象，生产里跨页连读不会短）、金标（改正后）在组内。
未进复审页的强真值格：四个模型一致且与金标一致、haiku 置信 high，按金标算。
python eval_corrected.py"""
import json, sys, collections
from pathlib import Path
sys.path.insert(0, "/home/user/open-guji-cv"); sys.path.insert(0, str(Path(__file__).parent))
from common import *
from open_guji_cv.groups.ctx_l1 import CtxL1Backend
from open_guji_cv.groups.ctx_l3 import parse_output
from open_guji_cv.groups.registry import GROUPS

R = Path(__file__).parent / "l2_results"; MODELS = ("opus", "sonnet", "haiku", "muse", "gemini"); MIN_SIDE = 8
V = {}
for f in ("review_round1_verdicts.jsonl", "review_round2_verdicts.jsonl", "review_semantic_overrides.jsonl"):      # 后者覆盖前者；semantic_overrides＝形近字按文意定（sheldon 10-17），覆盖按刻字选的两格
    for l in (R / f).open(encoding="utf-8"):
        x = json.loads(l); V[x["id"]] = x["verdict"]

def has_img(g, i): return (CG / g / "crops" / (i.replace(":", "_") + ".png")).exists()

def main(verbose=False):
    out = {}
    for g in ("jys", "ry", "rr"):
        fam = set(FAMILY[g]); spec = GROUPS[g]
        l1 = CtxL1Backend(f"/home/user/open-guji-cv/{spec.config_dir}/rules.yaml", spec.members)
        man = json.load(open(R / f"{g}_manifest.json")); runs = {}
        for m in MODELS:
            d = {}
            for n in man: d.update(parse_output((R / m / f"{n}.json").read_text(encoding="utf-8")))
            runs[m] = d
        tot = collections.Counter(); errs = []
        for r in load(g):
            if r["gold_tier"] not in STRONG: continue
            i = r["id"]; gold = r["gold"]; tot["strong"] += 1
            if i in V:
                if V[i] in fam: gold = V[i]
                else: tot["excl_review_other_idk"] += 1; continue
            if gold not in fam: tot["excl_out_of_family"] += 1; continue
            if not has_img(g, i): tot["excl_no_img"] += 1; continue
            l, rt = window(r)
            if min(len(l), len(rt)) < MIN_SIDE: tot["excl_short_ctx"] += 1; continue
            tot["eval"] += 1
            c1, w1, _ = l1.decide(l, rt)
            picks = [("L1", c1)]
            for m in MODELS:
                hv = runs[m].get(i, {}); hc = hv.get("char") if hv.get("conf") == "high" and hv.get("char") in fam else None
                picks += [(m + "_high", hc), ("L1→" + m, c1 or hc)]
            for nm, ch in picks:
                tot[nm + ":give"] += ch is not None; tot[nm + ":ok"] += ch == gold
                if ch is not None and ch != gold: errs.append((nm, i, gold, ch, l[-8:] + "？" + rt[:8]))
        out[g] = (tot, errs)
        print(f"\n== {g}  强真值 {tot['strong']}  可评 {tot['eval']}（剔: 复审其他/拿不准 {tot['excl_review_other_idk']}, 成员字外 {tot['excl_out_of_family']}, 无图 {tot['excl_no_img']}, 上下文短 {tot['excl_short_ctx']}）")
        for nm in ["L1"] + [x for m in MODELS for x in (m + "_high", "L1→" + m)]:
            n, k, ok = tot["eval"], tot[nm + ":give"], tot[nm + ":ok"]
            print(f"  {nm:14s} 给字 {k}/{n} 覆盖 {k/n:.1%}  对 {ok}  准确率 {ok/k:.1%}  Wilson下界 {wilson_lo(ok,k):.3f}" if k else f"  {nm} 无")
        for e in errs: print("   ERR", e)
    return out
if __name__ == "__main__": main()
