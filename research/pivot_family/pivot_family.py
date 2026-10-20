# -*- coding: utf-8 -*-
"""离线实验：「以字找字」（pivot 字 → 异体族/形近族 → 按字块图排序）与「自动异体族展开」。

只读：不改引擎、不碰 products；用 r5 checkpoint 和 unicode-cjk-ab 字体模板索引。

    cd open-guji-cv && .venv/bin/python research/pivot_family/pivot_family.py --out <json>

（`cache/` 下要有 train_bundle.zip 解出的 oov_bench、glyph_bench；首跑建 7 万字模板索引约 40 分钟）

靶子：cache/oov_bench（314，类外）+ cache/glyph_bench 的 unseen / seen_test。
金标 g = 刻本字形（精确码位）。

A. 现役基线：emb 全表 top-k（与 eval_oov 同口径）。
B. 自动族展开（不需人输入）：top-3 照旧，之后插入 top-1..3 的异体族成员（按余弦），
   再接 emb 原序补满。量 top-5/10，以及「展示 N 个」时的召回。
C. 以字找字：模拟用户先认出一个「接近的字」p（取 g 的异体族里整理本最常用的那个，
   即用户通常从整理本/读音知道的正字），系统给 p 的族（异体一跳/两跳 ∪ 形近表），
   按字块图余弦排序。量 g 在族内的名次；对照「族按码位/来源顺序不排」（≈字统网列表）。
   另两档对照：pv30＝只取 p 的字体模板在模板空间里最近的 30 个字（不用异体表）；
   f1pv＝一跳族 ∪ pv30。
注意 C 的 p 是从 g 的族里挑的，所以「族里有没有 g」恒为是——这里量的是**排序**，
异体表的**覆盖**（用户真实想到的 p 和 g 之间有没有边）量不了，见 README。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def load_items(limit_seen: int):
    import cv2
    from open_guji_cv.clustering.normalize import normalize_patch
    out = []
    ob = Path("cache/oov_bench")
    for ln in (ob / "items.jsonl").read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        it = json.loads(ln)
        if len(it["char"]) != 1 or not ("㐀" <= it["char"] or ord(it["char"]) > 0x2000):
            continue
        if ord(it["char"]) < 0x2E80:          # 拉丁字母噪声标签
            continue
        im = cv2.imread(str(ob / it["png"]), cv2.IMREAD_GRAYSCALE)
        if im is None:
            continue
        out.append(("oov", it["char"], (im > 127).astype(np.uint8)))
    gb = Path("cache/glyph_bench")
    nseen = 0
    for ln in (gb / "items.jsonl").read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        it = json.loads(ln)
        sp = it.get("split")
        if sp not in ("unseen", "seen_test"):
            continue
        if sp == "seen_test":
            if nseen >= limit_seen:
                continue
            nseen += 1
        im = cv2.imread(str(it["png"]).replace("\\", "/"), cv2.IMREAD_GRAYSCALE)
        if im is None:
            continue
        out.append((sp, it["char"], normalize_patch(im)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seen", type=int, default=800, help="seen_test 取前 N 条")
    a = ap.parse_args()

    from open_guji_cv.clustering.charset_spec import base_charset
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates
    from open_guji_cv.clustering.confusables import load_pairs
    from open_guji_cv.clustering.rare_panel import _corpus_freq
    from open_guji_cv.steps.align_ref import DEFAULT_CORPUS
    from open_guji_cv.variants import NEVER_SOURCES, _graph

    G = _graph()
    freq = _corpus_freq(DEFAULT_CORPUS)
    near = load_pairs()

    def fam1(c):  # 一跳异体（去形近钓鱼、通假）
        return [v for v, tags in G.variants_of(c) if set(tags) - NEVER_SOURCES]

    def fam2(c, cap=80):
        s = [c] + fam1(c)
        seen = set(s)
        for v in list(s[1:]):
            for w in fam1(v):
                if w not in seen and len(seen) < cap:
                    seen.add(w); s.append(w)
        return s

    def near_of(c, k=8):
        return [b for b, *_ in near.get(c, [])[:k]]

    cs = tuple(base_charset("unicode-cjk-ab"))
    cnn = CnnCandidates(str(DEFAULT_CKPT))
    cnn._ensure()
    mat, names = cnn._emb_index(cs)
    pos = {c: i for i, c in enumerate(names)}
    print(f"索引 {mat.shape}", flush=True)

    items = load_items(a.seen)
    print(f"靶子 {len(items)} 条：{Counter(t for t, _, _ in items)}", flush=True)
    Q = cnn.embed([im for _, _, im in items])
    S = Q @ mat.T                                   # (N, V)

    def rank_in(order, g):
        try:
            return order.index(g) + 1
        except ValueError:
            return None

    rows = []
    for i, (tier, g, _) in enumerate(items):
        s = S[i]
        top = np.argsort(-s)[:50]
        base = [names[j] for j in top]
        # B. 自动族展开：top-3 + 其异体族（按余弦）+ 原序
        head = base[:3]
        extra = []
        for c in head:
            for v in fam1(c):
                if v in pos and v not in head and v not in extra:
                    extra.append(v)
        extra.sort(key=lambda v: -s[pos[v]])
        merged = head + extra[:4]
        for c in base:
            if c not in merged:
                merged.append(c)
        # B'. 族作独立分组：主列表 10 个 + top-1..3 的族全部另列
        fam_group = [v for v in extra if v not in base[:10]]
        # C. 以字找字
        fam_g = [v for v in fam1(g)]
        pivot = None
        if fam_g:
            cand = [g] + fam_g
            pivot = max(cand, key=lambda c: (freq.get(c, 0), c == g))
        r = {"tier": tier, "g": g, "base_rank": rank_in(base, g),
             "auto_rank": rank_in(merged, g),
             "famgroup_hit": g in fam_group, "famgroup_n": len(fam_group),
             "has_family": bool(fam_g), "g_freq": freq.get(g, 0), "pivot": pivot}
        if pivot is not None:
            pj = pos.get(pivot)
            pv = [names[j] for j in np.argsort(-(mat @ mat[pj]))[:30]] if pj is not None else [pivot]
            for name, pool in (("f1", [pivot] + fam1(pivot)),
                               ("pv30", pv),
                               ("f1pv", list(dict.fromkeys([pivot] + fam1(pivot) + pv))),
                               ("f2", fam2(pivot)),
                               ("f2n", list(dict.fromkeys(fam2(pivot) + near_of(pivot) +
                                                          [x for v in fam1(pivot) for x in near_of(v, 3)])))):
                pool = [c for c in pool if c in pos]
                ranked = sorted(pool, key=lambda c: -s[pos[c]])
                r[name + "_n"] = len(pool)
                r[name + "_rank"] = rank_in(ranked, g)
                r[name + "_unsorted_rank"] = rank_in(sorted(pool), g)   # 码位序≈不排序的列表
            r["pivot_is_g"] = pivot == g
        rows.append(r)

    def topk(rs, key, k):
        n = len(rs)
        h = sum(1 for x in rs if x.get(key) is not None and x[key] <= k)
        return h, n

    summary = {}
    for tier in ("oov", "unseen", "seen_test", "all"):
        rs = [x for x in rows if tier == "all" or x["tier"] == tier]
        if not rs:
            continue
        d = {"n": len(rs)}
        for key in ("base_rank", "auto_rank"):
            d[key] = {f"top{k}": topk(rs, key, k) for k in (1, 3, 5, 10)}
        d["base10_or_famgroup"] = sum(1 for x in rs if (x["base_rank"] or 99) <= 10 or x["famgroup_hit"])
        d["famgroup_n_median"] = float(np.median([x["famgroup_n"] for x in rs]))
        fr = [x for x in rs if x["pivot"] is not None]
        d["pivot_n"] = len(fr)
        d["pivot_is_g"] = sum(1 for x in fr if x["pivot_is_g"])
        for name in ("f1", "f2", "f2n", "pv30", "f1pv"):
            d[name] = {
                "pool_n_median": float(np.median([x[name + "_n"] for x in fr])) if fr else None,
                "in_pool": sum(1 for x in fr if x[name + "_rank"] is not None),
                **{f"top{k}": topk(fr, name + "_rank", k)[0] for k in (1, 3, 5, 10)},
                "unsorted_top5": topk(fr, name + "_unsorted_rank", 5)[0],
            }
        # 只看 g ≠ pivot（刻本用了非常用异体）——这正是「去字统网翻一大批」的情形
        fv = [x for x in fr if not x["pivot_is_g"]]
        d["variant_shape_n"] = len(fv)
        d["variant_shape_base"] = {f"top{k}": topk(fv, "base_rank", k)[0] for k in (1, 5, 10)}
        for name in ("f1", "f2", "f2n", "pv30", "f1pv"):
            d["variant_shape_" + name] = {f"top{k}": topk(fv, name + "_rank", k)[0] for k in (1, 3, 5, 10)}
            d["variant_shape_" + name]["unsorted_top5"] = topk(fv, name + "_unsorted_rank", 5)[0]
            d["variant_shape_" + name]["pool_n_median"] = float(np.median([x[name + "_n"] for x in fv])) if fv else None
        summary[tier] = d
    Path(a.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
