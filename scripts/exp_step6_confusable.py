"""X1 实验（第二集）：confusable-context 154 题上，学出来的逐候选打分 vs 现行 n-gram。

二选一、纯上下文（题面不含字形候选），所以特征只有：本书/通用 LM 的窗口分（左 2 + 右 2，
右侧取 OCR 列文本）、OCR 读到的字及其置信、字形覆盖率（多半缺）。
本书 LM 先把全部题的整理本列从语料里挖掉（heldout 口径）。
分组折：按页、以及按形近对（leave-one-pair-out，量跨对泛化）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import exp_step6_learned as E  # noqa: E402

FEATS = ["lg", "lb", "lm", "w_lg", "w_lb", "w_lm", "ocr_eq", "ocr_p", "ocr_p_eq", "cov", "has_cov", "is_base"]
GROUPS = {"lm_ctx": ["lg", "lb", "lm", "w_lg", "w_lb", "w_lm"], "ocr": ["ocr_eq", "ocr_p", "ocr_p_eq", "is_base"],
          "shape": ["cov", "has_cov"]}


def build(cases, gen, book, mix):
    rows, meta = [], []
    for s, c in enumerate(cases):
        txt = c["col_masked"]
        i = txt.index("△")
        prev, nxt = tuple(txt[max(0, i - 2):i]), tuple(txt[i + 1:i + 3])
        opts = c["options"]
        base = c["ocr_char"] if c["ocr_char"] in opts else opts[0]
        vals = {}
        for o in opts:
            def win(lm):
                if lm is None:
                    return 0.0
                t = lm.logp(o, prev)
                if len(nxt) >= 1:
                    t += lm.logp(nxt[0], (prev[-1:] if prev else ()) + (o,))
                if len(nxt) >= 2:
                    t += lm.logp(nxt[1], (o, nxt[0]))
                return t
            vals[o] = (gen.logp(o, prev), book.logp(o, prev) if book else 0.0, mix.logp(o, prev),
                       win(gen), win(book), win(mix))
        mx = [max(vals[o][k] for o in opts) for k in range(6)]
        for o in sorted(opts, key=lambda o: o != base):          # 基线排第 0
            v = [vals[o][k] - mx[k] for k in range(6)]
            eq = float(o == c["ocr_char"])
            p = float(c.get("ocr_prob") or 0.0)
            cov = c["shape_cov_gold"] if o == c["gold"] else c["shape_cov_other"]
            # 注意：shape_cov_gold/other 是按金标命名的——用它当特征=泄漏，故一律不用（置 0）
            rows.append(v + [eq, p, p * eq, 0.0, 0.0, float(o == base)])
            meta.append((s, c["id"].split(":")[1], c["pair"], int(o == c["gold"]), int(o != base),
                         c["tier"]))
    X = np.array(rows)
    return {"X": X, "slot": np.array([m[0] for m in meta]), "page": np.array([m[1] for m in meta]),
            "pair": np.array([m[2] for m in meta]), "y": np.array([m[3] for m in meta]),
            "j": np.array([m[4] for m in meta]), "origin": np.array([m[5] for m in meta])}


def run(D, group, cols, w, kind="lr"):
    D = dict(D, page=D[group])
    oof, taus = E.nested_cv(D, kind, cols, w)
    f, r, h = E.report_nested(D, oof, taus)
    dec = E.slot_decide(D, np.arange(len(D["y"])), oof)
    acc = float(np.mean([D["y"][b] for _, b, _, _ in dec]))
    return {"flips": f, "rescued": r, "harmed": h, "argmax_acc": acc,
            "curve": {str(t): v for t, v in E.curve(D, oof, E.TAU_GRID).items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--general-corpus", required=True)
    ap.add_argument("--book-corpus", required=True)
    ap.add_argument("--out", default="runs/x1/step6_conf.json")
    args = ap.parse_args()
    cases = json.loads((Path(args.dataset) / "cases.json").read_text(encoding="utf-8"))["cases"]
    from eval_context_correction import heldout_corpus
    from open_guji_cv.clustering.lm import InterpolatedLM, train_ngram
    from open_guji_cv.clustering.variants import VariantMap
    vm = VariantMap.load(REPO / "config/charset/variants.tsv")
    gen = train_ngram([vm.normalize_text(x) for x in
                       Path(args.general_corpus).read_text(encoding="utf-8").split("\n") if x.strip()], 3, 2)
    raw = Path(args.book_corpus).read_text(encoding="utf-8")
    golds = [c["col_ref_masked"].replace("△", c["gold"]) for c in cases]
    held, removed = heldout_corpus(raw, golds)
    print("heldout removed", removed)
    assert removed > 0
    book = train_ngram([vm.normalize_text(x) for x in held.split("\n") if x.strip()], 3, 1)
    rep = {"n": len(cases), "heldout_removed": removed, "scen": {}}
    for scen, bk in (("with_book", book), ("no_book", None)):
        mix = InterpolatedLM([(gen, .1), (bk, .9)]) if bk else InterpolatedLM([(gen, 1.0)])
        D = build(cases, gen, bk, mix)
        b0 = D["j"] == 0
        S = {"majority": max(np.mean([c["gold"] == c["options"][0] for c in cases]),
                             1 - np.mean([c["gold"] == c["options"][0] for c in cases])),
             "ocr_acc": float(D["y"][b0].mean())}
        # 现行 n-gram：纯 LM（混合）窗口分高者；与 baseline_r1 同类的臂
        for nm, k in (("ngram_ctx_mix", 2), ("ngram_win_mix", 5), ("ngram_win_gen", 3)):
            ok = []
            for s in sorted(set(D["slot"])):
                rr = np.flatnonzero(D["slot"] == s)
                ok.append(D["y"][rr[np.argmax(D["X"][rr, k])]])
            S[nm] = float(np.mean(ok))
        allc = list(range(len(FEATS)))
        S["learned"] = {}
        for kind in ("lr", "hgb"):
            for grp in ("page", "pair"):
                S["learned"][f"{kind}/{grp}"] = run(D, grp, allc, 3.0, kind)
        for g, fs in GROUPS.items():
            cols = [i for i, f in enumerate(FEATS) if f not in fs]
            S["learned"][f"lr/page/-{g}"] = run(D, "page", cols, 3.0, "lr")
        rep["scen"][scen] = S
        print(scen, {k: v for k, v in S.items() if k != "learned"})
        for k, v in S["learned"].items():
            print("  ", k, v["flips"], v["rescued"], v["harmed"], round(v["argmax_acc"], 4))
    Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
