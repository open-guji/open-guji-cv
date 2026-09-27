"""评测：审卡默认首选改前／改后命中率（人裁集、维基锚定集），两路一致率与一致时精确率。

  GUJI_GLYPH_DB=<借来的四庫库> GUJI_CACHE_DIR=<沙箱> python evaluate.py human.pkl corpus.pkl > report.json

CNN 一路直接调线上代码 `review.borrow_first.cnn_ranks_for_patches`（与审卡装配同一条），
融合用 `pick_first` / `first_view`，量的就是线上那份逻辑。

「命中」两种口径：strict（字相同）与 rel（字相同或 `config/variants/variants.json`
登记的异体对，同 R 的 a1 `rel()`，用来对照 R 报的 52.4% / 94.2%）。
「改前」有两个：pixel = `glyph_match` 首位（R 的口径）；card = 改前审卡按字种分组用的
`_top_pick` 链（Step6-AI → 上下文 → 库 → OCR；全唐文没有 Step6-AI）。
"""
from __future__ import annotations

import json
import os
import pickle
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_v = json.loads((REPO / "config/variants/variants.json").read_text(encoding="utf-8"))


def rel(a, b):
    if a is None or b is None:
        return False
    if a == b:
        return True
    P, D = _v.get("pairs", {}), _v.get("directed", {})
    return (b in (P.get(a) or {})) or (a in (P.get(b) or {})) or (b in (D.get(a) or {})) or (a in (D.get(b) or {}))


def card_pick(r):
    if r.get("ctx"):
        return r["ctx"]
    if r["pixel"]:
        return r["pixel"][0][0]
    if r.get("ocr"):
        return r["ocr"][0][0]
    return None


def pct(a, b):
    return f"{a}/{b}={a / b:.1%}" if b else f"{a}/0"


def main():
    from open_guji_cv.review.borrow_first import cnn_ranks_for_patches, first_view
    db = os.environ["GUJI_GLYPH_DB"]
    report = {}
    for path in sys.argv[1:]:
        recs = pickle.load(open(path, "rb"))
        ranks = cnn_ranks_for_patches([r["norm"] for r in recs], db)
        name = Path(path).stem
        rows = []
        for r, cr in zip(recs, ranks):
            vc = first_view(r["pixel"], cr, "cnn")
            vr = first_view(r["pixel"], cr, "rrf")
            rows.append({"id": r["id"], "src": r["src"], "truth": r["truth"],
                         "pixel": vc["pixel"], "card": card_pick(r), "cnn": vc["char"],
                         "rrf": vr["char"], "agree": vc["agree"],
                         "cnn_top5": [c for c, _ in cr]})
        out = {"n": len(rows)}
        for sub, rs in [("all", rows)] + sorted(
                ((s, [x for x in rows if x["src"] == s]) for s in {x["src"] for x in rows})):
            n = len(rs)
            d = {"n": n}
            for key in ("pixel", "card", "cnn", "rrf"):
                d[key] = {"strict": pct(sum(x[key] == x["truth"] for x in rs), n),
                          "rel": pct(sum(rel(x[key], x["truth"]) for x in rs), n)}
            d["cnn_top5_rel"] = pct(sum(any(rel(c, x["truth"]) for c in x["cnn_top5"]) for x in rs), n)
            both = [x for x in rs if x["agree"] is not None]
            ag = [x for x in both if x["agree"]]
            d["agree_rate"] = pct(len(ag), len(both))
            d["agree_precision_rel"] = pct(sum(rel(x["cnn"], x["truth"]) for x in ag), len(ag))
            dis = [x for x in both if not x["agree"]]
            d["disagree"] = {k: pct(sum(rel(x[k], x["truth"]) for x in dis), len(dis))
                             for k in ("pixel", "cnn", "rrf")}
            d["cross_pixel_cnn_rel"] = dict(Counter(
                f"像素{'对' if rel(x['pixel'], x['truth']) else '错'}&CNN{'对' if rel(x['cnn'], x['truth']) else '错'}"
                for x in rs))
            d["truth_in_lib_proxy"] = pct(sum(any(rel(c, x["truth"]) for c in x["cnn_top5"]) for x in rs), n)
            out[sub] = d
        # 错例前 15（CNN 错）
        errs = Counter((x["truth"], x["cnn"]) for x in rows if not rel(x["cnn"], x["truth"]))
        out["cnn_err_top"] = [f"{t}→{p}×{k}" for (t, p), k in errs.most_common(15)]
        errs = Counter((x["truth"], x["pixel"]) for x in rows if not rel(x["pixel"], x["truth"]))
        out["pixel_err_top"] = [f"{t}→{p}×{k}" for (t, p), k in errs.most_common(15)]
        report[name] = out
        json.dump(rows, open(Path(path).with_suffix(".rows.json"), "w"), ensure_ascii=False)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
