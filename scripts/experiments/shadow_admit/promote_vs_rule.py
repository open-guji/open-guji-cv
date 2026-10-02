# -*- coding: utf-8 -*-
"""规则 A（`seed_admit.rare_ref`）vs 影子升级（`shadow_promote`）vs 两者合用——同一人裁集上的正面比（overview#349 D3 道）。

输入（全部来自 guji-workspace 孤儿分支 snap/<ws>/<vol>/<ts> 解出的 products，见 HANDOFF_D3.md「复现」）：
  --up    book=<上游 products 目录>   含 glyph_match / rare_candidates / align_ref（Step5–7 产物，人裁前口径）
  --human book=<含 human 通道的 seed_admit 目录>   人裁标签 = channel=="human" 的格
  --base  book=<seed_admit 目录>      沙箱重跑、`use_human_verdicts=false` 且 rare_ref 关：人裁前的待审/放行与 doubts
  --rule  book=<seed_admit 目录>      同上但 rare_ref 开：命中 = channel=="rare_ref"（线上代码的真实输出，非离线重算）
  --db    glyph.db（`glyph-db rebuild` 出）

评测域 U = 人裁格里「人裁前待审（base admit=False）且无硬护栏」的格——三种方法都只在 U 上动手，只升不降。
折：`page5`（按 (书,页) 分组 5 折，两册合训）、`xbook`（vol02↔vol03 互相留出）。
模型信号 = `open_guji_cv.shadow.signals`（v2），分类器同 `scripts/shadow_gate_train.py`。

    python scripts/experiments/shadow_admit/promote_vs_rule.py --up vol02=… --human vol02=… --base vol02=… --rule vol02=… \
        --up vol03=… … --db glyph.db --out results_d3 [--train-domain all|U] [--save-model models/shadow_admit/shadow_gate_v2.joblib]
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from open_guji_cv.shadow.gate import decide_promote  # noqa: E402
from open_guji_cv.shadow.signals import FEATURES, CellEvidence, build_rows, jmerge, load_context  # noqa: E402
from open_guji_cv.steps.seed_admit import _hard_blocked  # noqa: E402


def make_clf():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                          l2_regularization=1.0, random_state=0)


def _cells(d: str, kind: str) -> dict:
    out = {}
    for f in glob.glob(f"{d}/p*.json"):
        doc = json.load(open(f, encoding="utf-8"))[kind]
        if kind == "align_ref":
            for r in doc["chars"]:
                out[r["id"]] = r
        else:
            for c in doc["columns"]:
                for r in c.get("chars") or []:
                    out[r["id"]] = r
    return out


def assemble(book: str, up: str, human: str, base: str, rule: str) -> list[dict]:
    H = {i: r for i, r in _cells(human, "seed_admit").items() if r["channel"] == "human"}
    B, R = _cells(base, "seed_admit"), _cells(rule, "seed_admit")
    G, RC, A = (_cells(f"{up}/{k}", k) for k in ("glyph_match", "rare_candidates", "align_ref"))
    cells = []
    for i, h in H.items():
        g, b = G.get(i), B.get(i)
        if g is None or b is None:
            continue
        a = A.get(i) or {}
        ev = CellEvidence(id=i, lib=[(c, v) for c, v in g["candidates"]],
                          rare=[(x["char"], x["score"]) for x in ((RC.get(i) or {}).get("candidates") or [])],
                          ref=a.get("align_char"), cur=b["char"])
        cells.append(dict(id=i, book=book, page=int(i.split(":")[1]), label=h["char"], ev=ev,
                          op=a.get("align_op"), base_admit=b["admit"], base_char=b["char"],
                          blocked=_hard_blocked(b["doubts"], g["guard"]),
                          rule_hit=R[i]["channel"] == "rare_ref", rule_char=R[i]["char"]))
    return cells


def featurize(cells: list[dict], ctx) -> pd.DataFrame:
    rows = []
    for c in cells:
        lab = jmerge(c["label"])
        for r in build_rows(c["ev"], ctx):
            rows.append({"id": c["id"], "book": c["book"], "page": c["page"], "label": int(r["cand"] == lab), **r})
    return pd.DataFrame(rows)


def predict(df: pd.DataFrame, cells: list[dict], train_ids: set, test_ids: set, feats) -> dict:
    """→ {cell id: (pick, conf)}；逐格归一。"""
    tr = df[df["id"].isin(train_ids)]
    clf = make_clf().fit(tr[list(feats)], tr["label"])
    te = df[df["id"].isin(test_ids)].copy()
    te["s"] = clf.predict_proba(te[list(feats)])[:, 1]
    te["conf"] = te["s"] / te.groupby("id")["s"].transform("sum").clip(lower=1e-9)
    best = te.loc[te.groupby("id")["conf"].idxmax()]
    return {r.id: (r.cand, float(r.conf)) for r in best.itertuples()}


def run_folds(df, cells, scheme: str, feats, train_domain: str) -> dict:
    from sklearn.model_selection import GroupKFold
    pool = [c for c in cells if train_domain == "all" or (not c["base_admit"] and not c["blocked"])]
    out: dict = {}
    if scheme == "page5":
        ids = [c["id"] for c in pool]
        groups = [(c["book"], c["page"]) for c in pool]
        gid = pd.factorize(pd.Series(groups))[0]
        for tr, te in GroupKFold(n_splits=5).split(ids, groups=gid):
            test = {ids[k] for k in te}
            out.update(predict(df, cells, {ids[k] for k in tr}, test, feats))
        # U 里不在训练域（train_domain=U 时全在；all 时 U ⊂ all）——补算不在池里的格不需要
    else:
        books = sorted({c["book"] for c in cells})
        for tb in books:
            tr = {c["id"] for c in pool if c["book"] != tb}
            te = {c["id"] for c in pool if c["book"] == tb}
            out.update(predict(df, cells, tr, te, feats))
    return out


def fam(vm, c):
    return vm.semantic(jmerge(c)) if c else c


def main():
    ap = argparse.ArgumentParser()
    for k in ("up", "human", "base", "rule"):
        ap.add_argument(f"--{k}", action="append", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--train-domain", default="all", choices=["all", "U"])
    ap.add_argument("--features", default="v2", choices=["v1", "v2"])
    ap.add_argument("--save-model", default="")
    a = ap.parse_args()
    from open_guji_cv.clustering.variants import VariantMap
    vm = VariantMap.load(None)
    kv = lambda L: dict(x.split("=", 1) for x in L)  # noqa: E731
    up, hu, ba, ru = kv(a.up), kv(a.human), kv(a.base), kv(a.rule)
    cells = [c for b in up for c in assemble(b, up[b], hu[b], ba[b], ru[b])]
    ctx = load_context(a.db)
    df = featurize(cells, ctx)
    from open_guji_cv.shadow.signals import FEATURES_V1
    feats = list(FEATURES if a.features == "v2" else FEATURES_V1)
    byid = {c["id"]: c for c in cells}
    U = [c for c in cells if not c["base_admit"] and not c["blocked"]]
    cnt = lambda xs: ", ".join(f"{b} {sum(c['book'] == b for c in xs)}" for b in up)  # noqa: E731
    L = ["# 规则 A vs 影子升级 vs 合用（人裁集，评测域 U）\n",
         f"人裁格 {len(cells)}（{cnt(cells)}）；U（人裁前待审且无硬护栏）{len(U)}（{cnt(U)}）。"
         f"特征 {a.features}（{len(feats)} 个），训练域 {a.train_domain}。\n"]
    res_json = {}
    for scheme in ("page5", "xbook"):
        pred = run_folds(df, cells, scheme, feats, a.train_domain)
        Up = [c for c in U if c["id"] in pred]
        n_cov = len(Up)

        def stat(sel):                       # sel: [(cell, char)]
            ex = [(c, ch) for c, ch in sel if ch != c["label"]]
            fm = [(c, ch) for c, ch in sel if fam(vm, ch) != fam(vm, c["label"])]
            return len(sel), len(ex), len(fm), ex

        rule = [(c, c["rule_char"]) for c in Up if c["rule_hit"]]
        nA, eA, fA, exA = stat(rule)
        L.append(f"\n## 折：{scheme}（U 内有预测 {n_cov} 格）\n")
        L.append("| 方法 | 放行格 | 错（逐字） | 错（字族） |\n|---|---|---|---|")
        L.append(f"| 规则 A（线上 rare_ref 真实输出） | {nA} | {eA} | {fA} |")

        def promote_sel(thr):
            sel = []
            for c in Up:
                pick, conf = pred[c["id"]]
                v = decide_promote(pick, conf, c["ev"], thr)
                if v.promote:
                    ch = c["ev"].ref if (c["ev"].ref and jmerge(c["ev"].ref) == pick) else \
                        max(c["ev"].lib, key=lambda t: t[1])[0]
                    sel.append((c, ch))
            return sel

        sweep = []
        for thr in (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.93, 0.95, 0.97, 0.98, 0.99, 0.995):
            n, e, f, _ = stat(promote_sel(thr))
            sweep.append((thr, n, e, f))
            L.append(f"| 影子升级 conf≥{thr} | {n} | {e} | {f} |")
        # 合用：规则 A 候选，模型否决（模型首选 ≠ 规则字且把握度 ≥ τ）
        comb = []
        for tau in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
            sel = [(c, ch) for c, ch in rule if not (pred[c["id"]][0] != jmerge(ch) and pred[c["id"]][1] >= tau)]
            n, e, f, _ = stat(sel)
            comb.append((tau, n, e, f))
            L.append(f"| A + 模型否决 τ={tau} | {n} | {e} | {f} |")
        # 同放行量下的错数 / 同错数下的放行量
        L.append("\n同放行量（升级门槛调到放行数 ≥ 规则 A）：")
        ok = [r for r in sweep if r[1] >= nA]
        L.append("- 影子升级：" + (f"conf≥{ok[-1][0]} → 放行 {ok[-1][1]}，错 逐字 {ok[-1][2]} / 字族 {ok[-1][3]}（规则 A：{nA} 格，{eA}/{fA}）"
                                 if ok else f"门槛扫到 0.5 放行量也不足 {nA}（最多 {sweep[0][1]}）"))
        L.append(f"同错数（逐字错 ≤ 规则 A 的 {eA}）下的最大放行量：")
        okb = [r for r in sweep if r[2] <= eA]
        L.append("- 影子升级：" + (f"conf≥{okb[0][0]} → 放行 {okb[0][1]}" if okb else "无（最严门槛仍多错）"))
        L.append("- A + 模型否决：" + "；".join(f"τ={t}: {n} 格/错 {e}/{f}" for t, n, e, f in comb))
        # 重叠：规则 A 与影子升级各自放行的格怎么交叠（各取一个门槛）
        for thr in (0.95, 0.99):
            ps = {c["id"]: ch for c, ch in promote_sel(thr)}
            rs = {c["id"]: ch for c, ch in rule}
            both, only_r, only_p = set(ps) & set(rs), set(rs) - set(ps), set(ps) - set(rs)
            wrong = lambda ids, m: sum(m[i] != byid[i]["label"] for i in ids)  # noqa: E731
            L.append(f"\n重叠（升级 conf≥{thr}）：共同 {len(both)}（错 A {wrong(both, rs)} / 升级 {wrong(both, ps)}）；"
                     f"只规则 A {len(only_r)}（错 {wrong(only_r, rs)}）；只升级 {len(only_p)}（错 {wrong(only_p, ps)}）")
            rest = [c for c in Up if c["id"] not in ps and c["id"] not in rs]
            L.append(f"两者都没放行的 U 格 {len(rest)}（整理本无 {sum(not c['ev'].ref for c in rest)}、op=equal {sum(c['op']=='equal' for c in rest)}、"
                     f"5-b 首位≠整理本 {sum(bool(c['ev'].ref) and bool(c['ev'].rare) and c['ev'].rare[0][0] != c['ev'].ref for c in rest)}）")
        # 错例逐条
        L.append("\n### 错例（逐字口径；格 id、人裁字、放行字、整理本字、库首位、5-b 首位、模型首选/把握度）\n")
        for name, sel in (("规则 A", rule), ("影子升级 conf≥0.9", promote_sel(0.9))):
            for c, ch in sel:
                if ch != c["label"]:
                    ev = c["ev"]
                    L.append(f"- [{name}] {c['id']}：人裁 {c['label']} / 放行 {ch} / 整理本 {ev.ref} / "
                             f"库首位 {max(ev.lib, key=lambda t: t[1])[0] if ev.lib else None} / "
                             f"5-b首位 {ev.rare[0][0] if ev.rare else None} / 模型 {pred[c['id']][0]} {pred[c['id']][1]:.3f}")
        res_json[scheme] = {"rule": [nA, eA, fA], "promote": sweep, "combo": comb}
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / f"compare_{a.features}_{a.train_domain}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (Path(a.out) / f"compare_{a.features}_{a.train_domain}.json").write_text(
        json.dumps(res_json, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(L))
    if a.save_model:
        from open_guji_cv.shadow.model import save_model
        import subprocess
        import sklearn
        pool = [c for c in cells if a.train_domain == "all" or (not c["base_admit"] and not c["blocked"])]
        tr = df[df["id"].isin({c["id"] for c in pool})]
        clf = make_clf().fit(tr[feats], tr["label"])
        commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        fp = save_model(a.save_model, clf, {
            "model_id": Path(a.save_model).stem, "features": feats,
            "classifier": "HistGradientBoostingClassifier(max_iter=300, lr=0.05, max_leaf_nodes=15, l2=1.0, seed=0)",
            "calibration": "无单独校准：逐格归一 predict_proba 作把握度；门槛按人裁集实测错误率定（HANDOFF_D3.md）",
            "train_books": {b: sum(c["book"] == b for c in pool) for b in up},
            "n_cells": len(pool), "n_rows": int(len(tr)), "cv_commit": commit, "sklearn": sklearn.__version__,
            "trained_at": pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "notes": f"D3 影子升级；训练域 {a.train_domain}；标签 = vol02/vol03 人裁；无 LM 窗口分（未做）。"})
        print(f"模型 {a.save_model} 指纹 {fp}")


if __name__ == "__main__":
    main()
