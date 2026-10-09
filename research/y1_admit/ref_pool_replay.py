# -*- coding: utf-8 -*-
"""「ref 刻例并进最终精验池」回放原型（overview#493）：只读 research/，不改 steps/。

glyph_match 现在：特征 kNN 取全库前 k=10 个刻例做 elastic 精验。有整理本字 ref 时，另取 ref 及其直接异体的刻例中
与本格特征最近的 N 个（缺省 3）并进精验池，再走**同一套**三档判决与护栏（全库候选仍在竞争）。
只改池，不改判据；池没变的格记录原样搬。

用法（env 同 run.sh）：
  GUJI_PRODUCTS_DIR=<快照 products 根> python ref_pool_replay.py <book> <输出 products 根> <shard>/<n> [N]
输出 `<输出根>/<book>/glyph_match/pNNNN.json`（改动格的 verdict/char/cov/candidates 等更新），其余产物自己 cp。"""
import json, os, sys, glob, time
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from lib import load_step
from open_guji_cv import variants as V
from open_guji_cv.core.book import load_book
from open_guji_cv.core.engine import Engine
from open_guji_cv.core.pipeline import default_pipeline_id, load_pipeline
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.glyph_match import GlyphMatchStep, _patch, consensus_same, human_confirmed_counts
from open_guji_cv.clustering.normalize import normalize_patch
from open_guji_cv.clustering.match import MatchResult, _PARTNER

book_id, out_root, shard = sys.argv[1:4]
NX = int(sys.argv[4]) if len(sys.argv) > 4 else 3
si, sn = (int(x) for x in shard.split("/"))
SRC = os.environ["GUJI_PRODUCTS_DIR"]
book = load_book(book_id)
eng = Engine(book, load_pipeline(default_pipeline_id(book)), log=lambda s: None)
ctx = eng.ctx
p = ctx.params_for(STEPS["glyph_match"])
if p.norm_stroke is None and getattr(book, "norm_stroke", None):
    p = p.model_copy(update={"norm_stroke": int(book.norm_stroke)})
m = GlyphMatchStep()._matcher(p)
confirmed = human_confirmed_counts(p.db_path) if p.consensus_min_confirmed > 0 else {}
F = np.asarray(m._feats)
ci = load_step(SRC, book_id, "cell_shrink")
coord = {}; ref_of = {}
for f in glob.glob(f"{SRC}/{book_id}/align_ref/p*.json"):
    d = next(iter(json.load(open(f, encoding="utf-8")).values()))
    for c in d.get("coord", []):
        coord[c["id"]] = c["ref_char"]
    for c in d.get("chars", []):
        ref_of[c["id"]] = c.get("align_char")


