# -*- coding: utf-8 -*-
"""S1 道：候选排序模型 vs 现行规则——按页分组折、按册留出、负担保，同页集同折对比。

输入 `build_table.py` 的 pickle。输出 markdown 报告（stdout）；`--save-model` 用全部 gold 页训练并写模型文件。

指标（都用 `find_horizontal_border` 口径的线，两端点各算）：
- 页误差 = max(|左端差|, |右端差|)；命中率 ≤3px / ≤6px；平均/最坏
- 单侧（宁下勿上，TOL=30）：过 / 切字（线在金标上方）/ 太低

负担保：inner14（只有内框线，口径不同）与等距抽样正文页，只数「模型改了多少页、改了多远」。
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from open_guji_cv.bottompeak_model.chooser import select  # noqa: E402
from open_guji_cv.bottompeak_model.model import GUARD_DEFAULTS, save_model  # noqa: E402
from open_guji_cv.bottompeak_model.signals import FEATURES  # noqa: E402

TOL_POS = 6.0        # 标签：候选与金标距离 ≤ 此值记正
TOL_ONESIDE = 30.0


def endpoint_d(page: dict, y: float) -> tuple[float, float]:
    """线（终点 y，slope）在页左/右端相对金标的差（正=在金标下方）。"""
    w, s = page["w"], page["slope"]
    yl = y + s * (0 - w / 2.0)
    yr = y + s * ((w - 1) - w / 2.0)
    return yl - page["y_left_abs"], yr - page["y_right_abs"]


def page_err(page, y):
    dl, dr = endpoint_d(page, y)
    return max(abs(dl), abs(dr)), min(dl, dr)


def make_clf(kind: str, seed: int = 0):
    if kind == "hgb":
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.06,
                                              l2_regularization=1.0, min_samples_leaf=8, random_state=seed)
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000))


def cand_frame(pages) -> pd.DataFrame:
    recs = []
    for pi, p in enumerate(pages):
        for ci, r in enumerate(p["rows"]):
            d = dict(r)
            d["pi"], d["ci"] = pi, ci
            if "y_left_abs" in p:
                e, _ = page_err(p, r["final"])
                d["err"] = e
                d["y"] = int(e <= TOL_POS)
            recs.append(d)
    return pd.DataFrame(recs)


def predict_pages(train_idx, test_idx, pages, df, kind, feats, guard):
    """训练集页训练、在测试页上选候选。返回 {页下标: 选中候选下标}、{页下标: 概率向量}。"""
    tr = df[df.pi.isin(train_idx)]
    clf = make_clf(kind)
    clf.fit(tr[feats], tr["y"])
    out, probs = {}, {}
    for pi in test_idx:
        sub = df[df.pi == pi]
        if len(sub) < 2:
            out[pi] = None
            continue
        p = clf.predict_proba(sub[feats])[:, 1]
        k_rule = int(np.flatnonzero(sub["is_rule"].values > 0)[0]) if (sub["is_rule"].values > 0).any() else None
        if k_rule is None:
            out[pi] = None
            continue
        out[pi] = select(sub["final"].tolist(), k_rule, p, guard)
        probs[pi] = p
    return out, probs


def summarize(name, errs, worsts):
    errs, worsts = np.array(errs), np.array(worsts)
    n = len(errs)
    ok = (worsts >= 0) & (worsts <= TOL_ONESIDE)
    above = worsts < 0
    low = worsts > TOL_ONESIDE
    return dict(方法=name, n=n, **{"≤3px": f"{100*(errs<=3).mean():.1f}%", "≤6px": f"{100*(errs<=6).mean():.1f}%"},
                平均=f"{errs.mean():.1f}", p90=f"{np.percentile(errs, 90):.1f}", 最坏=f"{errs.max():.1f}",
                单侧过=f"{ok.sum()} ({100*ok.mean():.1f}%)", 切字=int(above.sum()), 太低=int(low.sum()))


def evaluate(pages, gold_idx, df, kind, feats, guard, folds=5, seeds=(0, 1, 2)):
    """按页分组 K 折（多种子），汇总每页被选中的终点。返回 per-method 误差表。"""
    from sklearn.model_selection import KFold
    rule_e = [page_err(pages[i], pages[i]["rule_final"]) for i in gold_idx]
    res = {s: {} for s in seeds}
    for s in seeds:
        for tr, te in KFold(folds, shuffle=True, random_state=s).split(gold_idx):
            tri = [gold_idx[i] for i in tr]
            tei = [gold_idx[i] for i in te]
            sel, _ = predict_pages(tri, tei, pages, df, kind, feats, guard)
            res[s].update(sel)
    return res, rule_e


def rows_for(pages, gold_idx, sel_by_seed):
    """每个种子一行汇总；再返回逐页（取各种子中位的误差）用于明细。"""
    tables = []
    per_page = {i: [] for i in gold_idx}
    for s, sel in sel_by_seed.items():
        errs, worsts, switched = [], [], 0
        for i in gold_idx:
            p = pages[i]
            k = sel.get(i)
            y = p["rule_final"] if k is None else p["rows"][k]["final"]
            switched += int(k is not None and abs(y - p["rule_final"]) > 0.5)
            e, w = page_err(p, y)
            errs.append(e); worsts.append(w)
            per_page[i].append((e, w))
        tables.append((errs, worsts, switched))
    return tables, per_page


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--kind", default="hgb", choices=["hgb", "lr"])
    ap.add_argument("--margin", type=float, default=GUARD_DEFAULTS["margin"])
    ap.add_argument("--min-prob", type=float, default=GUARD_DEFAULTS["min_prob"])
    ap.add_argument("--up-slack", type=float, default=GUARD_DEFAULTS["up_slack"])
    ap.add_argument("--drop", default="", help="消融：逗号分隔的特征名，训练时去掉")
    ap.add_argument("--save-model", default="")
    ap.add_argument("--model-id", default="bottompeak_v1")
    a = ap.parse_args()

    pages = pickle.loads(Path(a.table).read_bytes())
    df = cand_frame(pages)
    feats = [f for f in FEATURES if f not in set(filter(None, a.drop.split(",")))]
    guard = {**GUARD_DEFAULTS, "margin": a.margin, "min_prob": a.min_prob, "up_slack": a.up_slack}
    gold_idx = [i for i, p in enumerate(pages) if p["kind"] == "gold"]
    other_idx = [i for i, p in enumerate(pages) if p["kind"] != "gold"]
    print(f"# 候选模型 vs 现行规则（{a.kind}，特征 {len(feats)}，护栏 {guard}）\n")
    print(f"gold {len(gold_idx)} 页；候选 {len(df[df.pi.isin(gold_idx)])} 条；有正例的页（天花板）"
          f"{int(df[df.pi.isin(gold_idx)].groupby('pi').y.max().sum())}/{len(gold_idx)}\n")

    rule = [page_err(pages[i], pages[i]["rule_final"]) for i in gold_idx]
    orc = []
    for i in gold_idx:
        best = min(pages[i]["rows"], key=lambda r: page_err(pages[i], r["final"])[0])
        orc.append(page_err(pages[i], best["final"]))
    out = [summarize("现行规则", [e for e, _ in rule], [w for _, w in rule])]
    out.append(summarize("候选里最佳(天花板)", [e for e, _ in orc], [w for _, w in orc]))

    # 1) 页分组 5 折 × 3 种子
    sel_by_seed, _ = evaluate(pages, gold_idx, df, a.kind, feats, guard)[0], None
    tables, per_page = rows_for(pages, gold_idx, sel_by_seed)
    for s, (errs, worsts, sw) in zip(sel_by_seed, tables):
        out.append(summarize(f"模型 页折 seed{s}（改 {sw} 页）", errs, worsts))

    # 2) 按册留出（vol02→vol03、vol03→vol02）
    by_book = {b: [i for i in gold_idx if pages[i]["book"] == b] for b in ("vol02", "vol03")}
    for tr_b, te_b in (("vol02", "vol03"), ("vol03", "vol02")):
        tei = by_book[te_b]
        sel, _ = predict_pages(by_book[tr_b], tei, pages, df, a.kind, feats, guard)
        errs, worsts = [], []
        rule_sub = []
        sw = 0
        for i in tei:
            p = pages[i]
            k = sel.get(i)
            y = p["rule_final"] if k is None else p["rows"][k]["final"]
            sw += int(k is not None and abs(y - p["rule_final"]) > 0.5)
            e, w = page_err(p, y)
            errs.append(e); worsts.append(w)
            rule_sub.append(page_err(p, p["rule_final"]))
        out.append(summarize(f"留出 {tr_b}→{te_b} 规则", [e for e, _ in rule_sub], [w for _, w in rule_sub]))
        out.append(summarize(f"留出 {tr_b}→{te_b} 模型（改 {sw} 页）", errs, worsts))
    print(pd.DataFrame(out).to_markdown(index=False))

    # 逐页：模型比规则好/坏
    med = {i: np.median([e for e, _ in per_page[i]]) for i in gold_idx}
    better = [i for i, (e, _) in zip(gold_idx, rule) if med[i] < e - 3]
    worse = [i for i, (e, _) in zip(gold_idx, rule) if med[i] > e + 3]
    print(f"\n页折（种子中位）：比规则好 >3px {len(better)} 页，差 >3px {len(worse)} 页")
    for i in worse:
        e0 = dict(zip(gold_idx, rule))[i][0]
        print(f"  变差 {pages[i]['book']}/{pages[i]['page']}: 规则 {e0:.1f} → 模型 {med[i]:.1f}")

    # 3) 负担保：全部 gold 训练，在 inner14 / body 页上看改了多少
    clf = make_clf(a.kind)
    trn = df[df.pi.isin(gold_idx)]
    clf.fit(trn[feats], trn["y"])
    print("\n## 负担保（模型用全部 gold 页训练）\n")
    for kind in ("inner14", "body"):
        idx = [i for i in other_idx if pages[i]["kind"] == kind]
        moved = []
        for i in idx:
            sub = df[df.pi == i]
            if len(sub) < 2 or not (sub["is_rule"] > 0).any():
                continue
            p = clf.predict_proba(sub[feats])[:, 1]
            kr = int(np.flatnonzero(sub["is_rule"].values > 0)[0])
            k = select(sub["final"].tolist(), kr, p, guard)
            if k != kr:
                moved.append((pages[i]["book"], pages[i]["page"],
                              float(sub["final"].iloc[k] - sub["final"].iloc[kr]), float(p[kr]), float(p[k])))
        print(f"- {kind}: {len(idx)} 页，模型改 {len(moved)} 页")
        for m in moved:
            print(f"    {m[0]}/{m[1]}: 移 {m[2]:+.1f}px（p现役 {m[3]:.2f} → p新 {m[4]:.2f}）")
    if a.save_model:
        fp = save_model(a.save_model, clf, feats, guard,
                        {"model_id": a.model_id, "kind": a.kind, "trained_on": f"gold {len(gold_idx)} 页",
                         "tol_pos": TOL_POS})
        print(f"\n模型已存 {a.save_model}（指纹 {fp}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
