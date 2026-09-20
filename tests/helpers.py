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


def make_ctx(tmp_path, book=None, *, raw: dict[int, np.ndarray] | None = None,
             monkeypatch=None):
    """造一个 `RunContext`：产物库与图像缓存都落在 tmp 里，原图可直接注入。

    `raw={页号: 灰度图}` 绕开磁盘原图——几何链的测试要的是「这张图长这样时
    算法怎么走」，跟图从哪儿读来的无关。

    ⚠️ 传 `monkeypatch` 时顺带把 `GUJI_PRODUCTS_DIR` / `GUJI_CACHE_DIR` 也指到
    同一处。**有些生产代码不走 ctx 而是自己 `ImageCache()`**（`eval/rulers.py`
    的 `_col_profile` 就是，闸3 借它取列投影），那条路读的是默认根；不对齐的话
    测试里写进 ctx 缓存的列图它一张也看不到，R2/R2s 这些量会静默变成 0——
    看着通过，其实什么都没量。
    """
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore

    book = book or make_book()
    products, cache = tmp_path / "products", tmp_path / "cache"
    if monkeypatch is not None:
        monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
        monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    ctx = RunContext(book, ProductStore(products), ImageCache(cache), log=lambda s: None)
    for page, img in (raw or {}).items():
        ctx._raw[page] = img
    return ctx


# ── 合成页面 ─────────────────────────────────────────────────────────────
#
# 合成页与它的 `Borders` 必须由**同一组参数**生成，否则闸子量出来的偏差是
# fixture 自己对不上，不是被测代码的问题。所以只有 `synth_page` 一个入口，
# 图和产物一起返回。


def column_xs(w: int = 900, n_cols: int = 9, margin: int = 60) -> list[float]:
    """均匀版式的 n_cols+1 条界行 x。"""
    return [float(x) for x in np.linspace(margin, w - margin, n_cols + 1)]


