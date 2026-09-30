# -*- coding: utf-8 -*-
"""`ref_lib` 通道变体放行加闸（2026-09-27）。

任务书依据：R 形近溯源 done 单实测 `bxgb:52:11:15`——图上刻「冶」，产物写成了
「治」。库候选（top1）「治」cov 0.9443、Step6 margin 只有 0.024（远低于放行阈），
本该弃权，却因为 `variants.auto.tsv` 里一条 twedu 单向登记的 `冶→治`
（`vmap.semantic("冶") == vmap.semantic("治")`）被 `relax_ref_agree` 的 `ref_lib`
分支直接放行——那条逻辑此前完全不看字面是否相同、也不看 Step6 margin。

三种要盯住的情形（任务书验收要求）：
1. 变体放行（字面不同、边不可信、margin 不过线）被拦——记 doubt、不放行；
2. 可信边（双向关系 / 人裁 / 书级 codepoints）照放；
3. 字面相同（库候选 == 整理本字）不受影响。

2026-09-28（overview#201）：冶/治 登记进 `never_group.json`，语义层不再同义，走不到
`ref_lib` 变体分支了。闸本身的三条行为测试改用同为单向直接边的 `𠮓→變`（D #178 单向桶里的
新旧字形）钉；`_trusted_variant_edge` 的纯函数测试仍用 冶/治（它不看语义表）。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.recog import AlignRec, PageAlignRef
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _trusted_variant_edge
from open_guji_cv.variant_ledger import BookLedger

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 15


def _write_align(ctx, *, align_char: str, align_op: str = "replace"):
    # 真实例 `bxgb:52:11:15` 的 `align_op` 是 "replace"（R 形近溯源 done 单 + 本地
    # 复核，见任务书里的 done 单）——"equal" 层的疑问集更宽松，会在
    # `admission_decision` 的 `ref_overridable` 分支提前放行（`match_ref`），
    # 测不到 `relax_ref_agree` 这一段；"replace" 才是这个真实场景会走的路。
    write_product(ctx, "align_ref", PAGE, align_ref=PageAlignRef(
        page=PAGE, anchored=True,
        chars=[AlignRec(id=f"{BOOK}:{PAGE}:{COL}:{SLOT}", col=COL, slot=SLOT,
                        align_char=align_char, align_op=align_op)]))


def _run(tmp_path, monkeypatch, *, lib_char: str, align_char: str,
         book=None, params: dict | None = None):
    """摆一格「库候选 lib_char，整理本给 align_char」的证据 → 跑 C1。

    cov/wmax 照录 `bxgb:52:11:15` 的真实数字（R 形近溯源 done 单），这样测出来的
    是真实场景会不会命中——不是拍一个凑巧过 admission_decision 早期通道的数字。
    """
    ctx = make_ctx(tmp_path, book or make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, verdict="unsure", cov=0.9443, wmax=25.81,
                 candidates=_candidates(lib_char)),
        ]))
    _write_align(ctx, align_char=align_char)
    return _run_with_params(ctx, SeedAdmitParams(**(params or {})))


def _candidates(top: str) -> list[tuple[str, float]]:
    """真实例候选池有 5 个、top1/top2 只差 0.0053（`泊` 0.939）——单候选列表会让
    `match_margin`（top1 断档领先即放行，见 `seeding.py` 注释）提前放行、测不到
    `relax_ref_agree`。这里补一个贴近的第二候选，复现真实的「没有断档」。"""
    filler = "泊" if top != "泊" else "泗"
    return [(top, 0.9443), (filler, 0.939)]


def _run_with_params(ctx, params: SeedAdmitParams):
    """`ctx.params_for(step)` 先查 `ctx.params[step.spec.id]`（`core/step.py`），
    直接塞进去就是这次跑用的参数——不用伪造 pipeline yaml 那一整套解析链。"""
    ctx.params["seed_admit"] = params
    return STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]


def _rec(sa):
    (col,) = sa.columns
    (r,) = col.chars
    return r


# ── 1. 变体放行被拦 ──────────────────────────────────────────────

def test_untrusted_variant_is_blocked(tmp_path, monkeypatch):
    """`𠮓→變`（原例 冶→治，见模块头）：graph 来源、单向、无人裁、无 codepoints、margin 0.024——加闸后不放行。"""
    sa = _run(tmp_path, monkeypatch, lib_char="變", align_char="𠮓")
    r = _rec(sa)
    assert r.admit is False, f"未加闸的变体放行没被拦住：channel={r.channel}"
    assert "ref_lib_variant" in r.doubts, r.doubts
    assert r.channel != "ref_lib"


def test_guard_default_on():
    assert SeedAdmitParams().ref_lib_variant_guard is True


def test_guard_disabled_restores_old_behavior(tmp_path, monkeypatch):
    """关掉开关要能回到加闸前的行为（回归安全阀）。"""
    sa = _run(tmp_path, monkeypatch, lib_char="變", align_char="𠮓",
             params={"ref_lib_variant_guard": False})
    r = _rec(sa)
    assert r.admit is True and r.channel == "ref_lib" and r.char == "變"


# ── 2. 可信边照放 ────────────────────────────────────────────────

def test_bidirectional_variant_is_admitted(tmp_path, monkeypatch):
    """关系层两个方向都登记（双向）→ 可信边，即便 margin 不过线也放行。

    用真实字对 `彝`/`彞`（vol03 快照实测的另一条 `ref_lib` 变体放行，见 done 单）：
    `vmap.semantic('彝')==vmap.semantic('彞')=='彝'`，`regulars_of` 两个方向都有
    登记（`彝→彞` unihan 简繁、`彞→彝` twedu），与单向的 `冶→治` 形成对照——不用
    伪造关系图，拿生产配置里现成的可信边验证「双向就放行」。
    """
    sa = _run(tmp_path, monkeypatch, lib_char="彝", align_char="彞")
    r = _rec(sa)
    assert r.admit is True and r.channel == "ref_lib" and r.char == "彝"
    assert "ref_lib_variant" not in r.doubts


def test_margin_over_threshold_is_admitted(tmp_path, monkeypatch):
    """边不可信，但 Step6 margin 过线（复用 context_margin）也放行。"""
    from open_guji_cv.products.kinds.recog import ColumnDecision, DecisionRec, PageDecision
    monkeypatch.setattr("open_guji_cv.variants.regulars_of", lambda ch, sources=None: [])
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, verdict="unsure", cov=0.9443, wmax=25.81,
                 candidates=_candidates("變")),
        ]))
    _write_align(ctx, align_char="𠮓")
    # margin 0.80 ≥ 生产 context_margin 0.70，但 source 不是 "context"（不走上面
    # 那条 context 通道)，只用来给 ref_lib 变体闸的 margin 分支背书。
    write_product(ctx, "context_decide", PAGE, context_decision=PageDecision(
        page=PAGE, columns=[ColumnDecision(col=COL, chars=[
            DecisionRec(id=f"{BOOK}:{PAGE}:{COL}:{SLOT}", slot=SLOT,
                       char="丙", margin=0.80, source="prior"),
        ])]))
    sa = _run_with_params(ctx, SeedAdmitParams())
    r = _rec(sa)
    assert r.admit is True and r.channel == "ref_lib" and r.char == "變"


def test_human_ledger_pair_is_trusted(tmp_path, monkeypatch):
    """本书用字账人裁确认过这一对（`pair_confirmed`）→ 可信边。"""
    monkeypatch.setattr("open_guji_cv.variants.regulars_of", lambda ch, sources=None: [])
    ledger = BookLedger({"groups": {"治": {"members": ["冶", "治"],
                                          "pairs": {"冶→治": {"human": 1}}}}})
    assert _trusted_variant_edge("冶", "治", ledger, make_book(BOOK)) is True


def test_book_codepoints_pair_is_trusted():
    """本书 `codepoints` 配置把两个码位统一 → 可信边（书级实证）。"""
    ledger = BookLedger({"groups": {}})
    book = make_book(BOOK, codepoints={"冶": "治"})
    assert _trusted_variant_edge("冶", "治", ledger, book) is True


def test_one_way_edge_alone_is_not_trusted():
    """只有单向关系边、没有人裁、没有 codepoints → 不可信（这正是冶→治的实况）。"""
    ledger = BookLedger({"groups": {}})
    book = make_book(BOOK)
    assert _trusted_variant_edge("冶", "治", ledger, book) is False


def test_hand_curated_table_pair_is_trusted():
    """`config/dicts/variants.tsv`（人工表）登记过的对，即便关系层查不到双向也可信。

    真实例：`為→爲` 关系层双向、但 `逰→遊`/`无→無`/`迴→回` 等 10/17 条查不到双向
    （单向 `directed`），全部是人工确认——只认双向会把这些手工条目也拦掉，比不加闸
    还倒退。"""
    ledger = BookLedger({"groups": {}})
    book = make_book(BOOK)
    for top, ref in [("逰", "遊"), ("无", "無"), ("迴", "回")]:
        assert _trusted_variant_edge(top, ref, ledger, book) is True, f"{top}->{ref}"


# ── 3. 字面相同不受影响 ──────────────────────────────────────────

def test_literal_same_is_unaffected_by_guard(tmp_path, monkeypatch):
    """库候选 == 整理本字（字面相同）：不经过变体闸，照放。"""
    monkeypatch.setattr("open_guji_cv.variants.regulars_of", lambda ch, sources=None: [])
    sa = _run(tmp_path, monkeypatch, lib_char="治", align_char="治")
    r = _rec(sa)
    assert r.admit is True and r.channel == "ref_lib" and r.char == "治"
    assert "ref_lib_variant" not in r.doubts
