# -*- coding: utf-8 -*-
"""`RunContext._raw` 必须有界（R-rare-mem 急件，2026-09-27）。

此前是无界 `dict`：注释写着「同一页只读一次」，实现却是「每一页都留一份，
一本书跑到底」——引擎按 step-major 顺序跑（一个 Step 对全书每页各调一次
`raw_page`），同一个 `RunContext` 贯穿整本书的所有步骤。四庫 vol03 服务器上
`rare_candidates` 单进程涨破 3G 被杀，`_raw` 是主要分量之一：轮到
`rare_candidates` 跑时，`_raw` 早被它前面几个读原图的 Step（border_detect /
column_warp / line_detect）攒满了整本书（188 页 × ~7MB ≈ 1.4GB，云端实测）。

这条测试不依赖真书原图（用 monkeypatch 造假页），只钉「见过的页数超过
`_RAW_MAX` 之后，字典大小不再增长、且总是能拿到正确内容」这两件事。
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.step import RunContext


class _FakePath:
    """`raw_page` 只用得到 `.exists()` 和 `str(path)` 这两样，够了。"""

    def __init__(self, page: int):
        self.page = page

    def exists(self) -> bool:
        return True

    def __str__(self) -> str:
        return f"/fake/{self.page}.png"


@pytest.fixture()
def ctx(monkeypatch):
    book = SimpleNamespace(id="testbook", font={}, binarized_input=False)
    c = RunContext(book, store=None, cache=None, log=lambda s: None)

    # `raw_page` 走 `self._page_path(page)` 再 `imread`；跳过真实文件，
    # 每页给一张内容各不相同、能验真伪的假图（内容按页号编码）。
    monkeypatch.setattr(RunContext, "_page_path", lambda self, page: _FakePath(page))

    from open_guji_cv.core import step as step_mod

    def fake_imread(path, flag):
        page = int(str(path).rsplit("/", 1)[-1].split(".")[0])
        return np.full((4, 4), page, dtype=np.uint8)

    monkeypatch.setattr(step_mod, "imread", fake_imread)
    return c


def test_raw_dict_stays_bounded_across_many_pages(ctx):
    for p in range(1, 200):
        ctx.raw_page(p)
        assert len(ctx._raw) <= ctx._RAW_MAX, (
            f"处理到第 {p} 页，_raw 长到 {len(ctx._raw)} 条，超过上限 {ctx._RAW_MAX}")
    assert len(ctx._raw) == ctx._RAW_MAX


def test_raw_page_content_correct_after_eviction(ctx):
    """页 1 被挤出去以后重新访问，必须重新读、内容仍然对——不是拿错页的缓存。"""
    for p in range(1, 10):
        ctx.raw_page(p)
    assert 1 not in ctx._raw, "页 1 应该已经被挤出去了（上限 2）"
    img1_again = ctx.raw_page(1)
    assert int(img1_again[0, 0]) == 1, "重新取回的页 1 内容不对"


def test_raw_page_same_page_repeated_call_hits_cache(ctx, monkeypatch):
    """同一页连续访问不重复读盘（这是 `_raw` 存在的本意，别改没了）。"""
    calls = []
    from open_guji_cv.core import step as step_mod
    orig = step_mod.imread

    def counting_imread(path, flag):
        calls.append(path)
        return orig(path, flag)

    monkeypatch.setattr(step_mod, "imread", counting_imread)
    ctx.raw_page(5)
    ctx.raw_page(5)
    ctx.raw_page(5)
    assert len(calls) == 1, "同一页应该只读盘一次"
