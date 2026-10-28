"""文意 L2 模型小头训练与按册留出评测（A24 2026-10-28，线程「压低己已巳日曰人审率」）。

    python research/m7/ctx/l2model_train.py <L3 表目录> <输出目录> --groups ry,rm,jys [--eval <细读标注.jsonl>,…] [--folds 10]

- 训练样本：L3 答案表（`group_clf/1`）里给了字的格（strong 与非 strong 都收），外加大模型各遍都 high 说「其他」的格（类「其他」）。
  窗口取表键（建表时的前后各 20 字）。
- 特征：`ctx_l2.Encoder` 的目标位向量＋`FEAT` 各字填空 log 概率（与管线同一取法，单条推理、不 padding）。
- 头：标准化＋逻辑回归（C=0.05）；按册 10 折留出，报「门槛 → 覆盖、对表错、对细读错」；全量重训后写 `<组>.json`（`ctx_model/1`）。
- 门槛与护栏取 `PARAMS`（10-28 定的中档）；改了要重跑本脚本看留出表。
向量按窗口缓存在 `<输出目录>/_emb_<组>.npz`，重跑不重算。
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from open_guji_cv.groups import ctx_l2
from open_guji_cv.groups.ctx_l3 import _split_key

ENCODER = {"name": "SIKU-BERT/sikuroberta", "revision": "bb25260d5c321924fe4fb353c09191c0aaf5c5c6"}
FEAT = "日曰目己已巳"
CLS = {"ry": ["日", "曰", "其他"], "rm": ["日", "目", "其他"], "jys": ["己", "已", "巳", "其他"]}
#: 中档（sheldon 10-28 定「同意中档」：放行的格不再看，不放行的交 L3 在线，大模型不确定的交人）。按册留出（表答案为准）：
#: ry 覆盖 87.4% 错 5／8668，rm 82.7% 错 1／3317，jys 83.5% 错 0／2016。零错档是 ry 0.995／-3、rm 0.99／-1、jys 0.99／-1。
#: thr 概率门槛；other 组外形近字护栏（填空分差 ≥ d 弃权）；right_only 右邻字限定
PARAMS = {
    "ry": dict(thr=0.99, other={"chars": "目自臼白田口甘旦四百", "d": -1.0}),
    "rm": dict(thr=0.99, other={"chars": "曰自臼白田口甘旦四百", "d": 0.0}),
    "jys": dict(thr=0.99, other={"chars": "巴乙且旨", "d": 1.0}, right_only={"丑卯巳未酉亥": "己"}),
}


def examples(table: dict, g: str) -> list[dict]:
    out = []
    for cid, e in table["cells"].items():
        lr = _split_key(e.get("ctx"))
        if lr is None:
            continue
        vs = [v for v in (e.get("votes") or {}).values() if v]
        if e.get("char") is not None:
            y = e["char"] if e["char"] in CLS[g] else "其他"
        elif e.get("why") == "abstain:other" and vs and all(v[0] == "其他" and v[1] == "high" for v in vs):
            y = "其他"
        else:
            continue
        out.append(dict(id=cid, vol=cid.split(":")[0], left=lr[0], right=lr[1], y=y, strong=bool(e.get("strong"))))
    return out


def embed(enc, items, cache: Path, chars: str):
    old = dict(np.load(cache, allow_pickle=True)["d"].item()) if cache.exists() else {}
    H, L = [], []
    for i, (l, r) in enumerate(items):
        k = l + "|" + r
        if k not in old:
            old[k] = enc.encode(l, r, chars)
            if i % 500 == 0:
                print(f"  emb {i}/{len(items)}", file=sys.stderr, flush=True)
        h, lp = old[k]
        H.append(h)
        L.append(lp)
    np.savez(cache, d=np.array(old, dtype=object))
    return np.array(H, dtype=np.float32), L


def feats(H, L):
    return np.hstack([H, np.array([[lp[c] for c in FEAT] for lp in L], dtype=np.float32)])


def keep(g, ch, lp, right, p, P):
    """管线同款判定（`ctx_l2.judge` 的门槛与护栏）：→ 给出的类或 None。"""
    if p < P["thr"]:
        return None
    if ch != "其他":
        oth = P["other"]["chars"]
        if max(lp[c] for c in oth) - lp[ch] >= P["other"]["d"]:
            return None
        for s, only in (P.get("right_only") or {}).items():
            if right[:1] and right[:1] in s and ch != only:
                return None
    return ch


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    ap = argparse.ArgumentParser()
    ap.add_argument("tables"); ap.add_argument("out")
    ap.add_argument("--groups", default="ry,rm,jys"); ap.add_argument("--folds", type=int, default=10)
    ap.add_argument("--eval", default="", help="细读标注 jsonl（id、left、right、form、conf），逗号分隔；只评测不训练")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    enc = ctx_l2.Encoder(ENCODER["name"], ENCODER["revision"])
    ev_all = []
    for f in [x for x in a.eval.split(",") if x]:
        ev_all += [json.loads(s) for s in open(f, encoding="utf-8") if s.strip()]
    report = {}
    for g in a.groups.split(","):
        P = PARAMS[g]
        chars = "".join(dict.fromkeys(FEAT + P["other"]["chars"]))
        ex = examples(json.loads(Path(a.tables, f"{g}.json").read_text(encoding="utf-8")), g)
        H, L = embed(enc, [(e["left"], e["right"]) for e in ex], out / f"_emb_{g}.npz", chars)
        X = feats(H, L); y = np.array([e["y"] for e in ex])
        vols = sorted({e["vol"] for e in ex}); fold = {v: i % a.folds for i, v in enumerate(vols)}
        F = np.array([fold[e["vol"]] for e in ex])
        # 细读标注（日曰目三字联读）只评 ry／rm：ry 里 目＝其他，rm 里 曰＝其他
        ev = [dict(e, y=e["form"] if e["form"] in CLS[g][:-1] else "其他") for e in ev_all
              if g in ("ry", "rm") and e.get("form") and e.get("conf") == "high" and e.get("left") is not None]
        He, Le = embed(enc, [(e["left"], e["right"]) for e in ev], out / f"_emb_{g}_eval.npz", chars) if ev else (None, [])
        Xe = feats(He, Le) if ev else None
        Fe = np.array([fold.get(e["id"].split(":")[0], 0) for e in ev])
        got, got_e = [None] * len(ex), [None] * len(ev)
        for k in range(a.folds):
            tr = F != k
            sc = StandardScaler().fit(X[tr]); m = LogisticRegression(C=0.05, max_iter=3000).fit(sc.transform(X[tr]), y[tr])
            for idx, XX, LL, RR, G in ((np.where(F == k)[0], X, L, [e["right"] for e in ex], got),
                                       (np.where(Fe == k)[0] if ev else [], Xe, Le, [e["right"] for e in ev], got_e)):
                if len(idx) == 0:
                    continue
                pr = m.predict_proba(sc.transform(XX[idx]))
                for j, p in zip(idx, pr):
                    ch = m.classes_[p.argmax()]
                    G[j] = keep(g, ch, LL[j], RR[j], p.max(), P)
        cov = sum(x is not None for x in got) / len(ex)
        err = [ex[i]["id"] for i, x in enumerate(got) if x is not None and x != y[i]]
        cov_e = sum(x is not None for x in got_e)
        err_e = [ev[i]["id"] for i, x in enumerate(got_e) if x is not None and x != ev[i]["y"]]
        report[g] = dict(n=len(ex), cover=round(cov, 4), err_table=err, eval_n=len(ev), eval_cover=cov_e, err_eval=err_e)
        print(g, json.dumps(report[g], ensure_ascii=False), flush=True)
        sc = StandardScaler().fit(X); m = LogisticRegression(C=0.05, max_iter=3000).fit(sc.transform(X), y)
        head = {"schema": ctx_l2.SCHEMA, "group": g, "ver": f"{g}-l2m-2", "encoder": ENCODER, "feat_chars": FEAT,
                "classes": [str(c) for c in m.classes_], "mean": sc.mean_.round(6).tolist(), "scale": sc.scale_.round(6).tolist(),
                "coef": m.coef_.round(6).tolist(), "intercept": m.intercept_.round(6).tolist(), **P,
                "train": {"n": len(ex), "folds": a.folds, "lovo": report[g]}}
        Path(out, f"{g}.json").write_text(json.dumps(head, ensure_ascii=False), encoding="utf-8")
    Path(out, "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
