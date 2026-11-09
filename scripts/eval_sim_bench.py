# -*- coding: utf-8 -*-
"""5a 逐对相似度基准（sim_bench，A23 2026-11-09）：只量「查询图 × 库刻例」的相似度函数本身。

和 eval_match_bench.py 的分工：那个量整条 5a 栈（kNN 粗排＋精验＋闸）；这个把粗排**固定**下来，
每个查询给一个固定候选池，只换相似度函数，看「同字更像、异字拉开」有没有变好，和每对耗时。

候选池（`pool` 子命令，一次建好存 pkl）：查询＝人裁冻结分片（缺省全唐文 006-qtw-human，3002 格），
库＝本书 glyph.db（按物理格留一）。每个查询取
  - 同字刻例：按 HOG 相似度前 8 个；
  - 异字：HOG 相似度最高的 8 个别的字，各取最像的 3 个刻例；再补形近表（confusable.partners）里库中有的对家。
己已巳、日曰两组按组折叠（Sheldon 11-05：匹配到组内任一字形都算对）。

指标（`report`，体检标记格不进头条）：
  - rank1：同字最高分 > 所有异字最高分（字分 = 该字刻例分数的最大值，和生产一致）；
  - auroc / tpr@fpr1% / tpr@fpr0.1%：每格「同字最高分」对「最难异字最高分＋novel 格的最高分」，
    衡量**一个全局门槛**能不能把同字和异字分开（生产的 same 闸、共识升档都是全局门槛）；
  - gate：生产式二维闸（首位分 ≥ t 且领先第二名 ≥ d），按页号奇偶二折，一折拟合（精度 ≥ P 时召回最大）、另一折测；
  - us：单进程每对微秒。

11-09 全唐文结果（体检标记除外，answerable 2723／novel 90）：生产 elastic rank1 0.9956、auroc 0.961、tpr@1% 0.54；
τ=3 0.978／0.66（每对 870us，比生产 1360us 快）；融合 fast7 0.982／0.76；度量学习 CNN（研究代码在 ai-team）0.998／0.97。
同形异码折叠后，二维闸 P.999 召回各算法都约 95%——全唐文干净格上闸的瓶颈是码位口径，不是相似度。

用法（云端沙箱）::

    GUJI_GLYPH_DB=<全唐文 glyph.db> python scripts/eval_sim_bench.py pool --work /tmp/simb
    python scripts/eval_sim_bench.py score --work /tmp/simb prod el_tau3 fast
    python scripts/eval_sim_bench.py fit --work /tmp/simb            # fast 特征 → fast7 融合（二折出分）
    python scripts/eval_sim_bench.py report --work /tmp/simb prod el_tau3 fast7_oof
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval_fold import fold  # noqa: E402

G_PER, R_CHARS, R_PER = 8, 8, 3
_W: dict = {}


def build_pool(db: str, shard: Path, out: Path) -> None:
    from open_guji_cv.clustering.confusable import partners
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.seeding import load_matcher_from_db
    import sqlite3
    m, _ = load_matcher_from_db(GlyphDB(db), knn_k=15)
    F = m.library_matrix()
    chars = [fold(c) for c in m._chars]
    prov = dict(sqlite3.connect(db).execute("select instance_id, provenance from admissions"))
    P = partners()
    rows_of: dict[str, list[int]] = {}
    for j, c in enumerate(chars):
        rows_of.setdefault(c, []).append(j)
    exp = json.loads((shard / "expected.json").read_text(encoding="utf-8"))
    qs = []
    for x in exp["instances"]:
        norm = (cv2.imread(str(shard / x["crop"]), cv2.IMREAD_GRAYSCALE) > 127).astype(np.uint8)
        sims = F @ m.extract(norm[None])[0]
        excl = m._same_cell_rows(x["instance_id"])
        if excl:
            sims[list(excl)] = -np.inf
        gold = fold(x["char"])
        order = np.argsort(-sims)
        gold_rows = sorted((j for j in rows_of.get(gold, []) if j not in excl), key=lambda j: -sims[j])[:G_PER]
        riv: dict[str, list[int]] = {}
        for j in order[:3000]:
            c = chars[int(j)]
            if c == gold or (c not in riv and len(riv) >= R_CHARS):
                continue
            lst = riv.setdefault(c, [])
            if len(lst) < R_PER:
                lst.append(int(j))
        for p in P.get(x["char"], ()):
            p = fold(p)
            if p != gold and p not in riv and p in rows_of:
                rr = [j for j in rows_of[p] if j not in excl]
                if rr:
                    riv[p] = sorted(rr, key=lambda j: -sims[j])[:R_PER]
        qs.append(dict(id=x["instance_id"], gold=gold, norm=norm, gold_rows=gold_rows, rivals=riv,
                       sc=x.get("selfcheck_flag") or ""))
    lib = dict(ids=m._ids, chars=chars, patches=m._patches, prov=[prov.get(i, "?") for i in m._ids])
    pickle.dump(dict(qs=qs, lib=lib, db=db, shard=str(shard)), open(out, "wb"))
    print(f"池：{len(qs)} 查询（answerable {sum(bool(q['gold_rows']) for q in qs)}），库 {len(lib['ids'])} 条 → {out}")


def _rows(q):
    return list(q["gold_rows"]) + [j for c in q["rivals"] for j in q["rivals"][c]]


def _init(pool_path):
    import sim_algos
    _W["D"] = pickle.load(open(pool_path, "rb"))
    _W["R"] = sim_algos.REGISTRY


def _work(args):
    name, i = args
    f = _W["R"][name]
    q, lib = _W["D"]["qs"][i], _W["D"]["lib"]
    v = [f(q["norm"], lib["patches"][j]) for j in _rows(q)]
    return i, [x if isinstance(x, list) else float(x) for x in v]


def score(work: Path, names: list[str], procs: int) -> None:
    pool_path = str(work / "pool.pkl")
    _init(pool_path)
    nq = len(_W["D"]["qs"])
    for name in names:
        t, n = time.perf_counter(), 0
        for i in range(min(200, nq)):
            n += len(_work((name, i))[1])
        us = (time.perf_counter() - t) / n * 1e6
        with Pool(procs, initializer=_init, initargs=(pool_path,)) as p:
            res = dict(p.map(_work, [(name, i) for i in range(nq)], chunksize=20))
        pickle.dump({"scores": res, "us_pair": us}, open(work / f"s_{name}.pkl", "wb"))
        print(f"{name}: {us:.0f} us/对", flush=True)


def fit(work: Path) -> None:
    """fast 特征 → Logistic 回归。按页号奇偶二折出 out-of-fold 分（fast7_oof），另报全量系数（原始尺度）。"""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    import sim_algos
    D = pickle.load(open(work / "pool.pkl", "rb"))
    S = pickle.load(open(work / "s_fast.pkl", "rb"))
    X, y, qi, fd = [], [], [], []
    for i, q in enumerate(D["qs"]):
        ng = len(q["gold_rows"])
        for t, v in enumerate(S["scores"][i]):
            X.append(v), y.append(t < ng), qi.append(i), fd.append(int(q["id"].split(":")[2]) % 2)
    X, y, qi, fd = map(np.array, (X, y, qi, fd))
    bad = np.array([bool(D["qs"][i]["sc"]) for i in qi])
    pred = np.zeros(len(y))
    for k in (0, 1):
        tr, te = (fd != k) & ~bad, fd == k
        sc = StandardScaler().fit(X[tr])
        m = LogisticRegression(max_iter=2000).fit(sc.transform(X[tr]), y[tr])
        p = m.predict_proba(sc.transform(X[te]))[:, 1]
        pred[te] = np.log(p + 1e-9) - np.log(1 - p + 1e-9)
    res = {i: list(pred[qi == i]) for i in range(len(D["qs"]))}
    pickle.dump({"scores": res, "us_pair": S["us_pair"]}, open(work / "s_fast7_oof.pkl", "wb"))
    sc = StandardScaler().fit(X[~bad])
    m = LogisticRegression(max_iter=2000).fit(sc.transform(X[~bad]), y[~bad])
    coef = m.coef_[0] / sc.scale_
    print("全量系数", dict(zip(sim_algos.FAST_NAMES, np.round(coef, 3))),
          "bias", round(float(m.intercept_[0] - (m.coef_[0] * sc.mean_ / sc.scale_).sum()), 3))


def _auroc(pos, neg):
    from scipy.stats import rankdata
    r = rankdata(np.r_[pos, neg])
    n1, n0 = len(pos), len(neg)
    return float((r[:n1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _tpr(pos, neg, fpr):
    neg = np.sort(neg)[::-1]
    k = int(np.floor(fpr * len(neg)))
    return float(np.mean(np.asarray(pos) > (neg[k] if k < len(neg) else -np.inf)))


# 同形异码（全唐文 11-09 看图：库里同一个刻形挂在两个码位下），--fold-variants 时与 VariantMap 语义异体一起折叠。
# 待 Sheldon／QTW 确认口径；只影响评测，不动库。
SAME_SHAPE_QTW = {"歳": "歲", "𠋫": "侯", "廏": "廄", "两": "兩"}


def _folder(on: bool):
    if not on:
        return lambda c: c
    from open_guji_cv.clustering.variants import VariantMap
    vm = VariantMap.load()
    return lambda c: vm.semantic(SAME_SHAPE_QTW.get(c, c))


def _per_query(D, sc, include_sc=False, fv=lambda c: c):
    """每个查询 → (同字分 或 None, 最难异字分, 首位分, 领先, 首位对否, 页奇偶)。fv：评测折叠（异体同形算同字）。"""
    out = []
    for i, q in enumerate(D["qs"]):
        s = sc.get(i)
        if s is None or (q["sc"] and not include_sc):
            continue
        ng = len(q["gold_rows"])
        gold = fv(q["gold"])
        per = {gold: max(s[:ng])} if ng else {}
        k = ng
        for c, rr in q["rivals"].items():
            c = fv(c)
            per[c] = max(per.get(c, -np.inf), max(s[k:k + len(rr)]))
            k += len(rr)
        if not ng and gold in per:          # novel 格的异体在库里：折叠后算有同字
            ng = 1
        r = sorted(per.items(), key=lambda t: -t[1])
        g = per.get(gold) if ng else None
        riv = max((v for c, v in per.items() if c != gold), default=0.0)
        top2 = r[1][1] if len(r) > 1 else 0.0
        out.append((g, riv, r[0][1], r[0][1] - top2, ng > 0 and r[0][0] == gold, int(q["id"].split(":")[2]) % 2))
    return out


def _gate(rows, P):
    R = np.array([(t, d, ok, g is not None, f) for g, _, t, d, ok, f in rows], dtype=float)
    rec, acc, err = [], 0, 0
    for f in (0, 1):
        tr, te = R[R[:, 4] != f], R[R[:, 4] == f]
        best = (0, (np.inf, np.inf))
        for t in np.quantile(tr[:, 0], np.linspace(0, 0.995, 80)):
            for d in np.quantile(tr[:, 1], np.linspace(0, 0.995, 80)):
                a = (tr[:, 0] >= t) & (tr[:, 1] >= d)
                ok = (a & (tr[:, 2] == 1)).sum()
                if a.sum() and ok / a.sum() >= P and ok > best[0]:
                    best = (ok, (t, d))
        t, d = best[1]
        a = (te[:, 0] >= t) & (te[:, 1] >= d)
        ok = (a & (te[:, 2] == 1)).sum()
        rec.append(ok / max(1, (te[:, 3] == 1).sum()))
        acc += a.sum()
        err += a.sum() - ok
    return float(np.mean(rec)), int(err), int(acc)


def report(work: Path, names: list[str], include_sc: bool, fold_variants: bool = False) -> dict:
    D = pickle.load(open(work / "pool.pkl", "rb"))
    fv = _folder(fold_variants)
    out = {}
    print(f"{'算法':<12}{'rank1':>8}{'auroc':>8}{'tpr@1%':>8}{'tpr@.1%':>8}{'闸P.999 召回/错':>16}{'闸P.995 召回/错':>16}{'us/对':>8}")
    for n in names:
        S = pickle.load(open(work / f"s_{n}.pkl", "rb"))
        rows = _per_query(D, S["scores"], include_sc, fv)
        pos = [r[0] for r in rows if r[0] is not None]
        neg = [r[1] for r in rows if r[0] is not None] + [r[2] for r in rows if r[0] is None]
        o = dict(n=len(pos), n_novel=sum(r[0] is None for r in rows),
                 rank1=float(np.mean([r[0] > r[1] for r in rows if r[0] is not None])),
                 auroc=_auroc(pos, neg), tpr1=_tpr(pos, neg, 0.01), tpr01=_tpr(pos, neg, 0.001),
                 gate999=_gate(rows, 0.999), gate995=_gate(rows, 0.995), us=S["us_pair"])
        out[n] = o
        print(f"{n:<12}{o['rank1']:>8.4f}{o['auroc']:>8.4f}{o['tpr1']:>8.4f}{o['tpr01']:>8.4f}"
              f"{o['gate999'][0]:>10.3f}/{o['gate999'][1]:<5}{o['gate995'][0]:>10.3f}/{o['gate995'][1]:<5}{o['us']:>8.0f}")
    print(f"answerable {o['n']}，novel {o['n_novel']}（体检标记{'含' if include_sc else '不含'}）")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "pool", "score", "fit", "report"))
    ap.add_argument("algos", nargs="*")
    ap.add_argument("--work", default="/tmp/sim_bench")
    ap.add_argument("--db", default=os.environ.get("GUJI_GLYPH_DB"))
    ap.add_argument("--shard", default="../open-guji-dataset/char-clustering/samples/006-qtw-human")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--all", action="store_true", help="report 含体检标记格")
    ap.add_argument("--fold-variants", action="store_true", help="report 把语义异体与 SAME_SHAPE_QTW 当同字")
    ap.add_argument("--out", default=None)
    a = ap.parse_intermixed_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    if a.cmd == "run":   # 一条龙（注册表用）：建池 → 生产/τ3/融合特征 → 融合二折 → 报告（含同形异码折叠两口径）
        if not a.db:
            raise SystemExit("要 --db 或 GUJI_GLYPH_DB（库要和分片同书）")
        build_pool(a.db, Path(a.shard), work / "pool.pkl")
        score(work, ["prod", "el_tau3", "fast"], a.procs)
        fit(work)
        names = ["prod", "el_tau3", "fast7_oof"]
        rep = {"strict": report(work, names, a.all), "fold_variants": report(work, names, a.all, True)}
        if a.out:
            Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    elif a.cmd == "pool":
        if not a.db:
            raise SystemExit("要 --db 或 GUJI_GLYPH_DB（库要和分片同书）")
        build_pool(a.db, Path(a.shard), work / "pool.pkl")
    elif a.cmd == "score":
        score(work, a.algos, a.procs)
    elif a.cmd == "fit":
        fit(work)
    else:
        rep = report(work, a.algos or ["prod"], a.all, a.fold_variants)
        if a.out:
            Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
