# -*- coding: utf-8 -*-
"""Step5-d 整理本对齐（阶段归位，2026-09-09）。

`align_ref` 从 `gold/v2_align.py` 里独立出来，成为与 `glyph_match`/
`ocr_candidates`/`context_decision` 平级的正式 Step；`gold.v2_align.align_page`
改成优先读它的产物再派生 `GoldChar`。这里守两条：

1. Step 本身：注册、`consumes`/`needs`、语料指纹进参数哈希；
2. 两个身份没有互相污染：`align_page` 读 `align_ref` 缓存 与 **不经缓存现算
   一遍**（脚本传非默认语料时的兜底路径）必须给出完全相同的结果——这是
   本次重组"纯重组不改变任何裁决"的核心保证，别的测试测不到这条。
"""

from __future__ import annotations

from dataclasses import asdict

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_match, write_product
from open_guji_cv.core.engine import params_hash
from open_guji_cv.core.step import KINDS, STEPS
from open_guji_cv.steps.align_ref import AlignRefParams

BOOK, PAGE, COL = "tbook", 1, 1

#: 测试自备的「整理本」。内容随便，只要够长到 8-gram 锚得住、且与下面那串
#: 刻本字位对得上——真语料（270 万字）既在仓外也不该被测试依赖。
REF_TEXT = "文華殿大學士臣紀昀等奉敕撰欽定四庫全書總目卷一經部易類一"
COLUMN_CHARS = "文華殿大學士臣紀昀等奉敕撰"


