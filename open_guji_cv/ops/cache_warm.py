# -*- coding: utf-8 -*-
"""`guji cache warm`：多进程预渲字块缓存（`char_patch`），给串行步省时间（overview#429）。

## 为什么

快照（`guji snap import`）只带 products，不带 `cache/`。导入后第一次读字块的步（典型是
Step5-b `rare_candidates`，它不是 `parallel_safe`）要逐格现切字块：四庫 vol04 云端实测
每页约 13 秒切图 + 1.5 秒算候选，整册约 55 分钟，几乎全花在切图上。而切图是逐页独立的，
可以放到别的进程里先做掉。

## 并发安全怎么保证

`ImageCache` 的图本身按 key 各写各的文件，不冲突；冲突在每种类一份的页戳
`_stamps.json`（读-改-写，固定 `.tmp` 名）。所以：

1. 主进程**先串行**把要预渲的页里戳对不上的缓存清掉（同 `ImageCache.get` 的判法），
   这之后 worker 里 `get` 不会再触发 `_drop_stale_page`；
2. worker 里把 `set_page_stamp` 换成空操作——只写图、不写戳；
3. 全部渲完，主进程**串行**给这些页、各种类补戳，戳值与 worker 自己写会写的一样
   （`RunContext.cache_stamp` = 产出它那一步这一页产物的 sha，预渲期间产物不变）。

不改任何 Step：切图走的是 `RunContext.materialize` → 产出步的 `render`，与跑批同一条路。
"""
from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor

KIND = "char_patch"

_ctx = None


def _page_keys(ctx, page: int) -> list[str]:
    """这一页要切的字块 key（与 `rare_candidates.run_page` 收集的口径一致：char 格、有 patch_key）。"""
    try:
        chars = ctx.product("char_index", page)
    except FileNotFoundError:
        return []
    return [r.patch_key for cc in chars.columns if cc.ok for r in cc.chars
            if r.cell_type == "char" and r.patch_key]


def _init(book_id: str, pipeline_id: str) -> None:
    global _ctx
    from ..core.book import load_book
    from ..core.pipeline import load_pipeline
    from ..core.step import RunContext
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    cache = ImageCache()
    cache.set_page_stamp = lambda *a, **k: None          # 戳由主进程串行补（见模块头 2.）
    _ctx = RunContext(load_book(book_id), ProductStore(), cache, log=lambda s: None,
                      pipeline=load_pipeline(pipeline_id))


def _warm_page(page: int) -> tuple[int, int, str | None]:
    n = 0
    try:
        for k in _page_keys(_ctx, page):
            _ctx.materialize(KIND, k)
            n += 1
        return page, n, None
    except Exception as e:  # noqa: BLE001 —— 一页失败不拖垮整批；该页留给跑批时现切
        return page, n, f"{type(e).__name__}: {e}"


def _kinds_dirs(ctx):
    base = ctx.cache.root / ctx.book.id
    return [d.name for d in base.iterdir() if d.is_dir()] if base.exists() else []


def _stamp_pass(ctx, pages: list[int], drop: bool) -> None:
    """`drop=True`：清掉戳对不上的页（预渲前）；`False`：给有图的页补戳（预渲后）。"""
    from ..core.spec import page_key
    for kind in _kinds_dirs(ctx):
        try:
            ctx.producer(kind)
        except Exception:  # noqa: BLE001 —— 不是哪一步产出的缓存目录（没有戳可言）
            continue
        d = ctx.cache.root / ctx.book.id / kind
        for pg in pages:
            pk = page_key(pg)
            cur = ctx.cache_stamp(kind, pk)
            if not cur:
                continue
            if drop:
                rec = ctx.cache.page_stamp(ctx.book.id, kind, pk)
                if rec is not None and rec != cur:
                    ctx.cache._drop_stale_page(ctx.book.id, kind, pk)
            elif any(d.glob(f"{pk}*")):
                ctx.cache.set_page_stamp(ctx.book.id, kind, pk, cur)


def warm(ctx, pipeline_id: str, pages: list[int], jobs: int, log=print) -> dict:
    """→ `{pages, patches, failed: {页: 错误}, seconds}`。`ctx` 是主进程的 `RunContext`。"""
    t0 = time.time()
    _stamp_pass(ctx, pages, drop=True)
    failed: dict[int, str] = {}
    n_total = 0
    with ProcessPoolExecutor(max_workers=max(1, jobs), initializer=_init,
                             initargs=(ctx.book.id, pipeline_id)) as ex:
        for i, (pg, n, err) in enumerate(ex.map(_warm_page, pages, chunksize=1), 1):
            n_total += n
            if err:
                failed[pg] = err
            if i % 10 == 0 or i == len(pages):
                log(f"guji cache warm：{i}/{len(pages)} 页，{n_total} 个字块，{time.time() - t0:.0f}s")
    _stamp_pass(ctx, pages, drop=False)
    return {"pages": len(pages), "patches": n_total, "failed": failed,
            "seconds": round(time.time() - t0, 1)}
