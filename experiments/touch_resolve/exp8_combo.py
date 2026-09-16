# -*- coding: utf-8 -*-
"""实验八：两个裁判合议——U-Net 一致率（实验七）× 模板贴合度（实验四）在候选池里选缝，外加一个交叉验证的小型学习选择器。

    python experiments/touch_resolve/exp8_combo.py

数据：out/exp7/per_case.json（逐候选 agree_w / dis_unet / seam_ink / dev_max / err，新金标）
   × out/exp4_glyph/per_case.json（逐候选模板贴合度 fits[kind].min / covA / covB，与金标无关，可直接复用）。
规则：
  R_fit(δ)   A 的规则：候选贴合度比现役缝高出 ≥ δ 才推翻（在新金标 673 条上复核）
  R_agree    实验七 S1：agree_w 最高
  R_both(δ)  两个裁判都指向同一条替代候选才换（agree_w 更高 且 fit 高出 ≥ δ），否则现役缝
  R_any(δ)   任一裁判明显偏好就换：先按 fit(δ)，没换再按 agree_w 是否比现役高出 ≥ 0.01
  R_*+U(T)   在上面之后，若选中候选与 U-Net 的分歧最大块 ≥ T 且 U-Net 在该块上很确定 → 改用 U-Net 归属（用 dis_unet 近似）
学习：逐候选 softmax 排序器（线性，torch），特征 = [agree_w, agree, log1p dis_unet, log1p dis_chosen, log1p seam_ink, log1p dev_max,
      is_chosen, fit_min, fit_covA, fit_covB, fit_missing, kind one-hot]，标签 = 该条里 (blob, px) 最小的候选；按页分 5 折交叉验证，
      报折外结果。U-Net 归属也作为一个池成员参与（agree_w=1, dis_unet=0, fit 缺失）。
"""
from __future__ import annotations

import json
import math
import random

import numpy as np

from common import OUT_ROOT, jdump

KINDS = ("straight", "seam_narrow", "seam_wide", "chosen", "unet")


def load():
    e7 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp7" / "per_case.json").read_text(encoding="utf-8"))}
    e4 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp4_glyph" / "per_case.json").read_text(encoding="utf-8"))}
    rows = []
    for i, r in e7.items():
        if not r["label_ok"]:
            continue
        fits = (e4.get(i) or {}).get("fits") or {}
        members = []
        for cd in r["cands"]:
            f = fits.get(cd["kind"]) or (fits.get("straight") if cd["kind"] == "chosen" else None)
            members.append({**cd, "fit": f})
        members.append({"kind": "unet", "is_chosen": False, "err": r["unet"], "agree": 1.0, "agree_w": 1.0,
                        "dis_unet": 0, "dis_chosen": max((cd["dis_unet"] for cd in r["cands"] if cd["is_chosen"]), default=0),
                        "seam_ink": -1, "dev_max": -1, "fit": None})
        rows.append({"id": i, "verdict": r["verdict"], "page": f"{r['book']}:{r['page']}", "members": members})
    return rows


def agg(errs):
    px = np.array([e["px"] for e in errs]); bl = np.array([e["blob"] for e in errs])
    return {"n": int(px.size), "px_mean": round(float(px.mean()), 1), "px_median": float(np.median(px)),
            "le20px": round(float((px <= 20).mean()), 4), "blob_ge60": round(float((bl >= 60).mean()), 4),
            "blob_ge150": round(float((bl >= 150).mean()), 4)}


def fmt(x):
    return f"{x['px_mean']:7.1f} {x['px_median']:6.0f} {x['le20px']:7.1%} {x['blob_ge60']:8.1%} {x['blob_ge150']:8.1%}"


def geo(r):
    return [m for m in r["members"] if m["kind"] != "unet"]


def chosen(r):
    return next(m for m in r["members"] if m["is_chosen"])


def unet(r):
    return next(m for m in r["members"] if m["kind"] == "unet")


def fitmin(m):
    return m["fit"]["min"] if m.get("fit") else None


def rule_fit(delta):
    def f(r):
        ch = chosen(r); base = fitmin(ch)
        best = ch
        for m in geo(r):
            fm = fitmin(m)
            if fm is not None and base is not None and fm - base >= delta and (fitmin(best) is None or fm > fitmin(best)):
                best = m
        return best
    return f


def rule_agree(r):
    return max(geo(r), key=lambda m: (m["agree_w"], m["is_chosen"]))


def rule_both(delta):
    def f(r):
        ch = chosen(r); base = fitmin(ch)
        cands = [m for m in geo(r) if not m["is_chosen"] and m["agree_w"] > ch["agree_w"]
                 and fitmin(m) is not None and base is not None and fitmin(m) - base >= delta]
        return max(cands, key=lambda m: m["agree_w"]) if cands else ch
    return f


def rule_any(delta, eps=0.01):
    def f(r):
        ch = chosen(r)
        m = rule_fit(delta)(r)
        if m is not ch:
            return m
        b = rule_agree(r)
        return b if b["agree_w"] - ch["agree_w"] >= eps else ch
    return f


def with_unet(rule, T):
    def f(r):
        m = rule(r)
        return unet(r) if m["dis_unet"] >= T else m
    return f


