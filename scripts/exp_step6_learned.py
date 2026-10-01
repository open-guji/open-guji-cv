"""X1 实验：Step6 定字＋弃权——学出来的逐候选打分 vs 现行手调规则（context-correction，按页留一折）。

    PYTHONPATH=. .venv/bin/python scripts/exp_step6_learned.py \
        ../open-guji-dataset/context-correction \
        --general-corpus corpus/external/daizhige_zhaoling.txt \
        --book-corpus $GUJI_WORKSPACE/corpus/zongmu_wuyingdian_reference.txt \
        --out runs/x1/step6_ctx.json

口径同 ``eval_context_correction.py --gate 0.70``：前文用列内金标（教师强制，取末 2 字），
冻结候选，只在候选内选；**额外**用后文基线首选字（非金标，线上可得）做窗口特征。
本书 LM 先挖掉全部测试页窗口（与 eval 脚本相同）→ 特征里没有任何页的答案。
CV 以页为组；弃权阈值 τ 在每个外折的**内层** OOF 上定（不看外折测试页）。
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
warnings.filterwarnings("ignore")

from open_guji_cv.steps.step6_signals import (FEATURE_GROUPS, FEATURES,  # noqa: E402
                                               SIGNAL_VERSION, SignalCtx, slot_rows)

# 泄漏特征：冻结候选池里 align 格「金标不是首选时，金标 100%（277/277）是 rapidocr 源候选」，
# 非金标非首选候选只有 1.4% 是 rapidocr——即池子构造时把整理本字塞进去并标成 rapidocr。
# 这是评测集构造痕迹，不是线上能用的信号；一律剔除（含到 --leaky 才放回，仅作对照）。
DROP = {"is_rapid"}
TAU_GRID = [round(x, 3) for x in np.arange(0.0, 1.0001, 0.025)]


def build_ctx(args, gold_texts, with_book: bool) -> SignalCtx:
    from eval_context_correction import heldout_corpus
    from open_guji_cv.clustering.confusable import partners
    from open_guji_cv.clustering.lm import InterpolatedLM, train_ngram
    from open_guji_cv.clustering.variants import VariantMap

    vpath = REPO / "config" / "charset" / "variants.tsv"
    vm = VariantMap.load(vpath if vpath.exists() else None)
    raw = Path(args.general_corpus).read_text(encoding="utf-8")
    gen = train_ngram([vm.normalize_text(x) for x in raw.split("\n") if x.strip()], 3, 2)
    book = None
    if with_book:
        raw = Path(args.book_corpus).read_text(encoding="utf-8")
        held, removed = heldout_corpus(raw, gold_texts)
        assert removed > 0, "没挖掉测试页窗口，本书 LM 在背答案"
        book = train_ngram([vm.normalize_text(x) for x in held.split("\n") if x.strip()], 3, 1)
        mix = InterpolatedLM([(gen, 0.1), (book, 0.9)])      # 现行混合口径
    else:
        mix = InterpolatedLM([(gen, 1.0)])
    return SignalCtx(semantic=vm.semantic, partners=partners(), lm_gen=gen,
                     lm_book=book, lm_mix=mix)


def extract(samples, ctx: SignalCtx):
    rows, meta = [], []
    for s in samples:
        page = str(s["page"]) if "page" in s else str(s.get("id"))
        for ci, col in enumerate(s["columns"]):
            sl_all = [sl for sl in col["slots"] if sl["candidates"]]
            for k, sl in enumerate(sl_all):
                cands = sl["candidates"]
                prev = tuple(x["gold"] for x in sl_all[:k])
                nxt = tuple(x["candidates"][0]["char"] for x in sl_all[k + 1:k + 3])
                X = slot_rows(cands, prev, nxt, ctx)
                for j, c in enumerate(cands):
                    rows.append(X[j])
                    meta.append((sl["instance_id"], page, j, int(c["char"] == sl["gold"]),
                                 sl.get("origin") or "align", len(cands),
                                 int(any(c2["char"] == sl["gold"] for c2 in cands))))
    X = np.array(rows)
    sid = [m[0] for m in meta]
    uniq = {s: i for i, s in enumerate(dict.fromkeys(sid))}
    return {"X": X, "slot": np.array([uniq[s] for s in sid]),
            "page": np.array([m[1] for m in meta]), "j": np.array([m[2] for m in meta]),
            "y": np.array([m[3] for m in meta]), "origin": np.array([m[4] for m in meta]),
            "n": np.array([m[5] for m in meta]), "ing": np.array([m[6] for m in meta])}


def make_model(kind):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if kind == "lr":
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=2000))
    return HistGradientBoostingClassifier(max_depth=3, max_iter=80, learning_rate=0.08,
                                          min_samples_leaf=20, l2_regularization=1.0,
                                          random_state=0)


def slot_decide(D, idx, prob):
    """idx: 行下标数组（按 slot 聚）；prob: 对应校准概率。返回每个 slot 的 (best_j, m, base 行, best 行)。"""
    out = []
    slots = D["slot"][idx]
    order = np.argsort(slots, kind="stable")
    idx, prob, slots = idx[order], prob[order], slots[order]
    bounds = np.flatnonzero(np.diff(slots)) + 1
    for rows, p in zip(np.split(idx, bounds), np.split(prob, bounds)):
        q = p / max(p.sum(), 1e-9)
        j = D["j"][rows]
        b = int(np.argmin(j))          # 基线 = j==0
        k = int(np.argmax(q))
        out.append((rows[b], rows[k], float(q[k] - q[b]), k != b))
    return out


def outcome(D, dec, tau):
    rescued = harmed = flips = 0
    for base, best, m, chg in dec:
        if chg and m >= tau:
            flips += 1
            rescued += D["y"][best] == 1 and D["y"][base] == 0
            harmed += D["y"][base] == 1 and D["y"][best] == 0
    return flips, int(rescued), int(harmed)


def platt(raw, y):
    from sklearn.linear_model import LogisticRegression
    lr = LogisticRegression(C=100.0).fit(raw.reshape(-1, 1), y)
    return lambda r: lr.predict_proba(np.asarray(r).reshape(-1, 1))[:, 1]


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def fit_score(D, tr_idx, te_idx, kind, cols):
    m = make_model(kind).fit(D["X"][tr_idx][:, cols], D["y"][tr_idx])
    return m.predict_proba(D["X"][te_idx][:, cols])[:, 1]


def pick_tau(D, idx, prob, harm_w):
    dec = slot_decide(D, idx, prob)
    best, bt = -1e9, 1.01
    for t in TAU_GRID + [1.01]:
        f, r, h = outcome(D, dec, t)
        v = r - harm_w * h
        if v > best + 1e-9 or (abs(v - best) < 1e-9 and t > bt):
            best, bt = v, t
    return bt


def nested_cv(D, kind, cols, harm_w):
    """外折=留一页。内层=在其余页上再留一页产 OOF → Platt + 选 τ。返回外折 OOF 行级校准概率与每折 τ。"""
    pages = sorted(set(D["page"]))
    oof = np.zeros(len(D["y"]))
    taus = {}
    for pg in pages:
        te = np.flatnonzero(D["page"] == pg)
        tr = np.flatnonzero(D["page"] != pg)
        inner = np.zeros(len(tr))
        for pg2 in pages:
            if pg2 == pg:
                continue
            msk = D["page"][tr] == pg2
            inner[msk] = fit_score(D, tr[~msk], tr[msk], kind, cols)
        cal = platt(logit(inner), D["y"][tr])
        taus[pg] = pick_tau(D, tr, cal(logit(inner)), harm_w)
        raw = fit_score(D, tr, te, kind, cols)
        oof[te] = cal(logit(raw))
    return oof, taus


def report_nested(D, oof, taus):
    f = r = h = 0
    for pg in sorted(set(D["page"])):
        te = np.flatnonzero(D["page"] == pg)
        a, b, c = outcome(D, slot_decide(D, te, oof[te]), taus[pg])
        f += a; r += b; h += c
    return f, r, h


def rule_curve(D, gates):
    """现行规则：pick!=base & margin>=g & ncand>=2 才改。"""
    X = D["X"]; ci = {n: i for i, n in enumerate(FEATURES)}
    base = np.flatnonzero(D["j"] == 0)
    res = {}
    by_slot = {s: [] for s in D["slot"]}
    for i, s in enumerate(D["slot"]):
        by_slot[s].append(i)
    for g in gates:
        f = r = h = 0
        for s, rows in by_slot.items():
            if len(rows) < 2:
                continue
            pk = [i for i in rows if X[i, ci["rule_pick"]] == 1.0]
            b = rows[0]
            if not pk or pk[0] == b:
                continue
            if X[pk[0], ci["rule_margin"]] >= g:
                f += 1
                r += D["y"][pk[0]] == 1 and D["y"][b] == 0
                h += D["y"][b] == 1 and D["y"][pk[0]] == 0
        res[g] = (f, int(r), int(h))
    return res


def curve(D, oof, taus_grid):
    dec = slot_decide(D, np.arange(len(D["y"])), oof)
    return {t: outcome(D, dec, t) for t in taus_grid}


def best_at_budget(cv, budget):
    """翻转预算 ≤budget 时能拿到的最大净收益(救-坏)，以及对应 τ。"""
    best = None
    for t, (f, r, h) in sorted(cv.items()):
        if f <= budget and (best is None or (r - h) > (best[1] - best[2])):
            best = (f, r, h, t)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--general-corpus", required=True)
    ap.add_argument("--book-corpus", required=True)
    ap.add_argument("--harm-w", type=float, default=3.0, help="选 τ 时一次改坏抵几次救回")
    ap.add_argument("--out", default="runs/x1/step6_ctx.json")
    ap.add_argument("--leaky", action="store_true")
    ap.add_argument("--no-ablation", action="store_true")
    args = ap.parse_args()
    from eval_context_correction import load_samples
    samples = load_samples(Path(args.dataset))
    gold_texts = ["".join(sl["gold"] for c in s["columns"] for sl in c["slots"]) for s in samples]
    allc = [i for i, fn in enumerate(FEATURES) if args.leaky or fn not in DROP]
    report = {"signal_version": SIGNAL_VERSION, "harm_w": args.harm_w, "scenarios": {}}

    for scen, with_book in (("with_book", True), ("no_book", False)):
        ctx = build_ctx(args, gold_texts, with_book)
        D = extract(samples, ctx)
        nslot = len(set(D["slot"]))
        base_rows = D["j"] == 0
        S = {"n_slots": nslot, "n_rows": int(len(D["y"])),
             "baseline_top1": float(D["y"][base_rows].mean()),
             "gold_in_cands": float(D["ing"][base_rows].mean()),
             "flippable_slots": int((D["n"][base_rows] >= 2).sum())}
        gates = [0.0, .1, .2, .3, .4, .5, .6, .7, .8, .9]
        S["rule_curve"] = {str(g): v for g, v in rule_curve(D, gates).items()}
        S["models"] = {}
        for kind in ("lr", "hgb"):
            oof, taus = nested_cv(D, kind, allc, args.harm_w)
            f, r, h = report_nested(D, oof, taus)
            cv = curve(D, oof, TAU_GRID)
            from sklearn.metrics import brier_score_loss, roc_auc_score
            slot_ok = {}
            M = {"nested_tau": {"flips": f, "rescued": r, "harmed": h,
                                "gain": round((r - h) / nslot, 4),
                                "taus": {k: v for k, v in taus.items()}},
                 "auc_row": float(roc_auc_score(D["y"], oof)),
                 "brier_row": float(brier_score_loss(D["y"], oof)),
                 "curve": {str(t): v for t, v in cv.items()}}
            # 无门槛 argmax 的 top1
            dec = slot_decide(D, np.arange(len(D["y"])), oof)
            M["argmax_top1"] = float(np.mean([D["y"][b] for _, b, _, _ in dec]))
            # 同翻转预算比较：现行 gate=0.7 的翻转数
            f07 = S["rule_curve"]["0.7"][0]
            M["at_rule_budget"] = best_at_budget(cv, f07)
            # origin 分层（按 slot）
            lab = {}
            for og in ("human", "align"):
                rr = [(D["y"][b], D["y"][ba]) for ba, b, m, c in dec
                      if D["origin"][ba] == og and c and m >= 0.5]
                lab[og] = {"flips@tau.5": len(rr),
                           "rescued": sum(1 for n, o in rr if n and not o),
                           "harmed": sum(1 for n, o in rr if o and not n)}
            M["by_origin@tau0.5"] = lab
            if not args.no_ablation:
                abl = {}
                for g in FEATURE_GROUPS:
                    cols = [i for i in allc if FEATURES[i] not in FEATURE_GROUPS[g]]
                    o2, t2 = nested_cv(D, kind, cols, args.harm_w)
                    a, b, c = report_nested(D, o2, t2)
                    abl[f"-{g}"] = {"flips": a, "rescued": b, "harmed": c,
                                    "gain": round((b - c) / nslot, 4)}
                for g in FEATURE_GROUPS:           # 单组 + ocr 基础
                    keep = set(FEATURE_GROUPS["ocr"]) | set(FEATURE_GROUPS[g])
                    cols = [i for i in allc if FEATURES[i] in keep]
                    o2, t2 = nested_cv(D, kind, cols, args.harm_w)
                    a, b, c = report_nested(D, o2, t2)
                    abl[f"ocr+{g}"] = {"flips": a, "rescued": b, "harmed": c,
                                       "gain": round((b - c) / nslot, 4)}
                M["ablation"] = abl
            S["models"][kind] = M
        report["scenarios"][scen] = S
        print(f"[{scen}] done", flush=True)
        if scen == "with_book":
            import pickle
            pickle.dump({k: v for k, v in D.items()},
                        open(Path(args.out).with_suffix(".D.pkl"), "wb"))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                              encoding="utf-8")
    print("→", args.out)


if __name__ == "__main__":
    main()
