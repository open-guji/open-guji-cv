# -*- coding: utf-8 -*-
"""覆盖率天花板：硬约束 precision ≥ 0.999 下，闸能开多低、recall 有多少。

    PYTHONPATH=. python scripts/eval_guard_ceiling.py --dump /tmp/pairs.npz \
        [--guard config/confusable_font_degraded.json --tau 0.93 0.95 0.97]

## 量的是什么

库匹配唯一的硬约束是 **precision ≥ 0.999**（错配一个字要毒一片），所以闸只能
站在「异字对的上尾之上」。天花板不由同字对决定，由**异字对分数的上尾**决定：
上尾越厚，闸越高，recall 越低。所以任何改动，只看它把异字上尾压下去多少。

## 护栏怎么记账

形近家族护栏 = 「两个字在形近表里 ≥ τ 时，系统不对这一对下判断（判成
ambiguous 交给 OCR/语言模型）」。在这层对级评测里就是：这类异字对**不计入
误判**，因为系统本来就不会认它。

**这个记账是偏乐观的**：真到线上，一个同字对如果它的字有形近对手也在库里
排在前面，同样会被判 ambiguous——那部分真匹配的损失这里没扣。所以这里的
recall 是**上界**，落到 `match.py` 之后必须用 `eval_db_match` 端到端复核。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from open_guji_cv.clustering.exclusions import excluded_ids  # noqa: E402

PREC_FLOOR = 0.999


def operating_point(cov: np.ndarray, same: np.ndarray, live: np.ndarray,
                    vetoed: np.ndarray) -> dict:
    """扫闸：找满足 precision ≥ 0.999 的最低闸，报那一点的 recall。"""
    m = live
    c, s, v = cov[m], same[m], vetoed[m]
    order = np.argsort(-c)
    c, s, v = c[order], s[order], v[order]
    # 被否决的异字对不算误判；被否决的同字对也不算命中（系统不下判断）
    tp = np.cumsum(s & ~v)
    fp = np.cumsum((~s) & ~v)
    prec = np.where(tp + fp > 0, tp / np.maximum(tp + fp, 1), 1.0)
    ok = np.where(prec >= PREC_FLOOR)[0]
    if len(ok) == 0:
        return {"gate": 1.0, "recall": 0.0, "precision": 1.0, "tp": 0, "fp": 0}
    i = ok[-1]
    return {"gate": round(float(c[i]), 4), "recall": round(float(tp[i] / s.sum()), 4),
            "precision": round(float(prec[i]), 5), "tp": int(tp[i]), "fp": int(fp[i])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--dataset", default="../open-guji-dataset/glyph-match/pairs")
    ap.add_argument("--guard", nargs="*", default=[], help="形近表 json（字对→分数）")
    ap.add_argument("--tau", nargs="*", type=float,
                    default=[0.99, 0.98, 0.97, 0.96, 0.95, 0.94, 0.93])
    ap.add_argument("--origin", default="knn")
    ap.add_argument("--exclude-origins", default=None,
                    help="只按这几个来源排除（逗号分隔，如 human,pipeline）。"
                         "默认全用——用来量「排除名单收紧之后会怎样」。")
    ap.add_argument("--book", default=None,
                    help="只在这一册的对上评（留出用：表从另一册学，这里评）")
    a = ap.parse_args()

    ds = Path(a.dataset)
    meta = {r["instance_id"]: r["char"]
            for r in json.loads((ds / "expected.json").read_text(encoding="utf-8"))["instances"]}
    ex = excluded_ids(origins=tuple(a.exclude_origins.split(","))
                      if a.exclude_origins else None)
    z = np.load(a.dump, allow_pickle=True)
    pairs, cov = list(z["pairs"]), z["cov"]

    # 标签从**现在的** expected.json 重新推——改标之后转储里的旧 label 不算数
    live = np.zeros(len(pairs), bool)
    same = np.zeros(len(pairs), bool)
    ca = [""] * len(pairs)
    cb = [""] * len(pairs)
    for k, p in enumerate(pairs):
        if p["origin"] != a.origin or p["a"] in ex or p["b"] in ex:
            continue
        if a.book and not (p["a"].startswith(a.book) and p["b"].startswith(a.book)):
            continue
        if p["a"] not in meta or p["b"] not in meta:      # 已剔除的实例
            continue
        live[k] = True
        ca[k], cb[k] = meta[p["a"]], meta[p["b"]]
        same[k] = ca[k] == cb[k]

    n_same, n_diff = int((same & live).sum()), int((~same & live).sum())
    print(f"对 {int(live.sum())}（同字 {n_same} / 异字 {n_diff}）"
          f"　排除名单 {len(ex)}　闸下限 precision ≥ {PREC_FLOOR}")

    base = operating_point(cov, same, live, np.zeros(len(pairs), bool))
    print(f"\n{'护栏':<26}{'族对':>7}{'否决':>7}{'闸':>9}{'recall':>9}{'倍数':>7}"
          f"{'precision':>11}{'牵连':>8}")
    print(f"{'无':<26}{'—':>7}{'—':>7}{base['gate']:>9}{base['recall']:>9}"
          f"{'1.0×':>7}{base['precision']:>11}{'0.0%':>8}")
    # 「牵连」= 有多大比例的同字对，它那个字在表里有形近对手（且对手也出现在
    # 数据里）。这些字到线上会被判 ambiguous，上面的 recall 没扣这一刀——
    # 牵连越大，recall 的水分越大。
    chars_here = set(meta.values())

    for g in a.guard:
        tab = json.loads(Path(g).read_text(encoding="utf-8"))
        tab = tab.get("pairs", tab)   # 表文件带 _doc/font 等表头
        name = Path(g).stem
        for tau in a.tau:
            fam = {k for k, v in tab.items() if v >= tau}
            vet = np.zeros(len(pairs), bool)
            for k in np.where(live)[0]:
                if ca[k] == cb[k]:
                    continue
                if (ca[k] + cb[k]) in fam or (cb[k] + ca[k]) in fam:
                    vet[k] = True
            r = operating_point(cov, same, live, vet)
            mult = r["recall"] / base["recall"] if base["recall"] else float("nan")
            ent = set()
            for k in fam:
                if len(k) == 2 and k[0] in chars_here and k[1] in chars_here:
                    ent.update(k)
            n_ent = sum(1 for k in np.where(live & same)[0] if ca[k] in ent)
            print(f"{name + ' τ=' + str(tau):<26}{len(fam):>7}{int(vet.sum()):>7}"
                  f"{r['gate']:>9}{r['recall']:>9}{f'{mult:.1f}×':>7}{r['precision']:>11}"
                  f"{f'{n_ent / max(n_same, 1):.1%}':>8}")


if __name__ == "__main__":
    main()
