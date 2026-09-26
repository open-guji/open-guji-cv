# -*- coding: utf-8 -*-
"""类外评测：金标字在 CNN `classes` **之外**时，各候选源能给出什么。

    python scripts/eval_oov.py [--charset unicode-cjk-ab] [--ckpt <path>]

集由 `scripts/build_oov_bench.py` 建，见那份的模块头（为什么必须单独建）。

## 读数须知

- **`cls`（分类头）在这个集上恒为 0**，这不是 bug：类外字不在它的输出空间里。
  它留在表里是为了让「0.0」一直摆在眼前——别再拿含类内字的集去标 emb 的参数。
- 主指标是 **`emb` 的 top-1 / top-10**。`06-给embedding加独立度量损失.md`
  要改善的就是这两个数。
- `hog` 一列供参考（用户 2026-09-17 裁定 HOG 不进生产），它是唯一
  「字表可以临时扩」的源，在类外字上有独立信号，但实测打不过 emb。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BENCH = Path("cache/oov_bench")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--charset", default="unicode-cjk-ab",
                    help="候选字表（charset_spec 的基集名）")
    ap.add_argument("--ckpt", default=None, help="换 checkpoint 对比用")
    ap.add_argument("--with-hog", action="store_true")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--json", default=None, help="结果写到这个文件（对比历次用）")
    ap.add_argument("--no-gw", action="store_true", help="关掉 GlyphWiki 变体形模板档（cnn_candidates.GW_ENABLED），做对照")
    ap.add_argument("--real-proto", action="store_true",
                    help="开真刻例多原型档（R2/T11，cnn_candidates.REAL_PROTO_ENABLED，缺省关）")
    ap.add_argument("--real-proto-store", action="append", default=[],
                    help="真刻例来源 store:<glyph_store 目录>，可重复；配合 --real-proto 用")
    a = ap.parse_args()

    import cv2
    from open_guji_cv.clustering.cnn_candidates import (
        CNN_WEIGHT, DEFAULT_CKPT, EMB_WEIGHT, CnnCandidates, rrf)
    from open_guji_cv.clustering.charset_spec import base_charset

    items = [json.loads(l) for l in
             (BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    imgs, G = [], []
    for it in items:
        im = cv2.imread(str(BENCH / it["png"]), cv2.IMREAD_GRAYSCALE)
        if im is None:
            continue
        imgs.append((im > 127).astype(np.uint8))   # 存盘时 ×255，读回来还原 {0,1}
        G.append(it["char"])
    cs = base_charset(a.charset)
    print(f"集 {len(G)} 条 / {len(set(G))} 字种；字表 {a.charset} {len(cs)} 字")

    if a.no_gw:
        import open_guji_cv.clustering.cnn_candidates as _cc
        _cc.GW_ENABLED = False
    real_exclude_ids: frozenset = frozenset()
    if a.real_proto:
        import open_guji_cv.clustering.cnn_candidates as _cc
        _cc.REAL_PROTO_ENABLED = True
        _cc.REAL_PROTO_SPECS = tuple(a.real_proto_store)
        # 留一法：这批评测字自己的物理格不许进它自己的真刻例模板（同 5-a 的教训
        # 「自证不是证据」）——按 `id` 摘，`_real_index` 里再按物理格（同册同页
        # 同列、格号相差 <=2）扩摘一圈，见 `cnn_candidates._real_index` 文档。
        real_exclude_ids = frozenset(it["id"] for it in items if it.get("id"))
    cnn = CnnCandidates(a.ckpt or str(DEFAULT_CKPT))
    from open_guji_cv.clustering.cnn_candidates import GW_CATALOG, GW_ENABLED, REAL_PROTO_SPECS
    print(f"GlyphWiki 变体形模板档：{'开' if (GW_ENABLED and GW_CATALOG.exists()) else '关/缺席'}（{GW_CATALOG}）", flush=True)
    print(f"真刻例多原型档：{'开 ' + str(REAL_PROTO_SPECS) if a.real_proto else '关'}"
          f"（留一法摘除 {len(real_exclude_ids)} 个物理格）", flush=True)
    cnn._ensure()
    t0 = time.time()
    cls = [[c for c, _ in r] for r in cnn.topk_batch(imgs, cs, k=a.k)]
    emb = [[c for c, _ in r] for r in cnn.emb_topk_batch(imgs, cs, k=a.k, real_exclude_ids=real_exclude_ids)]
    dt = time.time() - t0
    rows = {"cls": cls, "emb": emb,
            "rrf": [rrf(c, e, k=a.k, weights=(CNN_WEIGHT, EMB_WEIGHT))
                    for c, e in zip(cls, emb)]}
    if a.with_hog:
        from open_guji_cv.clustering.font_candidates import candidates_batch
        rows["hog"] = [[h.char for h in r] for r in candidates_batch(imgs, cs, k=a.k)]

    n = len(G)
    print(f"检索 {dt:.1f}s\n")
    print(f'{"源":<6} {"top-1":>8} {"top-5":>8} {"top-10":>8}')
    res = {}
    for name, L in rows.items():
        t1 = sum(1 for r, g in zip(L, G) if r and r[0] == g)
        t5 = sum(1 for r, g in zip(L, G) if g in r[:5])
        t10 = sum(1 for r, g in zip(L, G) if g in r[:a.k])
        res[name] = {"top1": t1 / n * 100, "top5": t5 / n * 100, "top10": t10 / n * 100}
        print(f'{name:<6} {t1/n*100:7.1f}% {t5/n*100:7.1f}% {t10/n*100:7.1f}%')

    # 按来源拆开看：用户裁决那批是「人亲眼确认过」的，比库标签更硬
    srcs = [it["src"] for it in items][:n]
    print()
    for s in sorted(set(srcs)):
        idx = [i for i, x in enumerate(srcs) if x == s]
        t1 = sum(1 for i in idx if emb[i] and emb[i][0] == G[i])
        t10 = sum(1 for i in idx if G[i] in emb[i][:a.k])
        print(f'  emb / src={s:<8} n={len(idx):4d}  top1={t1/len(idx)*100:5.1f}%  '
              f'top10={t10/len(idx)*100:5.1f}%')

    if a.json:
        Path(a.json).write_text(json.dumps(
            {"charset": a.charset, "ckpt": a.ckpt or str(DEFAULT_CKPT),
             "n": n, "n_chars": len(set(G)), "result": res,
             "real_proto": a.real_proto, "real_proto_store": a.real_proto_store,
             "real_proto_loo": len(real_exclude_ids)},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n→ {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