def match_aug(norm, exclude_id, extra_chars):
    """复刻 GlyphMatcher._match，只在精验池里多并入 extra_chars 的最近 NX 个刻例。→ (MatchResult, 是否并入新刻例)"""
    feat = m._feature.extract(norm[None, ...])[0]
    sims = F @ np.asarray(feat, dtype=np.float32)
    excl = m._same_cell_rows(exclude_id) if exclude_id is not None else set()
    if excl:
        sims = sims.copy(); sims[list(excl)] = -np.inf
    top = [int(j) for j in np.argsort(-sims)[: m.k]]
    if excl:
        top = [j for j in top if j not in excl]
    if not top:
        return MatchResult("diff", None, None, 0.0, 0.0), False
    idx = [j for c in extra_chars for j in m._rows_for(c) if j not in excl]
    extra = [idx[int(i)] for i in np.argsort(-sims[idx])[:NX]] if idx else []
    extra = [j for j in extra if j not in top]
    if not extra:
        return None, False
    pool = top + extra
    same_hits, unsure_best = [], {}
    best_cov, best_wmax, best_char, nv = 0.0, 0.0, None, 0
    for j in pool:
        v = m._verify(norm, m._patches[j], cov_high=m.cov_high, miss_wmax=m.miss_wmax)
        nv += 1
        if v.f1 > best_cov:
            best_cov, best_wmax, best_char = v.f1, v.diff_blob_ratio, m._chars[j]
        if v.verdict == "same":
            same_hits.append((v.f1, v.diff_blob_ratio, m._chars[j], m._ids[j]))
        elif v.verdict == "unsure":
            unsure_best[m._chars[j]] = max(unsure_best.get(m._chars[j], 0.0), v.f1)
    if same_hits:
        same_hits.sort(key=lambda t: -t[0])
        cov, wmax, char, iid = same_hits[0]
        cands = dict(unsure_best)
        for c2, w2, ch2, _ in same_hits:
            cands[ch2] = max(cands.get(ch2, 0.0), c2)
        if len({c for _, _, c, _ in same_hits}) > 1:
            return m._apply_shape_rerank(MatchResult("unsure", None, None, cov, wmax, sorted(cands.items(), key=lambda t: -t[1]),
                                                     guard="conflict", n_verified=nv), norm, exclude_id), True
        partners = _PARTNER.get(char, frozenset())
        if partners:
            for q in sorted(partners):
                cands.setdefault(q, 0.0)
            return m._apply_shape_rerank(MatchResult("unsure", None, None, cov, wmax, sorted(cands.items(), key=lambda t: -t[1]),
                                                     guard="never_match", n_verified=nv), norm, exclude_id), True
        return MatchResult("same", char, iid, cov, wmax, sorted(cands.items(), key=lambda t: -t[1]), n_verified=nv), True
    if unsure_best:
        return m._apply_shape_rerank(MatchResult("unsure", None, None, best_cov, best_wmax,
                                                 sorted(unsure_best.items(), key=lambda t: -t[1]), n_verified=nv), norm, exclude_id), True
    return m._apply_shape_rerank(MatchResult("diff", None, None, best_cov, best_wmax,
                                             [(best_char, best_cov)] if best_char else [], n_verified=nv), norm, exclude_id), True


files = sorted(glob.glob(f"{SRC}/{book_id}/glyph_match/p*.json"))
os.makedirs(f"{out_root}/{book_id}/glyph_match", exist_ok=True)
nchg = nverd = ntot = 0
t0 = time.time()
for fi, f in enumerate(files):
    if fi % sn != si:
        continue
    raw = json.load(open(f, encoding="utf-8"))
    key = next(iter(raw)); d = raw[key]
    page = int(os.path.basename(f)[1:5])
    for col in d["columns"]:
        for r in col.get("chars") or []:
            ntot += 1
            k = r["id"]
            ref = ref_of.get(k) or coord.get(k)
            if not ref or ref == "〓" or k not in ci or not ci[k].get("patch_key"):
                continue
            E = sorted({ref} | {c for c, _ in V.variants_of(ref) if len(c) == 1})
            img = _patch(ctx, ci[k]["patch_key"], page)
            norm = normalize_patch(img, stroke_width=p.norm_stroke, isotropic=(ci[k].get("step3_kind") == "punct"))
            res, used = match_aug(norm, k, E)
            if res is None:
                continue
            verdict, char, via = res.verdict, res.char, None
            if verdict == "unsure" and res.guard is None:
                hit = consensus_same(list(res.candidates), confirmed.get, p.consensus_cov, p.consensus_margin, p.consensus_min_confirmed)
                if hit:
                    verdict, char, via = "same", hit[0], f"consensus:{hit[1]}"
            new = dict(verdict=verdict, char=char, matched_id=res.matched_id, cov=round(float(res.cov), 4),
                       wmax=round(float(res.wmax), 2),
                       candidates=[[c, round(float(v), 4)] for c, v in res.candidates[: p.max_candidates]],
                       guard=res.guard, n_verified=int(res.n_verified), via=via)
            if (new["verdict"], new["char"], new["candidates"][:1], new["guard"]) != (r["verdict"], r["char"], [list(x) for x in r["candidates"][:1]], r.get("guard")) \
                    or abs(new["cov"] - r["cov"]) > 1e-6:
                nchg += 1
                if new["verdict"] != r["verdict"] or new["char"] != r["char"]:
                    nverd += 1
            r.update(new)
    json.dump(raw, open(f"{out_root}/{book_id}/glyph_match/{os.path.basename(f)}", "w", encoding="utf-8"), ensure_ascii=False)
    if (fi // sn) % 10 == 0:
        print(f"shard{si} p{page} 累计格{ntot} 改动{nchg} 判决变{nverd} {round(time.time()-t0)}s", flush=True)
print("done", ntot, nchg, nverd)
