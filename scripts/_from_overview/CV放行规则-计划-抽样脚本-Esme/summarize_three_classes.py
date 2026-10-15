#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三类待审（切分坏／对齐改字／字组）看图回条汇总（Esme，GUJI-208en 件二，2026-10-14 洛杉矶）。

输入
  --sample  待审三类看图清单-Esme.csv（类,册,页,列,slot,格id,层,问题编号,产物字,cov,doubts）
  --layers  层总格数.csv（类,层,层总格数,层抽样格数）——加权用，来自抽样时的分层表
  --reply   Lucian 回条 CSV。约定列（没有他 208eb 格式时用这个）：
              格id,类,Q1,Q2,Q3,Q4,Q5,备注
            只填该类用到的列，其余留空：
              切分坏   Q1 框是否切坏 Y/N/看不清；Q2 若按现状放行会放出错字吗 Y/N/看不清
              对齐改字 Q3 改后字与图一致 Y/N/看不清；Q4 旧字与图一致 Y/N/看不清
              字组     Q5 一致写 Y；不一致写图上实际字或 N；看不清写「看不清」
            「格号对不上」：写在 Q 任一列或备注里，该格剔除，不算样本，也不换格。
输出  Markdown（stdout 或 --out）：每类的有效样本数、剔除数、每层原始计数、加权错放率、
      95% 区间、错放率单侧 95% 上界、结论一句话。

「错放」的定义（每类一个 0/1 指标 e；放行后会出错 = 1）
  切分坏   e = (Q2 == Y)
  对齐改字 e = (Q3 == N)        即按改后字放行会错；Q4 只作旁证单列，不进判据
  字组     e = (Q5 != Y 且 不是看不清)
  看不清／不定：单列计数 u；上界计算按最坏情况（全当错）算一次，写在「最坏上界」里。

加权：层权重 N_h/n_h（N_h＝层总格数，n_h＝该层有效样本数）。某层有效样本 0 → 该层无估计，
  从加权里去掉并在「覆盖」里写出缺的总格数比例。
区间：加权点估计 p̂；Kish 设计效应 deff = n·Σ(W_h²/n_h)（W_h＝N_h/ΣN_h，只含有样本的层），
  n_eff = n/deff，y_eff = round(p̂·n_eff)；用 n_eff,y_eff 做 Clopper–Pearson（双侧 95% 区间；
  p̂=0 时单侧 95% 上界＝1−0.05^(1/n_eff)）。这是保守近似，不是严格分层方差。

结论判据（红线是错放 0 ⇒ 判据以「有无观察到错放」与「错放率上界」为准）
  样本不足 ：有效样本 n < MIN_N；或缺层覆盖 > MAX_MISSING_COVER；或 无错放但 看不清 u > 0
             且最坏上界 > UPPER_OK
  不能降   ：观察到 ≥ 1 个确认错放（e=1 且不是看不清）。（红线 0 ⇒ 一个就够，除非 Mila 另定）
  安全可降（候选） ：无确认错放 且 u == 0 且 上界 ≤ UPPER_OK。注意「候选」：40 格样本最多证明
             上界 ≈ 7%，不证明 0；真要放需分层复核或小范围先试（待 Mila 定）。
  阈值已由 Mila 定案（GUJI-208ep，10-14）：MIN_N=30、MAX_MISSING_COVER=0.20、UPPER_OK=0.10；
  「看不清」按最坏情况全算错并单列格号；确认错放 ≥1 → 不能降（红线 0）。
  「安全可降（候选）」后固定加一行说明（见 CAND_NOTE）。