def _ctx_with_corpus(tmp_path, monkeypatch, *, chars: str = COLUMN_CHARS,
                     corpus_text: str = REF_TEXT * 30, corpus_name: str = "ref.txt"):
    """摆好「一列库 same 档字位 + 一份小整理本」，返回 (ctx, 语料路径)。"""
    corpus = tmp_path / corpus_name
    corpus.write_text(corpus_text, encoding="utf-8")
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    ctx.params["align_ref"] = AlignRefParams(corpus=str(corpus))
    recs = [dict(slot=i + 1, verdict="same", char=ch, cov=0.999, matched_id=f"g{i}")
            for i, ch in enumerate(chars)]
    write_product(ctx, "glyph_match", PAGE,
                  glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    return ctx, corpus


def test_registered():
    assert "align_ref" in STEPS and "align_ref" in KINDS
    assert "corpus" in STEPS["align_ref"].spec.needs
    # 2026-09-10 去掉对 context_decision 的依赖（不再借 Step6 的定字拼锚定串，
    # 见 align_ref.py 模块头「2026-09-10」一节）——四路才真正互相独立。
    #
    # 2026-09-13：`ocr_candidates` 从 consumes 挪到 optional_consumes。**吃的证据
    # 没变**（仍是库匹配 + OCR 两路），变的是缺席时怎么办：它是书级开关
    # `BookSpec.ocr_candidates` 控制的可选步骤（默认关，`Engine._enabled` 直接把它
    # 滤出 steps），写在 consumes 里会让指纹层 `upstream_shas` 认它是硬依赖、短路
    # 阻塞整步——而 `run_page` 早就用 `_opt()` 兜住了缺席（只在 match 和 ocr 都缺
    # 时才报错）。声明与实现对不上，vol01（开关关着）因此**整条 Step5-d/6/C1 全部
    # 阻塞**，`test_core_v2.test_keben_body_v2_on_vol01_page24` 一直挂在这上面。
    assert set(STEPS["align_ref"].spec.consumes) == {"glyph_match"}
    assert set(STEPS["align_ref"].spec.optional_consumes) == {"ocr_candidates"}


def test_corpus_fingerprint_lands_in_params_and_moves_the_hash():
    """语料换了同一批对齐结论就会变——指纹必须进参数、进哈希（同 context_decide）。"""
    p = AlignRefParams()
    assert p.corpus_fingerprint
    a = AlignRefParams(corpus_fingerprint="aaaa")
    b = AlignRefParams(corpus_fingerprint="bbbb")
    assert params_hash(a) != params_hash(b)


def test_align_ref_product_reads_as_continuous_prose(tmp_path, monkeypatch, ws):
    """端到端产出要读得通——这是"对齐挪出来"之后的整体验收。

    2026-09-20 改：原先读工作区里 vol01/24 的产物、钉「文華殿」「文淵」两个
    锚点，没跑过就 skip（云端从没执行过）。现在把刻本字位与整理本都由测试
    自己给：一列十二个 same 档字位、一份写着同一串字的小语料，对齐产物读出来
    必须逐字等于那一列——**这比原先那条严**（原先只查两个锚点在不在）。
    """
    ctx, _ = _ctx_with_corpus(tmp_path, monkeypatch)
    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert ar.anchored, f"锚不上：{ar.note}"
    c1 = sorted((c for c in ar.chars if c.col == COL), key=lambda c: c.slot)
    text = "".join(c.align_char for c in c1)
    assert text == COLUMN_CHARS, f"c1 对齐字读出来是「{text}」"
    assert all(c.align_op == "equal" for c in c1), \
        f"刻本与整理本逐字相同，不该出现 replace：{[(c.slot, c.align_op) for c in c1]}"


def test_unanchorable_page_says_so_instead_of_aligning_to_noise(tmp_path, monkeypatch,
                                                                ws):
    """语料里一个 n-gram 都命中不了时要如实报「没锚上」，不能硬对。

    硬对的后果是整列给出一串噪声字，而下游（seed_admit 的整理本通道）会把
    它当证据用——`_align()` 正是靠 `anchored` 这个标志决定要不要采信。
    """
    ctx, _ = _ctx_with_corpus(tmp_path, monkeypatch, corpus_text="甲乙丙丁" * 500)
    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert not ar.anchored
    assert ar.note, "没锚上却不说为什么"


def test_gold_derivation_matches_between_cached_and_live_recompute(tmp_path,
                                                                   monkeypatch, ws):
    """核心保证：读 `align_ref` 缓存 与 不经缓存现算一遍，`GoldChar` 必须逐条相同。

    `gold.v2_align.align_page` 两条路都会走到（默认语料走缓存，脚本传
    自定义语料走现算兜底，见该模块 `_aligned_chars` 的模块头），这条钉住
    两条路径算法完全一致，不是"看着都能跑"那种巧合。

    2026-09-20 改：原先要工作区的 vol01/24 产物 ＋ 8.2 MB 真语料，两样缺一
    就 skip，**而且本机跑的时候还踩过一次 fixture 抄错文件名**（复制的是另
    一部参考本，于是"现算"那一侧实际换了语料，op_run 从 63 变 139 —— 那不是
    算法分叉，是测试自己给错了输入）。现在两侧用的是**同一份内容、只是落盘到
    两个路径**的自备小语料，这才是这条真正要测的东西：语料给的信息完全一致时
    必须逐条相同（包括 op_run）。
    """
    from helpers import page_decision
    from open_guji_cv.gold.v2_align import align_book

    ctx, corpus = _ctx_with_corpus(tmp_path, monkeypatch)
    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert ar.anchored, f"锚不上：{ar.note}"
    ctx.store.write(BOOK, "align_ref", f"p{PAGE:04d}", {"align_ref": ar})
    # `align_page` 的载体是**定字产物**（金标要挂在已定的字位上），对齐结果
    # 只是给它配字，所以这里也得把 Step6 的产物摆上。
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=i + 1, char=ch, margin=1.0, source="db_same")
            for i, ch in enumerate(COLUMN_CHARS)]))

    cached = align_book(BOOK, [PAGE], ctx.store, corpus_path=corpus)
    # 内容相同、路径不同的副本：指纹（按路径 mtime/size 算）必然对不上缓存的
    # corpus_fingerprint，于是强制走现算兜底路径。
    copy = tmp_path / "corpus_copy.txt"
    copy.write_text(corpus.read_text(encoding="utf-8"), encoding="utf-8")
    live = align_book(BOOK, [PAGE], ctx.store, corpus_path=copy)

    assert cached[0].anchored and live[0].anchored
    assert [asdict(c) for c in cached[0].chars] == [asdict(c) for c in live[0].chars]