def synth_page(*, w: int = 900, h: int = 1400, n_cols: int = 9, period: int = 60,
               margin: int = 60, frame: int = 40, xs: list[float] | None = None,
               top_gap: int = 0, col_top_gap: dict[int, int] | None = None,
               col_n_chars: dict[int, int] | None = None, n_chars: int | None = None,
               gap: int = 14) -> tuple[np.ndarray, "object"]:
    """造一页「版框 + 界行 + 栏内字块」，同时返回与它**完全一致**的 `Borders`。

    - `xs`：自定界行位置。不给就是均匀版式；给一组不等距的，就能造出
      「某一列特别宽」这种要被 L1c 标记的形态。
    - `top_gap` / `col_top_gap`：字块离上版框多远。0 = 顶格列（闸2 该给
      `top_slack`），给一个正数 = 普通正文列（不该给）。
    - `n_chars` / `col_n_chars`：这一列排几个字——墨跨度装得下几个字正是
      `n_raised_hint` 的判据。
    - `gap`：字块之间留多少行白。0 = 上下字**物理粘连**，整列找不到墨谷——
      闸3 的 R2s「真粘连」就是这个形态。

    返回 `(灰度图, Borders)`。栏内没有字（`n_chars=0`）就是空栏页。
    """
    from open_guji_cv.products.kinds.borders import Borders, HLineRec, VLineRec

    xs = xs or column_xs(w, n_cols, margin)
    g = np.full((h, w), 255, np.uint8)
    x_lo, x_hi = int(min(xs)), int(max(xs))
    g[frame:frame + 6, x_lo:x_hi] = 20                       # 上版框
    g[h - frame - 6:h - frame, x_lo:x_hi] = 20               # 下版框
    for x in xs:                                             # 界行
        g[frame:h - frame, int(x) - 2:int(x) + 2] = 20

    inner_h = (h - frame) - (frame + 6)
    default_n = n_chars if n_chars is not None else max(1, inner_h // period - 1)
    for i in range(len(xs) - 1):
        col = i + 1
        top = (col_top_gap or {}).get(col, top_gap)
        cnt = (col_n_chars or {}).get(col, default_n)
        x0, x1 = int(xs[i]) + 6, int(xs[i + 1]) - 6
        if x1 - x0 < 4:
            continue
        y = frame + 6 + top
        for _ in range(cnt):
            if y + period - 14 >= h - frame - 6:
                break
            g[y + gap // 2:y + period - (gap - gap // 2), x0:x1] = 20
            y += period

    borders = Borders(
        width=w, height=h, expected_cols=len(xs) - 1,
        top=HLineRec(y_at_right=float(frame), slope=0.0, kind="straight"),
        bottom=HLineRec(y_at_right=float(h - frame), slope=0.0, kind="straight"),
        verticals=[VLineRec(x_at_top=float(x), slope=0.0) for x in xs])
    return g, borders


def ruled_page(w: int = 900, h: int = 1400, n_cols: int = 9,
               margin: int = 60, frame: int = 40) -> np.ndarray:
    """空栏页：版框与界行都印着，栏内一个字都没有。"""
    return synth_page(w=w, h=h, n_cols=n_cols, margin=margin, frame=frame,
                      n_chars=0)[0]


def body_page(w: int = 900, h: int = 1400, n_cols: int = 9, period: int = 60,
              margin: int = 60, frame: int = 40) -> np.ndarray:
    """正文页：栏格里按固定行距填满字块，行距即真周期。"""
    return synth_page(w=w, h=h, n_cols=n_cols, period=period, margin=margin,
                      frame=frame)[0]


def blank_page(w: int = 900, h: int = 1400) -> np.ndarray:
    """全白页——什么都没印。"""
    return np.full((h, w), 255, np.uint8)


# ── 合成产物 ─────────────────────────────────────────────────────────────

def make_borders(w: int = 900, h: int = 1400, n_cols: int = 9,
                 margin: int = 60, frame: int = 40, xs: list[float] | None = None):
    """一页规规矩矩的版框产物：上下横框 + n_cols+1 条竖线。

    只要产物、不要配套图像时用它；要图文一致请用 `synth_page`。
    """
    return synth_page(w=w, h=h, n_cols=n_cols, margin=margin, frame=frame,
                      xs=xs, n_chars=0)[1]


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


# ── 跑一段真链路 ─────────────────────────────────────────────────────────

def run_steps(ctx, page: int, step_ids: list[str]) -> dict:
    """依次跑几步并把产物写回库，返回 {产物名: 产物}。

    交接闸要读上游的真产物（列图在缓存里、窗口在库里），硬造一份容易和算法
    的实际输出对不上；跑真链路造出来的才是闸子真会看到的东西。
    """
    from open_guji_cv.core.step import STEPS

    out: dict = {}
    for sid in step_ids:
        res = STEPS[sid].run_page(ctx, page)
        ctx.store.write(ctx.book.id, sid, f"p{page:04d}", res)
        out.update(res)
    return out


def run_border_to_column_gate(tmp_path, gray, borders, *, page: int = 1,
                              book=None, gate1=None, monkeypatch=None):
    """摆好 Step1 产物 → 跑 Step2（column_warp）与闸2，返回 (ctx, 产物字典)。"""
    book = book or make_book(expected_cols=borders.expected_cols)
    ctx = make_ctx(tmp_path, book, raw={page: gray}, monkeypatch=monkeypatch)
    ctx.store.write(book.id, "border_detect", f"p{page:04d}", {"borders": borders})
    ctx.store.write(book.id, "border_detect_gate", f"p{page:04d}",
                    {"border_detect_gate_manifest": gate1 or make_gate1(
                        page, n_cols=borders.expected_cols,
                        expected_cols=book.expected_cols)})
    return ctx, run_steps(ctx, page, ["column_warp", "column_gate"])


#: 刻本链 Step2→Step4 的步骤序（含挂在出口的两道闸）。跑合成页时按需截断。
KEBEN_STEPS = ["column_warp", "column_gate", "row_segment", "row_segment_gate",
               "cell_shrink"]


def run_keben_chain(tmp_path, monkeypatch=None, *, page: int = 1, book=None,
                    through: str = "cell_shrink", gray=None, borders=None,
                    gate1=None, **page_kw):
    """合成一页 → 摆好 Step1 产物 → 跑刻本链到指定步骤。

    返回 `(ctx, 产物字典)`。`**page_kw` 原样转给 `synth_page`，要什么版式就
    给什么（列数、周期、每列字数、顶格…）。

    传 `monkeypatch` 会把 `GUJI_PRODUCTS_DIR` / `GUJI_CACHE_DIR` 一并指到 tmp
    ——有几处生产代码不走 ctx 而是自己 new 默认根的 Store/Cache（见 `make_ctx`）。
    """
    if gray is None or borders is None:
        gray, borders = synth_page(**page_kw)
    book = book or make_book(expected_cols=borders.expected_cols)
    ctx = make_ctx(tmp_path, book, raw={page: gray}, monkeypatch=monkeypatch)
    ctx.store.write(book.id, "border_detect", f"p{page:04d}", {"borders": borders})
    ctx.store.write(book.id, "border_detect_gate", f"p{page:04d}",
                    {"border_detect_gate_manifest": gate1 or make_gate1(
                        page, n_cols=borders.expected_cols,
                        expected_cols=book.expected_cols)})
    steps = KEBEN_STEPS[:KEBEN_STEPS.index(through) + 1]
    return ctx, run_steps(ctx, page, steps)


#: 从原图起跑的完整刻本链（Step1 起，含挂在出口的三道闸）。
KEBEN_STEPS_FROM_RAW = ["border_detect", "border_detect_gate"] + KEBEN_STEPS


def run_keben_from_raw(tmp_path, monkeypatch=None, *, book, gray, page: int = 1,
                       through: str = "cell_shrink"):
    """拿一张**真页**从 Step1 跑到指定步骤，返回 `(ctx, 产物字典)`。

    给的图应当是 `tests/fixtures/` 里那几张冻结样页（`fixture_page` fixture），
    不要指向 `data/` 或工作区——那些会变，变了这类端到端用例就跟着红，
    而红的原因跟被测代码无关。
    """
    ctx = make_ctx(tmp_path, book, raw={page: gray}, monkeypatch=monkeypatch)
    steps = KEBEN_STEPS_FROM_RAW[:KEBEN_STEPS_FROM_RAW.index(through) + 1]
    return ctx, run_steps(ctx, page, steps)


# ── Step5 系产物（库匹配 / OCR / 上下文裁决 / 整理本对齐）──────────────
#
# 这几步之后的链路（seed_admit、context_decide 的下游）只读产物、不碰图像，
# 所以直接造产物就能跑真步骤——比「跑一遍完整管线再看碰上什么」既快又可控：
# 想测哪一条通道，就把那条通道的证据摆成什么样。

def page_match(page: int = 1, book: str = "tbook", *, recs: list[dict],
               col: int = 1, db_fingerprint: str = "testdb"):
    """`glyph_match` 产物。`recs` 每项给 slot / verdict / char / cov 等。"""
    from open_guji_cv.products.kinds.recog import ColumnMatch, MatchRec, PageMatch

    chars = []
    for r in dict_list(recs):
        slot = r.pop("slot")
        chars.append(MatchRec(id=f"{book}:{page}:{col}:{slot}", slot=slot, **r))
    return PageMatch(page=page, db_fingerprint=db_fingerprint,
                     columns=[ColumnMatch(col=col, ok=True, chars=chars)])


def page_decision(page: int = 1, book: str = "tbook", *, recs: list[dict],
                  col: int = 1, strategy: str = "test"):
    """`context_decision` 产物。"""
    from open_guji_cv.products.kinds.recog import ColumnDecision, DecisionRec, PageDecision

    chars = []
    for r in dict_list(recs):
        slot = r.pop("slot")
        chars.append(DecisionRec(id=f"{book}:{page}:{col}:{slot}", slot=slot, **r))
    return PageDecision(page=page, strategy=strategy,
                        columns=[ColumnDecision(col=col, ok=True, chars=chars)])


def dict_list(recs: list[dict]) -> list[dict]:
    """浅拷贝一遍——构造器会 `pop`，不该改调用方手里的字面量。"""
    return [dict(r) for r in recs]


def write_product(ctx, step_id: str, page: int, **kinds):
    """把产物摆进库（`{种类名: 产物}`）。种类名要与该步 `produces` 里的一致。"""
    ctx.store.write(ctx.book.id, step_id, f"p{page:04d}", kinds)
