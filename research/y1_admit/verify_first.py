# -*- coding: utf-8 -*-
"""方案 5「核对优先」试验（overview#493）：有整理本的格，只在「整理本字及其异体」的库刻例里核对像不像，
不在全字库里找最像。只读 research/，不改 steps/。

用法（env 同 run.sh：GUJI_WORKSPACE、GUJI_GLYPH_DB、PYTHONIOENCODING）：
  GUJI_PRODUCTS_DIR=<快照 products 根> python verify_first.py <book> <金标 jsonl> <输出 json> [最多格数]

每个有标签的格：取整理本字 ref（对位 align_char，没有取坐标对位）、期望集 E＝{ref}∪ref 的直接异体，
只对 E 的库刻例做 kNN(k=10)＋elastic 精验（与全库匹配同一把尺子），记 E 内最佳字／cov／verdict／耗时，
并带上全库匹配（快照 glyph_match）的 top1／cov 与金标字，之后离线对各判据算放行数与金标误放行。"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from lib import load_step, labels
from open_guji_cv import variants as V
from open_guji_cv.core.book import load_book
from open_guji_cv.core.engine import Engine
from open_guji_cv.core.pipeline import default_pipeline_id, load_pipeline
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.glyph_match import GlyphMatchStep, _patch
from open_guji_cv.clustering.normalize import normalize_patch

book_id, gold_f, out_f = sys.argv[1:4]
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 10 ** 9
SRC = os.environ["GUJI_PRODUCTS_DIR"]
book = load_book(book_id)
eng = Engine(book, load_pipeline(default_pipeline_id(book)), log=lambda s: None)
ctx = eng.ctx
step = STEPS["glyph_match"]
p = ctx.params_for(step)
if p.norm_stroke is None and getattr(book, "norm_stroke", None):
    p = p.model_copy(update={"norm_stroke": int(book.norm_stroke)})
matcher = GlyphMatchStep()._matcher(p)
print("库", len(matcher), "条", flush=True)

L = labels(book_id)
G = {}
for l in open(gold_f, encoding="utf-8"):
    d = json.loads(l); G[d["cell"]] = d
truth = {}
for k, g in {**L, **G}.items():
    if g["v"] == "ok":
        truth[k] = g["shown"]
    elif g["v"] == "wrong" and g.get("char"):
        truth[k] = g["char"]
if os.environ.get("VF_EXTRA"):          # 额外的格（无标签，如待审格）：truth 记 None，只量核对结果
    for l in open(os.environ["VF_EXTRA"], encoding="utf-8"):
        truth.setdefault(l.strip(), None)
gm = load_step(SRC, book_id, "glyph_match"); ci = load_step(SRC, book_id, "cell_shrink")
al = load_step(SRC, book_id, "align_ref")
coord = {}
import glob
for f in glob.glob(f"{SRC}/{book_id}/align_ref/p*.json"):
    d = next(iter(json.load(open(f, encoding="utf-8")).values()))
    for c in d.get("coord", []):
        coord[c["id"]] = c["ref_char"]

F = np.asarray(matcher._feats)
rows = []
cells = [k for k in truth if k in ci and ci[k].get("patch_key") and k in gm]
cells.sort()
cells = cells[:limit]
t_all = time.time()
for n, k in enumerate(cells):
    a = al.get(k, {}); ref = a.get("align_char") or coord.get(k) or None
    if ref == "〓":
        ref = None
    page = int(k.split(":")[1])
    rec = dict(cell=k, truth=truth.get(k), ref=ref, op=a.get("align_op"),
               full_top=(gm[k]["candidates"][0][0] if gm[k]["candidates"] else None),
               full_cov=gm[k]["cov"], full_verdict=gm[k]["verdict"],
               full_cands=[(c, v) for c, v in gm[k]["candidates"][:3]])
    if ref:
        E = sorted({ref} | {c for c, _ in V.variants_of(ref) if len(c) == 1})
        idx = [j for c in E for j in matcher._rows_for(c)]
        rec["E"] = E; rec["n_rows"] = len(idx)
        if idx:
            img = _patch(ctx, ci[k]["patch_key"], page)
            norm = normalize_patch(img, stroke_width=p.norm_stroke, isotropic=False)
            t0 = time.time()
            feat = matcher._feature.extract(norm[None, ...])[0]
            sims = F[idx] @ np.asarray(feat, dtype=np.float32)
            top = [idx[int(i)] for i in np.argsort(-sims)[: matcher.k]]
            best = {}
            for j in top:
                v = matcher._verify(norm, matcher._patches[j], cov_high=matcher.cov_high, miss_wmax=matcher.miss_wmax)
                c = matcher._chars[j]
                cur = best.get(c)
                if cur is None or v.f1 > cur[0]:
                    best[c] = (round(float(v.f1), 4), round(float(v.diff_blob_ratio), 2), v.verdict)
            rec["t_check"] = round(time.time() - t0, 4)
            rec["E_best"] = sorted(((c, *v) for c, v in best.items()), key=lambda t: -t[1])
            t0 = time.time()
            matcher.match(norm)
            rec["t_full"] = round(time.time() - t0, 4)
    rows.append(rec)
    if (n + 1) % 100 == 0:
        print(n + 1, len(cells), round(time.time() - t_all), "s", flush=True)
json.dump(rows, open(out_f, "w"), ensure_ascii=False)
print("done", len(rows))
