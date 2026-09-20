# -*- coding: utf-8 -*-
"""测试自备数据的构造器。**测试要什么就在这儿造什么，不要去扫生产产物。**

为什么不用「读一份真产物」那套：产物是跑批的结果，跟着算法和数据一起变。
拿它当测试输入，等于把「代码对不对」和「这次跑批出了什么」绑在一起——
前者该被测，后者该被评测（`guji eval run`）看着。两件事混在一个断言里，
结果就是数据一变测试就红，而红了也说不清是谁的问题。

这里的东西都是**纯内存构造**，不落盘、不读 yaml、不碰工作区。要真图像就用
`tests/fixtures/` 里冻结的那三张页（见 `tests/conftest.py` 的 `fixture_page`）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

FIXTURE_RAW = Path(__file__).resolve().parent / "fixtures" / "workspace" / "raw"


def make_book(book_id: str = "tbook", **kw):
    """内存里造一册 `BookSpec`——不落盘、不读 yaml。

    版式常量（`expected_cols` / `chars_per_line` / `period_prior` …）按测试
    自己要测的形态给，别去 `load_book` 某本真书：那会让测试跟着那本书的
    册配置走，配置一改测试就红，而册配置改动跟被测代码通常毫无关系。
    """
    from open_guji_cv.core.book import BookSpec

    kw.setdefault("title", f"测试册 {book_id}")
    kw.setdefault("raw_dir", FIXTURE_RAW / "keben")
    kw.setdefault("expected_cols", 9)
    kw.setdefault("chars_per_line", 21)
    return BookSpec(id=book_id, **kw)


def make_ctx(tmp_path, book=None, *, raw: dict[int, np.ndarray] | None = None):
    """造一个 `RunContext`：产物库与图像缓存都落在 tmp 里，原图可直接注入。

    `raw={页号: 灰度图}` 绕开磁盘原图——几何链的测试要的是「这张图长这样时
    算法怎么走」，跟图从哪儿读来的无关。
    """
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore

    book = book or make_book()
    ctx = RunContext(book, ProductStore(tmp_path / "products"),
                     ImageCache(tmp_path / "cache"), log=lambda s: None)
    for page, img in (raw or {}).items():
        ctx._raw[page] = img
    return ctx


# ── 合成页面 ─────────────────────────────────────────────────────────────

def ruled_page(w: int = 900, h: int = 1400, n_cols: int = 9,
               margin: int = 60, frame: int = 40) -> np.ndarray:
    """空栏页：上下版框 + n_cols+1 条界行都印着，栏内一个字都没有。"""
    g = np.full((h, w), 255, np.uint8)
    g[frame:frame + 6, margin:w - margin] = 20
    g[h - frame - 6:h - frame, margin:w - margin] = 20
    for x in np.linspace(margin, w - margin, n_cols + 1):
        g[frame:h - frame, int(x) - 2:int(x) + 2] = 20
    return g


def body_page(w: int = 900, h: int = 1400, n_cols: int = 9, period: int = 60,
              margin: int = 60, frame: int = 40) -> np.ndarray:
    """正文页：`ruled_page` 的栏格里按固定行距填满字块，行距即真周期。"""
    g = ruled_page(w, h, n_cols, margin, frame)
    xs = np.linspace(margin, w - margin, n_cols + 1)
    for i in range(n_cols):
        x0, x1 = int(xs[i]) + 6, int(xs[i + 1]) - 6
        for y in range(frame + 20, h - frame - 50, period):
            g[y:y + period - 14, x0:x1] = 20
    return g


def blank_page(w: int = 900, h: int = 1400) -> np.ndarray:
    """全白页——什么都没印。"""
    return np.full((h, w), 255, np.uint8)


# ── 合成产物 ─────────────────────────────────────────────────────────────

def make_borders(w: int = 900, h: int = 1400, n_cols: int = 9,
                 margin: int = 60, frame: int = 40):
    """一页规规矩矩的版框产物：上下横框 + 均匀分布的 n_cols+1 条竖线。"""
    from open_guji_cv.products.kinds.borders import Borders, HLineRec, VLineRec

    xs = np.linspace(margin, w - margin, n_cols + 1)
    return Borders(
        width=w, height=h, expected_cols=n_cols,
        top=HLineRec(y_at_right=float(frame), slope=0.0, kind="straight"),
        bottom=HLineRec(y_at_right=float(h - frame), slope=0.0, kind="straight"),
        verticals=[VLineRec(x_at_top=float(x), slope=0.0) for x in xs])


def make_gate1(page: int = 1, *, admitted: bool = True, n_cols: int = 9,
               expected_cols: int = 9, page_type: str = "body",
               policy: str = "standard", reject: list[str] | None = None):
    """闸1（border_detect_gate）的产物。下游闸2/闸3 读它拿页型判定。"""
    from open_guji_cv.products.kinds.border_detect_gate import BorderDetectGateManifest

    return BorderDetectGateManifest(
        page=page, admitted=admitted, reject=reject or [], n_cols=n_cols,
        expected_cols=expected_cols, page_type=page_type, page_type_policy=policy)


def skip_gate1(page: int = 1, *, page_type: str = "cover", n_cols: int = 0,
               expected_cols: int = 9):
    """闸1 判 skip（封面/书签/牌记这类无正文栏格的页）的产物。"""
    return make_gate1(
        page, admitted=False, n_cols=n_cols, expected_cols=expected_cols,
        page_type=page_type, policy="skip",
        reject=[f"page_type_skip：页型判定为「{page_type}」，无正文栏格，不套列窗口"])
