# -*- coding: utf-8 -*-
"""影子放行模型·vol03 试跑：三种训法按页交叉验证对比 + 待审卡预测 + 全书影子运行（overview#269）。

    ~/shadow-venv/bin/python scripts/experiments/shadow_admit/vol03_eval.py \
        --target <scratch>/signals_all.jsonl \
        --bxgb <ws>/reports/bxgb/shadow/signals_labeled.jsonl \
        --vol02 <ws>/reports/vol02/shadow/signals_labeled_v2_clean.jsonl --out <dir>

vol03 信号由 `extract_snap.py` 出：**没有 OCR、没有小笔画判别器**。所以跨书训练一律去掉这两组信号，
并把训练书里「只有 OCR 提名」的候选行（库/5b/整理本都没提它）剔掉，让候选集口径与 vol03 一致；
`n_cands` 也去掉（它直接随 OCR 候选数变）。己已巳在训练书上同样合并成「己」。

评测口径：
- 标签只取 vol03 经绑定表采信的 confirm 带字裁决（seg_defect/not_a_char 不当字标签）；
- 印章遮挡格（`occluded`）单列，不混进主表；
- (a) bxgb+vol02 训 → vol03 零样本；(b) 再加 vol03 训练折（按页 5 折，同一折）；(c) 单信号基线；
- 把握度 = 一格内候选分数归一后的最大值；「前 X% 错误率」= 按把握度从高到低放行 X% 的格里错了几格。
只读信号文件，产出 md/jsonl 报表，不写产物、不写事件。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).parent))
from train import MODELS, curve, per_cell  # noqa: E402

JYS = set("己已巳")
F1 = ["lib_cov", "lib_in", "lib_top1", "lib_margin", "lib_top_cov", "human_n", "human_any",
      "rare_score", "ref_eq", "ref_sem", "ref_none", "ref_op_equal", "confusable"]
F2 = F1 + ["rel_exact", "rel_variant", "rel_jiajie", "rel_convention", "rel_confusable", "rel_unrelated",
           "ref_run", "ref_local_mismatch"]
# ref_op_equal（整理本字是 equal 还是 replace 对上的）在 vol03 上**意思反了**：训练书里 replace 对上的整理本字
# 只有 3.8%（vol02）/ 29.5%（bxgb）是真值，vol03 待审卡里是 98.9%——待审卡本来就是 Step7 按
# replace_align 挑出来的「库与整理本打架」的格。零样本带着它 top1 只有 54%，去掉回到 87%（2026-09-29 实测）。
F1N = [f for f in F1 if f != "ref_op_equal"]
F2N = [f for f in F2 if f != "ref_op_equal"]
MAKE = MODELS["梯度提升树"]
MAIN = "(b) bxgb+vol02+vol03 训练折（F1 去 ref_op_equal）"
SEED_FOLDS = 5


def J(c):
    return "己" if isinstance(c, str) and c in JYS else c


def load_train(p: str) -> pd.DataFrame:
    d = pd.read_json(p, lines=True, dtype={"ref_char": str, "cand": str, "cur": str})
    d = d[d["label"].notna()].copy()
    d["label"] = d["label"].astype(int)
    d = d[~((d["lib_in"] == 0) & (d["rare_score"] == 0) & (d["ref_eq"] == 0))]   # 只有 OCR 提名的候选
    d["cand"] = d["cand"].map(J)
    d["label"] = d.groupby(["id", "cand"])["label"].transform("max")
    d = d.sort_values("lib_cov", ascending=False).drop_duplicates(["id", "cand"])
    d = d[d["id"].isin(d[d["label"] == 1]["id"])]           # 真值已不在候选集的格（原来只有 OCR 提了真值）不进训练
    return d.reset_index(drop=True)


def cv_scores(tgt: pd.DataFrame, feats, extra: pd.DataFrame | None, folds) -> np.ndarray:
    p = np.zeros(len(tgt))
    for tr, te in folds:
        tr_df = tgt.iloc[tr] if extra is None else pd.concat([extra, tgt.iloc[tr]], ignore_index=True)
        p[te] = MAKE().fit(tr_df[feats], tr_df["label"]).predict_proba(tgt.iloc[te][feats])[:, 1]
    return p


def row(name, pk):
    c = curve(pk)
    return (f"| {name} | {pk['ok'].mean():.1%} | {int((~pk['ok']).sum())}/{len(pk)} | "
            f"{c[4][1]:.2%}（{c[4][2]}） | {c[6][1]:.2%}（{c[6][2]}） | {c[8][1]:.2%}（{c[8][2]}） |")


HDR = ["| 方案 | top1 | 错格/格数 | 前50%错误率（错格） | 前70% | 前90% |", "|---|---|---|---|---|---|"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--bxgb", required=True)
    ap.add_argument("--vol02", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    full = pd.read_json(a.target, lines=True, dtype={"ref_char": str, "cand": str, "cur": str, "truth": str})
    full["ref_char"] = full["ref_char"].fillna("")
    tgt = full[full["label"].notna()].reset_index(drop=True)
    tgt["label"] = tgt["label"].astype(int)
    B, V = load_train(a.bxgb), load_train(a.vol02)
    BV = pd.concat([B, V], ignore_index=True)
    folds = list(GroupKFold(n_splits=SEED_FOLDS).split(tgt, tgt["label"], tgt["page"]))

    occ_ids = set(tgt[tgt["occluded"] == 1]["id"])
    L = [f"# 影子放行模型 · vol03 试跑\n",
         f"训练书（去 OCR/判别器、剔只有 OCR 提名的候选后）：bxgb {B['id'].nunique()} 格、vol02 {V['id'].nunique()} 格。",
         f"vol03 带字标签 {tgt['id'].nunique()} 格（{tgt['page'].nunique()} 页；其中印章遮挡 {len(occ_ids)} 格单列）；"
         f"按页 {SEED_FOLDS} 折，各方案同一折。\n"]

    schemes: dict[str, np.ndarray] = {}
    # (c) 单信号基线
    base = {
        "单信号·整理本（ref_eq）": tgt["ref_eq"].to_numpy() + 1e-3 * tgt["lib_cov"].to_numpy(),
        "单信号·库 top1（lib_cov）": tgt["lib_cov"].to_numpy() + 1e-6 * tgt["ref_eq"].to_numpy(),
        "单信号·现字（seed_admit 快照里的字）": (tgt["cand"] == tgt["cur"]).astype(float).to_numpy() + 1e-3 * tgt["lib_cov"].to_numpy(),
    }
    schemes.update(base)
    # (a) 零样本
    for nm, tr, fs in (("(a) bxgb+vol02 训 → vol03 零样本（F1）", BV, F1),
                       ("(a) bxgb+vol02 训 → vol03 零样本（F1 去 ref_op_equal）", BV, F1N),
                       ("(a') vol02 训 → vol03 零样本（F2 去 ref_op_equal）", V, F2N)):
        schemes[nm] = MAKE().fit(tr[fs], tr["label"]).predict_proba(tgt[fs])[:, 1]
    # (b) 加 vol03 训练折
    schemes["(b) bxgb+vol02+vol03 训练折（F1）"] = cv_scores(tgt, F1, BV, folds)
    schemes[MAIN] = cv_scores(tgt, F1N, BV, folds)
    schemes["(b') vol02+vol03 训练折（F2 去 ref_op_equal）"] = cv_scores(tgt, F2N, V, folds)
    schemes["(b0) 只用 vol03 训练折（F2）"] = cv_scores(tgt, F2, None, folds)

    picks = {}
    for part, ids in (("主表（不含印章遮挡）", set(tgt["id"]) - occ_ids), ("印章遮挡格", occ_ids), ("全部", set(tgt["id"]))):
        L += [f"\n## {part}：{len(ids)} 格\n"] + HDR
        sub = tgt[tgt["id"].isin(ids)].reset_index(drop=True)
        for nm, sc in schemes.items():
            pk = per_cell(sub, sc[tgt["id"].isin(ids).to_numpy()])
            pk["ok"] = pk["pick"].map(J) == pk["truth"].map(J)
            if part == "全部":
                picks[nm] = pk
            L.append(row(nm, pk))

    # 按类别拆（全部标签格，用 (b) 的交叉验证分数）
    meta = tgt.drop_duplicates("id").set_index("id")
    cats = {
        "对齐改字层（doubts 含 replace_align）": set(meta[meta["doubts"].map(lambda d: "replace_align" in d)].index),
        "列尾（slot≥20）": set(meta[meta["slot"] >= 20].index),
        "夹注（jiazhu_a/b/solo）": set(meta[meta["kind"].str.startswith("jiazhu")].index),
        "整理本字≠真值": set(meta[meta["ref_char"] != meta["truth"]].index),
        "其余": set(meta.index),
    }
    cats["其余"] -= set().union(*[v for k, v in cats.items() if k != "其余"])
    L += ["\n## 按类别拆（全部标签格；top1 / 错格）\n",
          "| 类别 | 格数 | 整理本 | 库 top1 | 现字 | (a) 去 op | (b) 去 op |", "|---|---|---|---|---|---|---|"]
    keys = ["单信号·整理本（ref_eq）", "单信号·库 top1（lib_cov）", "单信号·现字（seed_admit 快照里的字）",
            "(a) bxgb+vol02 训 → vol03 零样本（F1 去 ref_op_equal）", MAIN]
    for cn, ids in cats.items():
        cells = [f"{picks[k][picks[k]['id'].isin(ids)]['ok'].mean():.1%}（错 {int((~picks[k][picks[k]['id'].isin(ids)]['ok']).sum())}）"
                 for k in keys]
        L.append(f"| {cn} | {len(ids)} | " + " | ".join(cells) + " |")

    # 把握度阈值上的实际错误率（(b)）
    pk = picks[MAIN]
    L += ["\n## (b 去 op) 的把握度门槛 → 标签格上的实际表现\n", "| 把握 ≥ | 格数 | 错格 | 错误率 |", "|---|---|---|---|"]
    for t in (0.99, 0.95, 0.9, 0.8):
        s = pk[pk["conf"] >= t]
        L.append(f"| {t} | {len(s)} | {int((~s['ok']).sum())} | {(~s['ok']).mean() if len(s) else 0:.2%} |")
    bad = pk[~pk["ok"]].sort_values("conf", ascending=False).head(25)
    L += ["\n## (b 去 op) 错得最有把握的标签格（前 25）\n", "| 字位 | 选了 | 真值 | 把握 | 整理本 | 现字 | 印章 |", "|---|---|---|---|---|---|---|"]
    L += [f"| {r.id} | {r.pick} | {r.truth} | {r.conf:.3f} | {meta.at[r.id, 'ref_char']} | {meta.at[r.id, 'cur']} | "
          f"{'是' if r.id in occ_ids else ''} |" for r in bad.itertuples()]

    # ── 全书影子运行：标签格用 (b) 的交叉验证分数，其余格用 bxgb+vol02+vol03 全量训的模型
    allt = pd.concat([BV, tgt], ignore_index=True)
    model = MAKE().fit(allt[F1N], allt["label"])
    unl = full[full["label"].isna()].reset_index(drop=True)
    unl["score"] = model.predict_proba(unl[F1N])[:, 1]
    tgt2 = tgt.copy()
    tgt2["score"] = schemes[MAIN]
    d = pd.concat([tgt2, unl], ignore_index=True)
    tot = d.groupby("id")["score"].sum().clip(lower=1e-9)
    idx = d.groupby("id")["score"].idxmax()
    cols = ["id", "page", "slot", "sub", "kind", "cand", "cur", "admit", "admit_char", "channel", "score", "ref_char",
            "doubts", "occluded", "truth", "verdict_v"]
    sp = d.loc[idx, cols].rename(columns={"cand": "pick"}).reset_index(drop=True)
    sp["conf"] = sp["score"] / sp["id"].map(tot).to_numpy()
    cur_sc = d[d["cand"] == d["cur"]].groupby("id")["score"].max()
    sp["cur_conf"] = (sp["id"].map(cur_sc).fillna(0.0) / sp["id"].map(tot)).to_numpy()
    sp["labeled"] = sp["truth"].notna()
    # 次选
    d2 = d.drop(index=idx.to_numpy())
    idx2 = d2.groupby("id")["score"].idxmax()
    second = d2.loc[idx2].set_index("id")
    sp["second"] = sp["id"].map(second["cand"])
    sp["second_conf"] = (sp["id"].map(second["score"]) / sp["id"].map(tot)).fillna(0.0).to_numpy()
    sp.to_json(out / "shadow_picks_vol03.jsonl", orient="records", lines=True, force_ascii=False)

    pend = sp[(~sp["admit"]) & sp["verdict_v"].isna() & ~sp["doubts"].map(lambda x: "excluded" in x)]
    L += [f"\n# 待审卡预测（admit=False、没有被采信的裁决、非排除名单：{len(pend)} 张）\n",
          "模型：bxgb+vol02+vol03 全部标签训（F1 去 ref_op_equal）。\n",
          "| 分组 | 张数 | 把握≥0.99 | ≥0.95 | ≥0.9 | 影子≠整理本（≥0.95 中） | 影子≠现字（≥0.95 中） |", "|---|---|---|---|---|---|---|"]
    groups = {
        "全部待审卡": pend,
        "对齐改字层（replace_align）": pend[pend["doubts"].map(lambda x: "replace_align" in x)],
        "列尾（slot≥20）": pend[pend["slot"] >= 20],
        "夹注": pend[pend["kind"].str.startswith("jiazhu")],
        "印章遮挡（doubt occluded）": pend[pend["occluded"] == 1],
        "库 unsure 且无 replace_align": pend[pend["doubts"].map(lambda x: "库 unsure" in x and "replace_align" not in x)],
    }
    for gn, g in groups.items():
        h = g[g["conf"] >= 0.95]
        L.append(f"| {gn} | {len(g)} | {int((g['conf'] >= 0.99).sum())} | {len(h)} | {int((g['conf'] >= 0.9).sum())} | "
                 f"{int((h['pick'] != h['ref_char']).sum())} | {int((h['pick'] != h['cur']).sum())} |")
    dz = pend[(pend["conf"] >= 0.95) & (pend["pick"] != pend["ref_char"])].sort_values("conf", ascending=False)
    L += [f"\n## 待审卡里 把握≥0.95 且 影子≠整理本字（{len(dz)} 张）\n",
          "| 字位 | 影子 | 把握 | 整理本 | 现字 | 次选 | 列内格 | doubts |", "|---|---|---|---|---|---|---|---|"]
    L += [f"| {r.id} | {r.pick} | {r.conf:.3f} | {r.ref_char or '—'} | {r.cur or '—'} | {r.second or ''} | {r.slot} | "
          f"{','.join(sorted(set(r.doubts)))} |" for r in dz.itertuples()]

    # 「预先勾上」规则在**同一队列的已裁卡**上的实测（已裁卡就是 09-28 从这批待审卡里裁掉的那部分）
    lab_sp = sp[sp["labeled"]].copy()
    lab_sp["ok"] = lab_sp["pick"] == lab_sp["truth"]
    ra = lab_sp["doubts"].map(lambda x: "replace_align" in x)
    rules = [
        ("replace_align 卡·勾整理本字", lab_sp[ra], lambda g: g["ref_char"] == g["truth"], lambda g: g["ref_char"] != ""),
        ("replace_align 卡·影子=整理本 且把握≥0.9", lab_sp[ra], lambda g: g["pick"] == g["truth"],
         lambda g: (g["pick"] == g["ref_char"]) & (g["conf"] >= 0.9)),
        ("replace_align 卡·影子=整理本 且把握≥0.95", lab_sp[ra], lambda g: g["pick"] == g["truth"],
         lambda g: (g["pick"] == g["ref_char"]) & (g["conf"] >= 0.95)),
        ("印章遮挡卡·勾现字", lab_sp[lab_sp["occluded"] == 1], lambda g: g["cur"] == g["truth"], lambda g: g["cur"].notna()),
        ("其余卡·影子把握≥0.95", lab_sp[~ra & (lab_sp["occluded"] == 0)], lambda g: g["pick"] == g["truth"],
         lambda g: g["conf"] >= 0.95),
        ("全部卡·影子把握≥0.95", lab_sp, lambda g: g["pick"] == g["truth"], lambda g: g["conf"] >= 0.95),
    ]
    L += ["\n## 「预先勾上」候选规则在已裁卡上的实测\n", "| 规则 | 该类已裁卡 | 规则命中 | 命中里错 | 错误率 | 待审卡里命中 |",
          "|---|---|---|---|---|---|"]
    pra = pend["doubts"].map(lambda x: "replace_align" in x)
    pend_groups = {"replace_align": pend[pra], "印章": pend[pend["occluded"] == 1],
                   "其余": pend[~pra & (pend["occluded"] == 0)], "全部": pend}
    for nm, g, okf, hitf in rules:
        h = g[hitf(g)]
        bad_n = int((~okf(h)).sum())
        pg = pend_groups["replace_align" if nm.startswith("replace") else "印章" if nm.startswith("印章")
                         else "其余" if nm.startswith("其余") else "全部"]
        L.append(f"| {nm} | {len(g)} | {len(h)} | {bad_n} | {bad_n / max(1, len(h)):.1%} | {int(hitf(pg).sum())} / {len(pg)} |")
    wr = lab_sp[ra & (lab_sp["ref_char"] != lab_sp["truth"])]
    L += ["\nreplace_align 已裁卡里整理本字错的：" + "；".join(f"{r.id} 整理本 {r.ref_char or '—'} → 真值 {r.truth}（影子 {r.pick} {r.conf:.2f}）"
                                          for r in wr.itertuples())]

    # 全书：影子≠现字且很有把握（已放行的格）
    adm = sp[sp["admit"] & ~sp["labeled"]]
    hi = adm[(adm["pick"] != adm["cur"]) & (adm["conf"] >= 0.9)].sort_values("conf", ascending=False)
    L += [f"\n# 全书影子运行（已放行 {len(adm)} 格）\n",
          f"影子≠现字：{int((adm['pick'] != adm['cur']).sum())} 格；其中把握 ≥0.9：{len(hi)}，≥0.95：{int((hi['conf'] >= 0.95).sum())}，"
          f"≥0.99：{int((hi['conf'] >= 0.99).sum())}。现通道分布（≥0.9）：{hi['channel'].value_counts().to_dict()}\n",
          "| 字位 | 现字 | 影子 | 把握 | 现字把握 | 整理本 | 现通道 |", "|---|---|---|---|---|---|---|"]
    L += [f"| {r.id} | {r.cur} | {r.pick} | {r.conf:.3f} | {r.cur_conf:.3f} | {r.ref_char or '—'} | {r.channel} |"
          for r in hi.itertuples()]
    hi.to_json(out / "admitted_disagree.jsonl", orient="records", lines=True, force_ascii=False)
    pend.to_json(out / "pending_picks.jsonl", orient="records", lines=True, force_ascii=False)
    text = "\n".join(L) + "\n"
    (out / "report_vol03.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
