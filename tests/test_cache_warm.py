"""`guji cache warm` 的页戳两趟（overview#429）：预渲前清戳不对的页、预渲后串行补戳。

worker 里不写戳（多进程读-改-写同一份 `_stamps.json` 会丢戳），所以戳全靠主进程这两趟。"""
from __future__ import annotations

import numpy as np

import open_guji_cv.steps  # noqa: F401  注册 char_patch 的产出步
from helpers import make_ctx
from open_guji_cv.ops.cache_warm import _stamp_pass

IMG = np.full((8, 8), 255, np.uint8)


def test_drop_mismatched_then_stamp_after(tmp_path):
    ctx = make_ctx(tmp_path)
    c, b = ctx.cache, ctx.book.id
    c.put(b, "char_patch", "p0001c01s1", IMG, stamp="OLD")     # 对着旧产物切的
    c.put(b, "char_patch", "p0002c01s1", IMG, stamp="NOW")     # 对得上
    ctx.cache_stamp = lambda kind, key: "NOW"

    _stamp_pass(ctx, [1, 2], drop=True)
    assert c.get(b, "char_patch", "p0001c01s1") is None        # 旧页清掉
    assert c.get(b, "char_patch", "p0002c01s1") is not None
    assert c.page_stamp(b, "char_patch", "p0001") is None

    c.put(b, "char_patch", "p0001c01s1", IMG)                  # worker：只写图、不写戳
    _stamp_pass(ctx, [1, 2, 3], drop=False)
    assert c.page_stamp(b, "char_patch", "p0001") == "NOW"
    assert c.page_stamp(b, "char_patch", "p0003") is None      # 没图的页不补戳
