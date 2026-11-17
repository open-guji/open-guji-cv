"""给 5a 相似度 CNN 拟合分数校准表 `calib.json`（`clustering.sim_cnn` 模块头「分数校准」）。

    python scripts/fit_glyph_sim_calib.py --work <sim_bench 工作目录> --cnn <分数名> --out models/glyph_sim_qtw/calib.json

输入是 `scripts/eval_sim_bench.py` 的工作目录：`pool.pkl`（查询格、同字刻例行、对手刻例行）、`s_prod.pkl`（现行覆盖分）、
`s_<分数名>.pkl`（这份权重的逐对分，`eval_sim_bench.py score` 出）。可疑标签（`sc` 非空）的查询不用。

做法：同等误配率——把 CNN 异字对分数的分位数对到 cov 异字对的同一分位数（0～99.995%），使下游任一「cov ≥ X」门槛
放进来的异字对比例不变；异字对分布尽头之上没有误配可对，按两边各自高于该点的同字对的条件分位数对齐。节点保留 4 位、单调。
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np

QS_IMP = list(np.linspace(0, 0.9, 10)) + [0.95, 0.98, 0.99, 0.995, 0.998, 0.999, 0.9995, 0.9998, 0.9999, 0.99995]
QS_GEN = [0.2, 0.4, 0.6, 0.8, 0.9, 0.95, 0.99]


def pairs(D: dict, S: dict) -> tuple[np.ndarray, np.ndarray]:
    gen, imp = [], []
    for i, q in enumerate(D["qs"]):
        s = S.get(i)
        if s is None or q["sc"]:
            continue
        s = [x[0] if isinstance(x, list) else x for x in s]
        ng = len(q["gold_rows"])
        gen += s[:ng]
        imp += s[ng:]
    return np.asarray(gen, float), np.asarray(imp, float)


def fit(cg, ci, ng, ni) -> list[list[float]]:
    ks, kc = list(np.quantile(ni, QS_IMP)), list(np.quantile(ci, QS_IMP))
    s0, c0 = ks[-1], kc[-1]
    gs, gc = ng[ng > s0], cg[cg > c0]
    if len(gs) and len(gc):
        ks += list(np.quantile(gs, QS_GEN))
        kc += list(np.quantile(gc, QS_GEN))
    ks.append(1.0)
    kc.append(1.0)
    ks = np.maximum.accumulate(np.round(ks, 4))
    kc = np.maximum.accumulate(np.round(kc, 4))
    keep = np.r_[True, np.diff(ks) > 0]
    return [[float(a), float(b)] for a, b in zip(ks[keep], kc[keep])]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--cnn", required=True, help="s_<名>.pkl 的名")
    ap.add_argument("--base", default="prod", help="对齐到的分数（缺省现行覆盖分 prod）")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    w = Path(a.work)
    D = pickle.load(open(w / "pool.pkl", "rb"))
    cg, ci = pairs(D, pickle.load(open(w / f"s_{a.base}.pkl", "rb"))["scores"])
    ng, ni = pairs(D, pickle.load(open(w / f"s_{a.cnn}.pkl", "rb"))["scores"])
    knots = fit(cg, ci, ng, ni)
    ks, kc = np.array(knots).T
    mg, mi = np.interp(ng, ks, kc), np.interp(ni, ks, kc)
    print(f"同字对 {len(cg)}、异字对 {len(ci)}；节点 {len(knots)}")
    for c in (0.85, 0.9, 0.95, 0.97, 0.98, 0.99, 0.993, 0.996):
        print(f"  ≥{c}: 异字对 {int((mi >= c).sum())}（cov {int((ci >= c).sum())}）  同字对 {np.mean(mg >= c):.3f}（cov {np.mean(cg >= c):.3f}）")
    Path(a.out).write_text(json.dumps({"schema": "sim-calib/1", "method": "equal-FMR", "base": a.base,
                                       "pairs": {"gen": len(cg), "imp": len(ci)}, "knots": knots},
                                      ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"→ {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
