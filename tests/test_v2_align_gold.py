# -*- coding: utf-8 -*-
"""v2 × 整理本自动金标 + C1 的 near_form 防线。

2026-09-20 重写。原先四条都要「工作区里跑过的 vol01 dev_set 产物 ＋ 8.2 MB
真语料」，两样缺一就整条 skip——模块头当年为此写了三十行「怎么摆环境才跑得
起来」（只能设 `GUJI_WORKSPACE`、不能额外设 `GUJI_PRODUCTS_DIR`，否则
products 与 cache 分家…）。那段说明本身就是这套测试设计不对的证据：一条
单元测试不该要求读者先把三个环境变量摆对。

拆成两半：

- **代码行为**（字形/文意分开记、形近家族不许只凭形状进库）留在这里，输入
  由测试自己给——要测「整理本把 㫖 正字化成 旨」，就写一份这么写的小语料，
  比在真书里等着碰上一个可靠得多。
- **准确率**（dev_set 锚定率 ≥75%、自动进库对金标零错、转换率 <10%）迁出。
  那是对某一次跑批的质量测量，属评测：`guji eval run`，口径见
  `doc/glyph_db_first_design.md` §7.3 与 `eval/` 下的判据 A。
  把它留在测试里的代价，这轮看得很清楚：数据一变就红，红了还说不清是
  算法退步还是这次跑批的数据不同；而云端根本跑不了，等于没有。
"""

from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.gold.v2_align import align_book
from open_guji_cv.steps.align_ref import AlignRefParams

BOOK, PAGE, COL = "tbook", 1, 1


def _gold(tmp_path, monkeypatch, *, shapes: str, corpus_text: str):
    """摆好「刻本这一列定成了 shapes + 整理本这么写」→ 派生 GoldChar。

    `shapes` 是 v2 定的字形（走 `context_decision`），`corpus_text` 是整理本。
    两者故意可以不同——「字形与文意分开记」测的正是这个差。
    """
    corpus = tmp_path / "ref.txt"
    corpus.write_text(corpus_text, encoding="utf-8")
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    ctx.params["align_ref"] = AlignRefParams(corpus=str(corpus))

    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=i + 1, verdict="same", char=ch, cov=0.999, matched_id=f"g{i}")
            for i, ch in enumerate(shapes)]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=i + 1, char=ch, margin=1.0, source="db_same")
            for i, ch in enumerate(shapes)]))
    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    ctx.store.write(BOOK, "align_ref", f"p{PAGE:04d}", {"align_ref": ar})
    return ctx, align_book(BOOK, [PAGE], ctx.store, corpus_path=corpus)[0]


def test_page_anchors_when_the_reference_contains_the_column(tmp_path, monkeypatch,
                                                             ws):
    """整理本里有这一列的文字 → 锚得上、逐字出金标。"""
    text = "文華殿大學士臣紀昀等奉敕撰欽定四庫全書總目"
    _, g = _gold(tmp_path, monkeypatch, shapes=text[:12], corpus_text=text * 30)
    assert g.anchored, g.note
    assert g.n_chars == 12
    assert "".join(c.shape for c in g.chars) == text[:12]


def test_unanchorable_page_is_reported_not_silently_empty(tmp_path, monkeypatch, ws):
    """锚不上要如实报，不能给一页「空金标」——空金标会被下游当成「全对」。"""
    _, g = _gold(tmp_path, monkeypatch, shapes="文華殿大學士臣紀昀等奉敕",
                 corpus_text="甲乙丙丁" * 500)
    assert not g.anchored
    assert g.note, "锚不上却不说为什么"
    assert g.n_chars == 0


def test_shape_and_ref_are_recorded_separately(tmp_path, monkeypatch, ws):
    """字形与文意分开记（用户 2026-09-04 定：先读字形、录入按文意）。

    整理本是正字化文本，刻本上的 㫖/彚/卽/祗 会被它写成 旨/彙/即/祇。
    这个差别必须留痕，不能只存一个。

    合成：刻本这一列定成「諭㫖各註某家藏本……」，整理本把 㫖 正字化成 旨。
    （列要够长：8-gram 锚定对「定字太少」的页直接判锚不住。）
    """
    shapes = "諭㫖各註某家藏本臣等謹按卷一經部"
    reading = "諭旨各註某家藏本臣等謹按卷一經部"
    _, g = _gold(tmp_path, monkeypatch, shapes=shapes, corpus_text=reading * 40)
    assert g.anchored, g.note

    conv = [c for c in g.chars if c.conversion]
    assert conv, "一条转换都没有——shape/ref 恐怕填成同一个值了"
    assert [(c.shape, c.ref) for c in conv] == [("㫖", "旨")], \
        [(c.shape, c.ref) for c in conv]
    for c in conv:
        assert c.shape != c.ref
    assert g.n_conversion == len(conv)
    # 其余字位两者必须相同——转换是少数派，不是"到处都在转"
    same = [c for c in g.chars if not c.conversion]
    assert same and all(c.shape == c.ref for c in same)


def test_near_form_families_never_auto_admit_on_shape_alone(tmp_path, monkeypatch):
    """形近家族不许只凭形状证据自动进库。

    这是 C1 包壳曾经的漏洞：judge_doubts 在 v1 里靠整理本产出 near_form，
    没有整理本时若不自己判，`admission_decision` 的形近防线整条失效。

    合成：两个字位，形状证据一模一样（cov 0.995、无竞争），区别只在
    候选是不是形近家族的字。**两侧都验**——家族字不许自动进，非家族字
    必须照常进；只验一侧的话把防线整条删掉也照样绿。
    """
    from open_guji_cv.clustering.seeding import NEAR_FORM_CHARS

    family = next(iter(sorted(NEAR_FORM_CHARS)))
    plain = "鼇"
    assert plain not in NEAR_FORM_CHARS

    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=1, verdict="unsure", cov=0.995, wmax=0.0,
                 candidates=[(family, 0.995)]),
            dict(slot=2, verdict="unsure", cov=0.995, wmax=0.0,
                 candidates=[(plain, 0.995)]),
        ]))
    sa = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    by_slot = {r.slot: r for cc in sa.columns for r in cc.chars}

    assert by_slot[2].admit and by_slot[2].channel in ("match_solo", "match_solo_ocr"), \
        f"非形近家族字该照常自动进库：{by_slot[2].channel} / {by_slot[2].doubts}"
    assert not by_slot[1].admit or by_slot[1].channel not in ("match_solo",
                                                              "match_solo_ocr"), \
        f"形近家族字「{family}」只凭形状就走了 {by_slot[1].channel}"
