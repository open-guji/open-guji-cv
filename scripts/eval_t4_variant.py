# -*- coding: utf-8 -*-
"""T4 变体形模板：在四庫「shape≠reading」异体分歧冻结子集上报 GW 开关前后的 top-1/5/10。

    GUJI_WORKSPACE=<四庫工作区> GUJI_CACHE_DIR=<沙箱 cache> \
      python scripts/eval_t4_variant.py --subset <冻结子集 jsonl> [--charset unicode-cjk-ab]

冻结子集每行 `{id, target_key, book, page, col, slot, shape, reading, ...}`——
来自四庫 `feedback/events/*.jsonl` 里 `kind=confirm && payload.v=confirm` 的
`shape != reading` 记录，按 `target.key`（物理格）去重取最新裁决，只保留双方都
是单个 CJK 表意字的（详见任务书-R-T4变体形模板.md 与本卡 done 单「负结果」一节）。

评的是：给这个字块图查候选，人工确认的 `reading` 有没有进 top-1/5/10——
`shape` 是印在纸上的异体写法，GlyphWiki 第六档模板的价值就在于「拿这个写法的
模板去够 reading 那个候选」。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", required=True, help="冻结子集 jsonl（t4_variant_subset.jsonl）")
    ap.add_argument("--charset", default="unicode-cjk-ab")
    ap.add_argument("--ckpt", default=None)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    import open_guji_cv.clustering.cnn_candidates as _cc
    from open_guji_cv.clustering.charset_spec import base_charset
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.rare_panel import _book_norm_stroke, rare_patch

    recs = [json.loads(ln) for ln in Path(a.subset).read_text(encoding="utf-8").splitlines() if ln.strip()]
    print(f"冻结子集 {len(recs)} 条")

    imgs, readings, shapes, ids = [], [], [], []
    missing = []
    for r in recs:
        ns = _book_norm_stroke(r["book"])
        img = rare_patch(r["book"], int(r["page"]), int(r["col"]), int(r["slot"]))
        if img is None:
            missing.append(r["id"])
            continue
        imgs.append(normalize_patch(img, stroke_width=ns))
        readings.append(r["reading"])
        shapes.append(r["shape"])
        ids.append(r["id"])
    print(f"取到字块图 {len(imgs)} / {len(recs)}（缺 {len(missing)}：{missing[:10]}{'...' if len(missing) > 10 else ''}）")
    if not imgs:
        print("一张图都没取到——先跑 pipeline 到 cell_shrink 把这些页的 char_patch 缓存出来。")
        return 1

    cs = base_charset(a.charset)
    print(f"候选字表 {a.charset}：{len(cs)} 字")
    cnn = CnnCandidates(a.ckpt or str(DEFAULT_CKPT))
    cnn._ensure()

    def _run(label: str, gw_enabled: bool) -> dict:
        cnn._gw_cs = None
        emb = cnn.emb_topk_batch(imgs, cs, k=max(a.k, 10), gw_enabled=gw_enabled)
        t1 = t5 = t10 = 0
        rows = []
        for (name, sc_list), g, s, rid in zip(
                [(None, r) for r in emb], readings, shapes, ids):
            order = [c for c, _ in sc_list]
            hit1 = bool(order) and order[0] == g
            hit5 = g in order[:5]
            hit10 = g in order[:a.k]
            t1 += hit1; t5 += hit5; t10 += hit10
            rows.append({"id": rid, "shape": s, "reading": g,
                         "top1": order[0] if order else None, "hit1": hit1, "hit5": hit5, "hit10": hit10})
        n = len(imgs)
        print(f"[{label}] n={n}  top-1={t1/n*100:5.1f}%  top-5={t5/n*100:5.1f}%  top-10={t10/n*100:5.1f}%")
        return {"n": n, "top1": t1 / n * 100, "top5": t5 / n * 100, "top10": t10 / n * 100, "rows": rows}

    print(f"GlyphWiki 目录：{_cc.GW_CATALOG}（{'存在' if _cc.GW_CATALOG.exists() else '缺席'}）")
    off = _run("gw 关（基线）", False)
    on = _run("gw 开", True)

    # 哪些条目因为开 gw 而翻盘（正负两个方向都报，别只挑好看的）
    flips_fixed = [b for a_, b in zip(off["rows"], on["rows"]) if (not a_["hit1"]) and b["hit1"]]
    flips_broke = [a_ for a_, b in zip(off["rows"], on["rows"]) if a_["hit1"] and (not b["hit1"])]
    print(f"\ntop-1 翻盘：关→开修好 {len(flips_fixed)} 条，关→开弄坏 {len(flips_broke)} 条")
    for r in flips_fixed[:20]:
        print(f"  修好 {r['shape']}→{r['reading']}（{r['id']}）")
    for r in flips_broke[:20]:
        print(f"  弄坏 {r['shape']}→{r['reading']}（{r['id']}）")

    if a.json:
        Path(a.json).write_text(json.dumps(
            {"n_subset": len(recs), "n_scored": len(imgs), "missing": missing,
             "charset": a.charset, "off": {k: v for k, v in off.items() if k != "rows"},
             "on": {k: v for k, v in on.items() if k != "rows"},
             "flips_fixed": len(flips_fixed), "flips_broke": len(flips_broke)},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n写入 {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
