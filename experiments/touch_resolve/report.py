# -*- coding: utf-8 -*-
"""把 exp1 / exp2 / exp3 / unet 的产出汇总成一份 markdown（stdout + out/report.md）。

    python experiments/touch_resolve/report.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from common import OUT_ROOT


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pct(x, d=1):
    return "—" if x is None else f"{100 * x:.{d}f}%"


def main() -> int:
    lines: list[str] = []
    P = lines.append
    e1s = load(OUT_ROOT / "exp1" / "summary.json"); e1p = load(OUT_ROOT / "exp1" / "per_case.json")
    if e1s:
        P("## 实验一 · 无整理本时识别器 top-k 对真字对的覆盖\n")
        P(f"用例 {e1s['n_cases']} 条（touching-cuts 金标里带上下字的），k={e1s['k']}。三种切法切半字图 → 现役 CNN 分类头 / embedding / RRF 融合。\n")
        P("| 切法 | 源 | 上半 @1/@5 | 下半 @1/@5 | 字对同进 3×3 | 5×5 | 10×10 |")
        P("|---|---|---|---|---|---|---|")
        for cond in ("straight", "chosen", "gold"):
            for src in ("cls", "emb", "fused"):
                t = e1s["table"]
                a = t[f"{cond}/{src}/above/all"]; b = t[f"{cond}/{src}/below/all"]; p = t[f"{cond}/{src}/pair/all"]
                P(f"| {cond} | {src} | {a['@1']}/{a['@5']} | {b['@1']}/{b['@5']} | {p['@3']} | {p['@5']} | {p['@10']} |")
        # label 可信度
        if e1p:
            bad = [r for r in e1p if any((r['rank']['gold'][f'fused_{s}'] is None or r['rank']['gold'][f'fused_{s}'] > 5) for s in ('above', 'below'))]
            P(f"\ngold 切法下 fused@5 漏网 {len(bad)}/{len(e1p)} 条；人工看图：约半数是**金标字对与图像不符**（整理本对齐错位或整理本与刻本用字不同），"
              f"不是识别失败。后续实验以「标签可信 = gold 切法下两侧 fused@5 都命中」分层。\n")
    for src in ("glyph", "font"):
        e2s = load(OUT_ROOT / f"exp2_{src}" / "summary.json"); e2p = load(OUT_ROOT / f"exp2_{src}" / "per_case.json")
        if not e2s:
            continue
        P(f"## 实验二 · 成对校验（模板源 {src}）\n")
        A = e2s["A_pair_verify"]
        P(f"假设集 = 真字对 ∪ 识别 top-3×top-3；每对做联合配准取贴合度 cov。n={A['n_scored']}。\n")
        P("| 排序依据 | 真字对排第一 |")
        P("|---|---|")
        P(f"| 贴合度 cov | {pct(A['true_top1_by_cov'])} |")
        P(f"| CNN 概率乘积 | {pct(A['true_top1_by_cnn'])} |")
        if e2p and e1p:
            e1 = {r["id"]: r for r in e1p}
            ok = []
            for r in e2p:
                if r.get("true_top1_cov") is None or r["id"] not in e1:
                    continue
                rk = e1[r["id"]]["rank"]["gold"]
                if rk["fused_above"] and rk["fused_above"] <= 5 and rk["fused_below"] and rk["fused_below"] <= 5:
                    ok.append(r)
            if ok:
                cov1 = np.mean([r["true_top1_cov"] for r in ok]); cnn1 = np.mean([r["true_top1_cnn"] for r in ok])
                # 组合：cov 与 cnn 名次相加
                comb = []
                for r in ok:
                    hy = [h for h in r["hyps"] if h["cov"] is not None]
                    if len(hy) < 2:
                        comb.append(True); continue
                    covs = sorted(hy, key=lambda h: -h["cov"]); cnns = sorted(hy, key=lambda h: -h["cnn"])
                    rank = {h["pair"]: i for i, h in enumerate(covs)}; rank2 = {h["pair"]: i for i, h in enumerate(cnns)}
                    best = min(hy, key=lambda h: rank[h["pair"]] + rank2[h["pair"]])
                    comb.append(best["pair"] == r["pair"])
                P(f"| 贴合度 cov（标签可信子集 n={len(ok)}） | {pct(cov1)} |")
                P(f"| CNN 概率乘积（同子集） | {pct(cnn1)} |")
                P(f"| cov 名次 + CNN 名次（同子集） | {pct(float(np.mean(comb)))} |")
                margins = np.array([r["margin_cov"] for r in ok])
                P(f"\n真字对 cov 与最强竞争对的间隔：中位 {np.median(margins):.3f}，p10 {np.percentile(margins, 10):.3f}，<0 的占 {pct(float((margins < 0).mean()))}。\n")
        B = e2s["B_partition_agreement"]
        P(f"像素级归属一致率（钝尺子，仅供参考）：partition {B['partition']:.4f} / chosen {B['chosen']:.4f} / straight {B['straight']:.4f} / best_cand {B['best_cand']:.4f}。\n")
        C1, C0 = e2s["C_recog_after_partition"], e2s["C_recog_chosen_cut"]
        P(f"归属后半字识别 fused@1：partition {pct(C1['@1'])} vs 现役切法 {pct(C0['@1'])}（n={C1['n']}）。\n")
    for src in ("glyph", "font"):
        e3 = load(OUT_ROOT / f"exp3_{src}" / "summary.json")
        if not e3:
            continue
        P(f"## 实验三 · 模板给像素归属（模板源 {src}，只配准真字对）\n")
        P("尺子相对人工金标缝：err_px 错归属墨像素数；blob≥60 = 有一笔大小的块划错边。\n")
        for sname in ("label_ok+poly", "label_ok", "label_ok/seam_ok", "label_ok/moved", "label_ok/ok", "label_ok/overlap"):
            s = e3["err"].get(sname)
            if not s or not s.get("partition"):
                continue
            P(f"**{sname}**（n={s['partition']['n']}）\n")
            P("| 归属 | err_px mean / median / p90 | ≤20px | blob≥60 | blob≥150 |")
            P("|---|---|---|---|---|")
            for k in ("partition", "derived_seam", "chosen", "straight", "best_cand"):
                x = s.get(k)
                if x:
                    P(f"| {k} | {x['px_mean']} / {x['px_median']:.0f} / {x['px_p90']:.0f} | {pct(x['le20px'])} | {pct(x['blob_ge60'])} | {pct(x['blob_ge150'])} |")
            P("")
        rb = e3["recog_both_top1"]["label_ok"]
        P(f"两侧都 top-1 命中真字（label_ok）：partition {rb['partition']} / chosen {rb['chosen']} / gold 切法 {rb['gold']}。")
        P(f"partition vs chosen 逐条（err_px 容差 10）：{e3['partition_vs_chosen_label_ok']}\n")
    e5 = load(OUT_ROOT / "exp5" / "summary.json")
    if e5:
        P("## 实验五 · 像素归属对身份假设的敏感度（标签可信 + 带折线）\n")
        P("同一套模板归属，只换身份来源。rank2 = 每侧故意取识别第 2 名（错但形近）。\n")
        for sname in ("all", "top1_correct", "top1_wrong"):
            d = e5.get(sname)
            if not d or not d.get("gold"):
                continue
            P(f"**{sname}**（n={d['gold']['n']}）\n")
            P("| 身份来源 | err_px mean / median / p90 | ≤20px | blob≥60 |")
            P("|---|---|---|---|")
            for k in ("gold", "top1", "rank2", "swap_worse", "chosen"):
                x = d.get(k)
                if x:
                    P(f"| {k} | {x['px_mean']} / {x['px_median']:.0f} / {x['px_p90']:.0f} | {pct(x['le20px'])} | {pct(x['blob_ge60'])} |")
            P("")
    e4 = load(OUT_ROOT / "exp4" / "summary.json")
    if e4:
        P("## 实验四 · 字形库纯度（半字块 vs 库中同字刻例的弹性 cov，越高越干净）\n")
        P("| 归属 | cov mean / median / p10 | 过 same 闸 |")
        P("|---|---|---|")
        for k in ("gold", "chosen", "straight", "partition", "unet"):
            x = e4.get(k)
            if x:
                P(f"| {k} | {x['mean']} / {x['median']} / {x['p10']} | {pct(x['same_rate'])} |")
        for k in ("partition", "unet"):
            if e4.get(f"{k}_vs_chosen"):
                P(f"\n{k} vs chosen（同侧比，容差 0.005）：{e4[f'{k}_vs_chosen']}")
        P("")
    for d in sorted(OUT_ROOT.glob("unet_*")):
        u = load(d / "summary.json")
        if not u:
            continue
        P(f"## 档 3 · 类别无关归属网络（{d.name}）\n")
        for sname in ("label_ok+poly", "poly", "label_ok", "all", "label_ok/seam_ok", "label_ok/moved"):
            s = u["err"].get(sname)
            if not s or not s.get("unet"):
                continue
            x, c = s["unet"], s["chosen"]
            P(f"- **{sname}**（n={x['n']}）err_px mean unet {x['px_mean']} vs chosen {c['px_mean']}；median {x['px_median']:.0f} vs {c['px_median']:.0f}；p90 {x['px_p90']:.0f} vs {c['px_p90']:.0f}；blob≥60 {pct(x['blob_ge60'])} vs {pct(c['blob_ge60'])}")
        rb = u["recog_both_top1"].get("label_ok")
        if rb:
            P(f"- 两侧都 top-1（label_ok）：unet {rb['unet']} vs chosen {rb['chosen']}")
        P("")
    text = "\n".join(lines)
    (OUT_ROOT / "report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
