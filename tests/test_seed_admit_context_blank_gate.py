# -*- coding: utf-8 -*-
"""Step7 context 通道对近空白字块弃权（2026-09-27 D 铁证复核：`vol03:9:9:21` 字块
几乎是空白，`context` 通道仍把它放行成「今」——上下文判定只看文意，没看这一格
到底有没有墨）。"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_chars, page_decision, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


def _ctx(tmp_path, monkeypatch, *, params: SeedAdmitParams | None = None):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    kwargs = {"seed_admit": params} if params is not None else {}
    return RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                      params=kwargs, log=lambda s: None)


def _run(ctx, *, match_recs, decision_recs, char_recs=None):
    write_product(ctx, "glyph_match", PAGE,
                  glyph_match=page_match(PAGE, BOOK, recs=match_recs, col=COL))
    write_product(ctx, "context_decide", PAGE,
                  context_decision=page_decision(PAGE, BOOK, recs=decision_recs, col=COL))
    if char_recs is not None:
        write_product(ctx, "cell_shrink", PAGE,
                      char_index=page_chars(PAGE, BOOK, recs=char_recs, col=COL))
    return STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]


def _all(sa):
    return [r for cc in sa.columns for r in cc.chars]


_BLANK_CASE = dict(
    match_recs=[dict(slot=1, verdict="unsure", cov=0.5, wmax=0.0, candidates=[])],
    decision_recs=[dict(slot=1, char="今", margin=0.9, source="context")],
    char_recs=[dict(slot=1, ink_ratio=0.005)],
)


def test_blank_cell_is_not_admitted_via_context(tmp_path, monkeypatch):
    """`vol03:9:9:21` 型：字形不定（没过任何字形通道），context 定了字，但字块
    几乎是空白（ink_ratio 0.005 < 闸 0.02）——不该自动放行，落人审。"""
    sa = _run(_ctx(tmp_path, monkeypatch), **_BLANK_CASE)
    r = _all(sa)[0]
    assert not r.admit, f"几乎空白的格不该被 context 通道放行：{r.channel}"
    assert "context_blank_cell" in r.doubts


def test_normal_ink_char_still_admitted_via_context(tmp_path, monkeypatch):
    """两侧都验：同一个 case 只把 ink_ratio 换成正常值（闸值之上），该照旧放行
    ——不然把判据整个删掉，上面那条测试也照样绿。"""
    case = {**_BLANK_CASE, "char_recs": [dict(slot=1, ink_ratio=0.3)]}
    sa = _run(_ctx(tmp_path, monkeypatch), **case)
    r = _all(sa)[0]
    assert r.admit and r.channel == "context", f"正常墨量的格不该被拦：{r.doubts}"


def test_gate_can_be_switched_off(tmp_path, monkeypatch):
    """开关关了退回改动前的行为——「只加不改」的验证判据。"""
    ctx = _ctx(tmp_path, monkeypatch, params=SeedAdmitParams(context_blank_gate=False))
    sa = _run(ctx, **_BLANK_CASE)
    r = _all(sa)[0]
    assert r.admit and r.channel == "context", (
        f"关掉闸该退回原行为（放行）：{r.channel}/{r.doubts}")


def test_missing_char_index_does_not_block(tmp_path, monkeypatch):
    """没有 `char_index` 产物（老测试/老产物）时不该挡——不知道墨量就不拦，这是
    「拿不准就保持基线」的落法，同 `_align` 缺失时的处理一致。"""
    case = {k: v for k, v in _BLANK_CASE.items() if k != "char_recs"}
    sa = _run(_ctx(tmp_path, monkeypatch), **case)
    r = _all(sa)[0]
    assert r.admit and r.channel == "context"


def test_default_min_ink_leaves_room_for_real_low_ink_chars():
    """闸值本身量出来的口径：见 `SeedAdmitParams.context_min_ink` 文档字符串——
    vol03 全书 `channel=context` 逐格看图定的界，压在「确认空白」（0.0493）与
    「确认真字，一横的「一」」（0.0677）之间。"""
    assert 0.0493 < SeedAdmitParams().context_min_ink < 0.0677
