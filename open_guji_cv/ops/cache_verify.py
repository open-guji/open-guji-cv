# -*- coding: utf-8 -*-
"""`guji cache verify`：查图像缓存是不是对着现在这版行切分产物切的（2026-10-01）。

## 为什么要有这个

缓存文件只按名字认（`products/cache.py` 模块头「页级戳」一节）。产物被**外部换掉**——从服务器 tar 回来、
`snap import`、从备份还原——缓存里还是上一代产物切的图：vol03 就这样 16% 的列字块整体错了一格，
`glyph_match` 点名重算读到邻格的图，字形库一更新对位就漂移，而 `guji status` 一片新鲜。

页级戳只管**今后**写的缓存；老缓存没有戳，只能看内容：对每一列抽一格，把缓存里那张图与
「现在这版产物重新渲染出来的本格 / 上一格 / 下一格」比相似度。缓存图更像邻格 = 这一列错位。

只抽每列中间一格：错位是整列性的（竖向差了整数格），一格足够露馅，全查要把每页渲染一遍。

## 列图（`column_image`）也要查（2026-10-01）

字块只是下游；**列图缓存本身过期**更糟：vol02 有 179/1674 列、vol01 有 452/1478 列的缓存列图与现渲染的列图
形状不同（顶部多 15~22px），下游用它算 `n_raised_hint`，把一批本来 21 格的列判成「有抬头格」切成 22 格——
拿旧版代码和 HEAD 代码喂同一份缓存，结果一样，换成空缓存（走渲染）才与旧产物一致。所以 `verify_book`
先逐列比缓存列图与重新渲染的**形状**（便宜、不会误报），形状不同的页整页清掉列图与字块缓存。
"""
from __future__ import annotations

import json

import cv2
import numpy as np

#: 邻格比本格高出这么多才算错位（相关系数；正确的缓存图与自己的渲染几乎 ≥0.9，邻格通常 <0.5）
SHIFT_MARGIN = 0.05
#: 一列至少有这么多字格才抽样（太短的列邻格不可靠）
MIN_CHARS = 5


def _vec(img: np.ndarray) -> np.ndarray:
    v = cv2.resize(255 - img, (48, 48)).astype(np.float32).ravel()
    v -= v.mean()
    n = float(np.linalg.norm(v))
    return v / (n or 1.0)


def best_offset(cache_img: np.ndarray, own: np.ndarray, left: np.ndarray | None,
                right: np.ndarray | None, margin: float = SHIFT_MARGIN) -> int:
    """缓存图最像哪一格：0 = 本格（正常）；-1/+1 = 上一格/下一格（错位）。纯函数，好测。"""
    c = _vec(cache_img)
    sc = {0: float(c @ _vec(own))}
    if left is not None:
        sc[-1] = float(c @ _vec(left))
    if right is not None:
        sc[1] = float(c @ _vec(right))
    off = max(sc, key=sc.get)
    return off if off != 0 and sc[off] > sc[0] + margin else 0


def stale_column_images(eng, pages) -> dict[int, list[int]]:
    """缓存列图与现渲染形状不同的列：`{页: [列…]}`。"""
    from ..core.step import STEPS
    from ..utils.image_io import imread
    st = STEPS["column_warp"]
    root = eng.cache.root / eng.book.id / "column_image"
    out: dict[int, list[int]] = {}
    for pg in pages:
        for p in sorted(root.glob(f"p{pg:04d}c*.png")):
            ci = imread(str(p), 0)
            try:
                r = st.render(eng.ctx, "column_image", p.stem)
            except Exception:                              # noqa: BLE001
                continue
            if ci is None or r is None or ci.shape != r.shape:
                out.setdefault(pg, []).append(int(p.stem[-2:]))
    return out


def verify_book(eng, pages, fix: bool = False, log=print) -> dict:
    """查 `char_patch` 缓存；`fix=True` 把有问题的页的 `char_patch` 与 `column_image` 缓存整页清掉（惰性重建）。"""
    from ..core.spec import page_key
    from ..core.step import STEPS
    from ..utils.image_io import imread

    book = eng.book.id
    step = STEPS["cell_shrink"]
    cache_root = eng.cache.root / book / "char_patch"
    bad: dict[int, list[tuple[int, int]]] = {}
    n_cols = n_missing = 0
    for pg in pages:
        ci = eng.store.read(book, "cell_shrink", page_key(pg), "char_index")
        if ci is None:
            continue
        for col in ci.columns:
            if not col.ok:
                continue
            chars = [r for r in col.chars if r.cell_type == "char" and r.patch_key]
            if len(chars) < MIN_CHARS:
                continue
            i = len(chars) // 2
            cp = cache_root / f"{chars[i].patch_key}.png"
            if not cp.exists():
                n_missing += 1
                continue
            cache_img = imread(str(cp), 0)
            if cache_img is None:
                continue
            n_cols += 1

            def render(r):
                try:
                    return step.render(eng.ctx, "char_patch", r.patch_key)
                except Exception:                      # noqa: BLE001
                    return None
            own = render(chars[i])
            if own is None:
                continue
            off = best_offset(cache_img, own, render(chars[i - 1]), render(chars[i + 1]))
            if off:
                bad.setdefault(pg, []).append((col.col, off))
    stale_cols = stale_column_images(eng, pages)
    n_stale = sum(len(v) for v in stale_cols.values())
    for pg in stale_cols:
        bad.setdefault(pg, [])
    out = {"book": book, "pages_checked": len(list(pages)), "columns_checked": n_cols,
           "stale_column_image_columns": n_stale,
           "columns_without_cache": n_missing,
           "bad_columns": sum(len(v) for v in bad.values()) + n_stale,
           "bad_pages": sorted(bad), "detail": {str(k): v for k, v in sorted(bad.items())}}
    if fix and bad:
        n = 0
        for pg in bad:
            for kind in ("char_patch", "column_image"):
                n += eng.cache.invalidate(book, kind, key_prefix=page_key(pg))
        out["fixed_files_removed"] = n
    return out


def main_print(res: dict) -> None:
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if res["bad_columns"]:
        print(f"（其中缓存列图与现渲染形状不同 {res.get('stale_column_image_columns', 0)} 列，会让闸误判抬头格、切出 22 格）")
        print(f"\n⚠️ {res['bad_columns']} 列的字块缓存错位（{len(res['bad_pages'])} 页）。"
              "缓存与现在的行切分产物不是一代的——常见成因：产物从别处换进来（tar/snap import/还原备份）没清缓存。\n"
              "加 --fix 把这些页的字块/列图缓存清掉让它按现产物重建；之后凡是点名重算过的 glyph_match 要重做。")
    else:
        print("\n✓ 抽查的列缓存都与现行产物对得上。")