def oracle(r):
    return min(r["members"], key=lambda m: (m["err"]["blob"], m["err"]["px"]))


def oracle_geo(r):
    return min(geo(r), key=lambda m: (m["err"]["blob"], m["err"]["px"]))


# ── 学习型排序器 ──
def feats(m):
    k = [1.0 if m["kind"] == kk else 0.0 for kk in KINDS]
    fit = m.get("fit") or {}
    return [m["agree_w"], m["agree"], math.log1p(max(m["dis_unet"], 0)), math.log1p(max(m["dis_chosen"], 0)),
            math.log1p(max(m["seam_ink"], 0)), math.log1p(max(m["dev_max"], 0)), 1.0 if m["is_chosen"] else 0.0,
            fit.get("min", 0.0) or 0.0, fit.get("covA", 0.0) or 0.0, fit.get("covB", 0.0) or 0.0, 0.0 if m.get("fit") else 1.0] + k


def train_ranker(train_rows, epochs=300, lr=0.05, wd=1e-3, seed=0):
    import torch
    torch.manual_seed(seed)
    X = [torch.tensor([feats(m) for m in r["members"]], dtype=torch.float32) for r in train_rows]
    y = []
    for r in train_rows:
        errs = [(m["err"]["blob"], m["err"]["px"]) for m in r["members"]]
        best = min(errs)
        y.append(torch.tensor([1.0 if e == best else 0.0 for e in errs]))
    allX = torch.cat(X); mu = allX.mean(0); sd = allX.std(0) + 1e-6
    w = torch.zeros(allX.shape[1], requires_grad=True); b = torch.zeros(1, requires_grad=True)
    opt = torch.optim.Adam([w, b], lr=lr, weight_decay=wd)
    for _ in range(epochs):
        opt.zero_grad(); loss = 0.0
        for x, t in zip(X, y):
            s = ((x - mu) / sd) @ w + b
            p = torch.log_softmax(s, 0)
            loss = loss - (p * (t / t.sum())).sum()
        (loss / len(X)).backward(); opt.step()
    return (w.detach(), b.detach(), mu, sd)


def apply_ranker(model, r):
    import torch
    w, b, mu, sd = model
    x = torch.tensor([feats(m) for m in r["members"]], dtype=torch.float32)
    s = ((x - mu) / sd) @ w + b
    return r["members"][int(torch.argmax(s))]


def main() -> int:
    rows = load()
    print(f"n={len(rows)}（label_ok，且实验四贴合度可用 {sum(1 for r in rows if fitmin(chosen(r)) is not None)}）")
    methods = {"chosen": chosen, "unet": unet, "R_agree(S1)": rule_agree}
    for d in (0.01, 0.015, 0.02, 0.03):
        methods[f"R_fit δ={d}"] = rule_fit(d)
    for d in (0.0, 0.01, 0.015):
        methods[f"R_both δ={d}"] = rule_both(d)
    for d in (0.015, 0.02):
        methods[f"R_any δ={d}"] = rule_any(d)
    for T in (150, 200):
        methods[f"R_any δ=0.015 +U(T={T})"] = with_unet(rule_any(0.015), T)
        methods[f"R_agree +U(T={T})"] = with_unet(rule_agree, T)
    methods["候选池上限"] = oracle_geo
    methods["全池上限"] = oracle
    out = {"n": len(rows), "label_ok": {}, "by_verdict": {}}
    print(f"{'method':28s} px_mean median  le20px  blob>=60 blob>=150")
    for name, f in methods.items():
        x = agg([f(r)["err"] for r in rows]); out["label_ok"][name] = x
        print(f"{name:28s} {fmt(x)}")
    # 学习型：按页 5 折
    pages = sorted({r["page"] for r in rows}); random.Random(0).shuffle(pages)
    folds = [set(pages[i::5]) for i in range(5)]
    picked = {}
    for k in range(5):
        tr = [r for r in rows if r["page"] not in folds[k]]; te = [r for r in rows if r["page"] in folds[k]]
        model = train_ranker(tr)
        for r in te:
            picked[r["id"]] = apply_ranker(model, r)
    x = agg([picked[r["id"]]["err"] for r in rows]); out["label_ok"]["学习排序器(5折页外)"] = x
    print(f"{'学习排序器(5折页外)':28s} {fmt(x)}")
    sel = {}
    for r in rows:
        sel[picked[r["id"]]["kind"]] = sel.get(picked[r["id"]]["kind"], 0) + 1
    print("  学习器选中分布:", sel)
    for v in ("seam_ok", "ok", "moved", "overlap"):
        rr = [r for r in rows if r["verdict"] == v]
        out["by_verdict"][v] = {name: agg([f(r)["err"] for r in rr]) for name, f in methods.items()}
        out["by_verdict"][v]["学习排序器(5折页外)"] = agg([picked[r["id"]]["err"] for r in rr])
        print(f"-- {v} n={len(rr)} blob>=150: " + "  ".join(f"{m}={out['by_verdict'][v][m]['blob_ge150']:.1%}" for m in ("chosen", "R_agree(S1)", "R_fit δ=0.015", "R_both δ=0.01", "R_any δ=0.015", "学习排序器(5折页外)", "全池上限")))
    jdump(out, OUT_ROOT / "exp8_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