"""
from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

# ── 阈值（Mila 2026-10-14 定案，GUJI-208ep）────────────────────────────────
MIN_N = 30                 # 一类有效样本低于此数 → 样本不足
MAX_MISSING_COVER = 0.20   # 有样本缺失的层合计占该类总格数超过此比例 → 样本不足
UPPER_OK = 0.10            # 错放率单侧 95% 上界不超过此值才敢写「安全可降（候选）」
# ────────────────────────────────────────────────────────────────

CLASSES = ["切分坏", "对齐改字", "字组"]
RECEIPT = "GUJI-137 回执（GUJI-208en／208ep，Esme）：三类看图汇总脚本自测输出（固定种子 1，可复现）；阈值已由 Mila 定案；以下为合成数据，结论无意义。"
CAND_NOTE = "候选只表示不否决；要放必须小范围先试＋放行后随机抽检（Emi 抽检方案），红线仍是错放 0。"
UNSURE = {"看不清", "不定", "?", "？"}
MISMATCH = "格号对不上"


def _binom_cdf(k: int, n: int, p: float) -> float:
    if p <= 0:
        return 1.0
    if p >= 1:
        return 1.0 if k >= n else 0.0
    s = 0.0
    for i in range(0, k + 1):
        s += math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                      + i * math.log(p) + (n - i) * math.log(1 - p))
    return min(1.0, s)


def _cp_upper(y: int, n: int, alpha: float) -> float:
    """Clopper–Pearson 上界：使 P(X ≤ y | p) = alpha 的 p。"""
    if n <= 0:
        return 1.0
    if y >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _binom_cdf(y, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _cp_lower(y: int, n: int, alpha: float) -> float:
    if y <= 0 or n <= 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if 1 - _binom_cdf(y - 1, n, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def classify_cell(cls: str, r: dict, prod_char: str):
    """返回 (状态, e)：状态 ∈ valid / unsure / mismatch / missing。"""
    cells = [(r.get(k) or "").strip() for k in ("Q1", "Q2", "Q3", "Q4", "Q5")]
    note = (r.get("备注") or "").strip()
    if any(MISMATCH in c for c in cells) or MISMATCH in note:
        return "mismatch", None
    q1, q2, q3, q4, q5 = cells
    if cls == "切分坏":
        v = q2
        if not v:
            return "missing", None
        if v in UNSURE:
            return "unsure", None
        return "valid", 1 if v.upper() == "Y" else 0
    if cls == "对齐改字":
        v = q3
        if not v:
            return "missing", None
        if v in UNSURE:
            return "unsure", None
        return "valid", 1 if v.upper() == "N" else 0
    v = q5
    if not v:
        return "missing", None
    if v in UNSURE:
        return "unsure", None
    return "valid", 0 if (v.upper() == "Y" or (prod_char and v == prod_char)) else 1


def summarize(sample, layers, replies):
    rep = {r["格id"].strip(): r for r in replies if r.get("格id")}
    N = {(r["类"], r["层"]): int(r["层总格数"]) for r in layers}
    per = {c: defaultdict(lambda: dict(n=0, e=0, u=0, mm=0, miss=0, drawn=0)) for c in CLASSES}
    q4_side = {"Y": 0, "N": 0, "u": 0}
    for s in sample:
        c, lay = s["类"], s["层"]
        d = per[c][lay]
        d["drawn"] += 1
        r = rep.get(s["格id"])
        if r is None:
            d["miss"] += 1
            continue
        st, e = classify_cell(c, r, s.get("产物字", ""))
        if st == "valid":
            d["n"] += 1
            d["e"] += e
        elif st == "unsure":
            d["u"] += 1
            d.setdefault("uids", []).append(s["格id"])
        elif st == "mismatch":
            d["mm"] += 1
        else:
            d["miss"] += 1
        if c == "对齐改字":
            q4 = (r.get("Q4") or "").strip()
            if q4.upper() == "Y":
                q4_side["Y"] += 1
            elif q4.upper() == "N":
                q4_side["N"] += 1
            elif q4:
                q4_side["u"] += 1
    out = {}
    for c in CLASSES:
        L = per[c]
        Ntot = sum(v for (cc, _), v in N.items() if cc == c)
        n_valid = sum(d["n"] for d in L.values())
        e_obs = sum(d["e"] for d in L.values())
        u = sum(d["u"] for d in L.values())
        mm = sum(d["mm"] for d in L.values())
        miss = sum(d["miss"] for d in L.values())
        used = {lay: d for lay, d in L.items() if d["n"] > 0}
        Nused = sum(N[(c, lay)] for lay in used)
        missing_cover = 1 - Nused / Ntot if Ntot else 1.0
        if n_valid and Nused:
            p_hat = sum(N[(c, lay)] / Nused * d["e"] / d["n"] for lay, d in used.items())
            deff = n_valid * sum((N[(c, lay)] / Nused) ** 2 / d["n"] for lay, d in used.items())
        else:
            p_hat, deff = float("nan"), 1.0
        n_eff = n_valid / deff if deff else n_valid
        y_eff = round(p_hat * n_eff) if n_valid else 0
        ne = max(1, round(n_eff))
        if n_valid:
            if y_eff == 0:
                lo, hi2, up = 0.0, _cp_upper(0, ne, 0.025), _cp_upper(0, ne, 0.05)
            else:
                lo, hi2, up = _cp_lower(y_eff, ne, 0.025), _cp_upper(y_eff, ne, 0.025), _cp_upper(y_eff, ne, 0.05)
        else:
            lo = hi2 = up = float("nan")
        worst_y = min(ne, y_eff + round(u * (ne / max(n_valid + u, 1))))
        worst_up = _cp_upper(worst_y, ne, 0.05) if n_valid else float("nan")
        # 结论
        if n_valid < MIN_N or missing_cover > MAX_MISSING_COVER:
            verdict = "样本不足"
            why = f"有效样本 {n_valid}（门槛 {MIN_N}）；缺层覆盖 {missing_cover:.0%}（门槛 {MAX_MISSING_COVER:.0%}）"
        elif e_obs >= 1:
            verdict = "不能降"
            why = f"观察到 {e_obs} 个确认错放（红线错放 0）"
        elif u > 0 and worst_up > UPPER_OK:
            verdict = "样本不足"
            why = f"无确认错放，但 {u} 格看不清，最坏上界 {worst_up:.1%} > {UPPER_OK:.0%}"
        elif up <= UPPER_OK and u == 0:
            verdict = "安全可降（候选）"
            why = f"无确认错放，错放率 95% 单侧上界 {up:.1%} ≤ {UPPER_OK:.0%}（仍不证明为 0）"
        else:
            verdict = "样本不足"
            why = f"无确认错放，但上界 {up:.1%} > {UPPER_OK:.0%} 或有看不清"
        out[c] = dict(Ntot=Ntot, n_valid=n_valid, e_obs=e_obs, u=u, mm=mm, miss=miss,
                      p_hat=p_hat, lo=lo, hi=hi2, up=up, worst_up=worst_up, deff=deff,
                      u_ids=[i for d in L.values() for i in d.get('uids',[])], n_eff=n_eff, missing_cover=missing_cover, verdict=verdict, why=why,
                      layers=L, N=N)
    return out, q4_side


def render(out, q4_side):
    o = ["# 三类看图汇总（脚本输出）", "",
         f"判据阈值（待 Mila 定）：MIN_N={MIN_N}，MAX_MISSING_COVER={MAX_MISSING_COVER:.0%}，UPPER_OK={UPPER_OK:.0%}。", ""]
    o += ["| 类 | 总格数 | 有效样本 | 确认错放 | 看不清 | 格号对不上（剔除） | 未回 | 加权错放率 | 95% 区间 | 单侧 95% 上界 | 结论 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c, r in out.items():
        f = lambda x: "—" if x != x else f"{x:.1%}"
        o.append(f"| {c} | {r['Ntot']} | {r['n_valid']} | {r['e_obs']} | {r['u']} | {r['mm']} | {r['miss']} | "
                 f"{f(r['p_hat'])} | [{f(r['lo'])}, {f(r['hi'])}] | {f(r['up'])} | **{r['verdict']}** |")
    o.append("")
    for c, r in out.items():
        o.append(f"## {c}")
        o.append(f"- 结论：**{r['verdict']}**——{r['why']}。")
        o.append(f"- 设计效应 deff={r['deff']:.2f}，有效样本 n_eff={r['n_eff']:.1f}；缺层覆盖 {r['missing_cover']:.0%}；"
                 f"最坏上界（看不清全当错）{'—' if r['worst_up']!=r['worst_up'] else format(r['worst_up'],'.1%')}。")
        if c == "对齐改字":
            o.append(f"- 旁证 Q4（旧字与图一致）：Y {q4_side['Y']}／N {q4_side['N']}／其他 {q4_side['u']}。")
        if r["u_ids"]:
            o.append(f"- 看不清的格（请 Lucian／Ezio 补看）：{'、'.join(r['u_ids'])}")
        if r["verdict"].startswith("安全可降"):
            o.append(f"- {CAND_NOTE}")
        o.append("")
        o.append("| 层 | 层总格数 | 抽样 | 有效 n | 确认错放 | 看不清 | 格号对不上 | 未回 |")
        o.append("|---|---|---|---|---|---|---|---|")
        for lay in sorted(r["layers"]):
            d = r["layers"][lay]
            o.append(f"| {lay} | {r['N'][(c, lay)]} | {d['drawn']} | {d['n']} | {d['e']} | {d['u']} | {d['mm']} | {d['miss']} |")
        o.append("")
    o.append("小样本提示：每类 40 格只能外推到类级，不外推到册或层；结论是看图＋文本一致，不是人裁。")
    return "\n".join(o)


def selftest(sample, outdir, seed=1):
    """造一份随机合成回条（每类设不同的真实错放率，加少量看不清／格号对不上）。"""
    rng = random.Random(seed)
    rate = {"切分坏": 0.25, "对齐改字": 0.0, "字组": 0.0}
    rows = []
    for s in sample:
        c = s["类"]
        row = dict(格id=s["格id"], 类=c, Q1="", Q2="", Q3="", Q4="", Q5="", 备注="")
        x = rng.random()
        if x < 0.05:
            row["备注"] = MISMATCH
        elif x < 0.10:
            for k in {"切分坏": ("Q1", "Q2"), "对齐改字": ("Q3", "Q4"), "字组": ("Q5",)}[c]:
                row[k] = "看不清"
        else:
            bad = rng.random() < rate[c]
            if c == "切分坏":
                row["Q1"] = "Y" if bad else rng.choice("YN"); row["Q2"] = "Y" if bad else "N"
            elif c == "对齐改字":
                row["Q3"] = "N" if bad else "Y"; row["Q4"] = rng.choice("YN")
            else:
                row["Q5"] = "Y" if not bad else (s["产物字"] or "?") + "x"
        rows.append(row)
    p = Path(outdir) / "合成回条-自测.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["格id", "类", "Q1", "Q2", "Q3", "Q4", "Q5", "备注"])
        w.writeheader(); w.writerows(rows)
    return p


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=str(here.parent / "待审三类看图清单-Esme.csv"))
    ap.add_argument("--layers", default=str(here / "层总格数.csv"))
    ap.add_argument("--reply")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true", help="造合成回条并跑通，输出到本目录")
    a = ap.parse_args()
    sample, layers = read_csv(a.sample), read_csv(a.layers)
    if a.selftest:
        reply = selftest(sample, here)
        out, q4 = summarize(sample, layers, read_csv(reply))
        txt = RECEIPT + "\n\n（合成回条自测：数据随机生成，仅验证脚本跑得通，结论无意义。）\n\n" + render(out, q4)
        (here / "自测输出.md").write_text(txt, encoding="utf-8")
        print(txt)
        return
    if not a.reply:
        sys.exit("需要 --reply 回条 CSV（或 --selftest）")
    out, q4 = summarize(sample, layers, read_csv(a.reply))
    txt = render(out, q4)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
