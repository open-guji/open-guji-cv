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
from pathlib import Path

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


def test_lib_gate_drops_confident_non_variant_replace_but_keeps_variants(tmp_path, monkeypatch, ws):
    """库证据闸（align_ref 模块头 2026-09-22）：

    - 库 cov 0.9995 认下「入」、整理本给「人」（不是异体）→ 这一位不采信；
    - 同样 cov，库认「巳」、整理本「已」（variants.json 登记的异体）→ 照采（人裁 66/66 全对）；
    - 库 cov 0.95（不够信）认「入」、整理本「人」→ 照采（长度闸说了算）。
    """
    from open_guji_cv.steps.align_ref import AlignRefParams as P
    # 刻本列：第 2 位库认「入」，第 15 位库认「巳」；整理本对应位是「人」「已」。
    # 两处替换之间要留 ≥8 个相同字，8-gram 才锚得住。
    col = "文入華殿大學士臣紀昀等奉敕撰巳欽定四庫全書總目卷一"
    ref = ("文人華殿大學士臣紀昀等奉敕撰已欽定四庫全書總目卷一經部易類一") * 30
    corpus = tmp_path / "ref.txt"; corpus.write_text(ref, encoding="utf-8")

    def run(cov3: float, gate: bool = True):
        ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
        ctx.params["align_ref"] = P(corpus=str(corpus), lib_gate=gate)
        recs = [dict(slot=i + 1, verdict="same", char=ch, cov=(cov3 if i == 1 else 0.9995),
                     matched_id=f"g{i}") for i, ch in enumerate(col)]
        write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
        ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
        assert ar.anchored, ar.note
        return ar, {c.slot: (c.align_char, c.align_op) for c in ar.chars if c.col == COL}

    ar, got = run(0.9995)
    assert 2 not in got, f"库高信度认「入」、整理本「人」非异体，该拦下，实得 {got.get(2)}"
    assert got.get(15) == ("已", "replace"), f"巳/已 是异体，该照采，实得 {got.get(15)}"
    assert ar.n_lib_dropped == 1
    _, got = run(0.95)
    assert got.get(2) == ("人", "replace"), "库不够信时长度闸说了算"
    ar, got = run(0.9995, gate=False)
    assert got.get(2) == ("人", "replace") and ar.n_lib_dropped == 0


# ── 多证人合并（2026-09-27，任务书 D-多证人对齐策略） ─────────────────────


def test_book_corpus_ignores_quality_and_takes_first_reference(tmp_path, monkeypatch):
    """现状（`witness_strategy="legacy"` 时走的路）：`book_corpus()` 只看
    `references[0]`，不管 `quality` 标签——这正是 Z5 全唐文实测「Kanripo(best)
    +维基(mid) 组合」与「仅 Kanripo」逐字节相同的根源（align_ref 模块头
    「多证人合并」一节）。低质量证人排第一时，legacy 策略会用它。
    """
    import open_guji_cv.core.book as book_mod
    from open_guji_cv.steps.align_ref import book_corpus

    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "low.txt").write_text("低质量证人排第一", encoding="utf-8")
    (tmp_path / "corpus" / "best.txt").write_text("高质量证人排第二", encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))

    class FakeBook:
        references = [{"file": "low.txt", "quality": "low"},
                      {"file": "best.txt", "quality": "best"}]

    monkeypatch.setattr(book_mod, "load_book", lambda book_id, books_dir=None: FakeBook())
    got = book_corpus(BOOK)
    assert Path(got).name == "low.txt", \
        f"现状只看列表第 0 项、不管 quality，该是 low.txt，实得 {Path(got).name}"


def _write_corpus(ws_root, name: str, text: str) -> None:
    (Path(ws_root) / "corpus" / name).write_text(text, encoding="utf-8")


def test_normalize_strategy_picks_best_quality_witness_not_list_position(tmp_path,
                                                                          monkeypatch, ws):
    """`witness_strategy="normalize"`：按 `quality` 选证人，不看 `references`
    列表顺序——低质量证人排第一、内容却完全不相关，仍应取到排第二的最佳证人。
    """
    from open_guji_cv.steps.align_ref import AlignRefParams as P
    col = "文華殿大學士臣紀昀等奉敕撰"
    _write_corpus(ws, "low.txt", ("毫不相干的另一段文字用来占位充数") * 20)
    _write_corpus(ws, "best.txt", (col + "欽定四庫全書總目卷一經部易類一") * 20)

    book = make_book(BOOK, references=[
        {"file": "low.txt", "quality": "low", "label": "低质量证人"},
        {"file": "best.txt", "quality": "best", "label": "最佳证人"},
    ])
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    ctx.params["align_ref"] = P(witness_strategy="normalize")
    recs = [dict(slot=i + 1, verdict="same", char=ch, cov=0.999, matched_id=f"g{i}")
            for i, ch in enumerate(col)]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))

    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert ar.anchored, f"该用最佳证人锚上，实得：{ar.note}"
    assert ar.witness_strategy == "normalize" and ar.n_witnesses == 2
    c1 = sorted((c for c in ar.chars if c.col == COL), key=lambda c: c.slot)
    assert "".join(c.align_char for c in c1) == col


def test_normalize_strategy_absorbs_known_variant_pair_legacy_would_flag_as_replace(
        tmp_path, monkeypatch, ws):
    """异体归一比较（模块头「多证人合并」一节）：`glyph_match` 载体给「為」，
    唯一证人原文是「爲」——两者是 `variants.tsv` 登记的已知异体。legacy 按原始
    字形比较判 `replace`；`normalize` 先归一再比，判 `equal`，且**取字仍是证人
    原文的字形**（「爲」，不会被偷换成归一目标字）。
    """
    from open_guji_cv.steps.align_ref import AlignRefParams as P
    # 变异位两侧各留 10/15 字的稳定匹配区，8-gram 才能绕开变异位投出干净票——
    # 太短的串（变异位周围不到 8 字）会让**所有**窗口都扫过变异位，直接锚不上。
    prefix, suffix = "文華殿大學士臣紀昀等", "欽定四庫全書總目卷一經部易類一"
    hyp_col = prefix + "為" + suffix        # 载体（glyph_match 认的字）：為
    true_col = prefix + "爲" + suffix       # 证人原文：爲
    _write_corpus(ws, "ref.txt", true_col * 20)

    def run(strategy: str):
        book = make_book(BOOK, references=[{"file": "ref.txt", "quality": "best"}])
        ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
        ctx.params["align_ref"] = P(witness_strategy=strategy,
                                    corpus=str(Path(ws) / "corpus" / "ref.txt"))
        recs = [dict(slot=i + 1, verdict="same", char=ch, cov=0.999, matched_id=f"g{i}")
                for i, ch in enumerate(hyp_col)]
        write_product(ctx, "glyph_match", PAGE,
                      glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
        ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
        assert ar.anchored, ar.note
        return {c.slot: (c.align_char, c.align_op) for c in ar.chars if c.col == COL}

    got_legacy = run("legacy")
    assert got_legacy.get(11) == ("爲", "replace"), \
        f"legacy 按原始字形比较，该判 replace，实得 {got_legacy.get(11)}"
    got_norm = run("normalize")
    assert got_norm.get(11) == ("爲", "equal"), \
        f"normalize 该把已知异体判 equal、取证人原文「爲」，实得 {got_norm.get(11)}"


def test_majority_vote_strategy_tie_break_by_quality(tmp_path, monkeypatch, ws):
    """两家证人在同一位给出不同字、票数 1:1 打平 → 按 `quality` 取高的那家。"""
    from open_guji_cv.steps.align_ref import AlignRefParams as P
    # 同上一条测试：变异位两侧各留够 8 字，两家证人才都能各自独立锚上
    # （锚不上的那家会被 `_majority_vote_labels` 悄悄跳过，测不出真正的表决）。
    prefix, suffix = "文華殿大學士臣紀昀等", "欽定四庫全書總目卷一經部易類一"
    hyp_col = prefix + "入" + suffix
    best_col = prefix + "入" + suffix     # 最佳证人：与载体一致（入）
    low_col = prefix + "人" + suffix      # 低质量证人：另一种转写（人）
    _write_corpus(ws, "best.txt", best_col * 20)
    _write_corpus(ws, "low.txt", low_col * 20)

    book = make_book(BOOK, references=[
        {"file": "low.txt", "quality": "low", "label": "低质量证人"},
        {"file": "best.txt", "quality": "best", "label": "最佳证人"},
    ])
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    ctx.params["align_ref"] = P(witness_strategy="majority_vote")
    recs = [dict(slot=i + 1, verdict="same", char=ch, cov=0.999, matched_id=f"g{i}")
            for i, ch in enumerate(hyp_col)]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))

    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert ar.anchored, ar.note
    assert ar.n_witnesses == 2
    got = {c.slot: (c.align_char, c.align_op) for c in ar.chars if c.col == COL}
    assert got.get(11) == ("入", "equal"), \
        f"1:1 打平该取质量高的那家（最佳证人「入」），实得 {got.get(11)}"


def test_majority_vote_strategy_true_majority_overrides_single_higher_quality_witness(
        tmp_path, monkeypatch, ws):
    """三家证人：两家（质量都是 low）都给「人」，一家（质量 best）给「入」——
    票数 2:1，多数赢，即使那两家质量都不如那一家高。这是「按字多数表决」与
    「单纯按质量选一家」的区别所在：质量选择在这里会选错（best 只有一票）。
    """
    from open_guji_cv.steps.align_ref import AlignRefParams as P
    prefix, suffix = "文華殿大學士臣紀昀等", "欽定四庫全書總目卷一經部易類一"
    hyp_col = prefix + "人" + suffix
    majority_col = prefix + "人" + suffix   # 两家 low：人
    best_col = prefix + "入" + suffix        # 一家 best：入
    _write_corpus(ws, "low1.txt", majority_col * 20)
    _write_corpus(ws, "low2.txt", majority_col * 20)
    _write_corpus(ws, "best.txt", best_col * 20)

    book = make_book(BOOK, references=[
        {"file": "low1.txt", "quality": "low", "label": "低质量证人一"},
        {"file": "low2.txt", "quality": "low", "label": "低质量证人二"},
        {"file": "best.txt", "quality": "best", "label": "最佳证人"},
    ])
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    ctx.params["align_ref"] = P(witness_strategy="majority_vote")
    recs = [dict(slot=i + 1, verdict="same", char=ch, cov=0.999, matched_id=f"g{i}")
            for i, ch in enumerate(hyp_col)]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))

    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert ar.anchored, ar.note
    assert ar.n_witnesses == 3
    got = {c.slot: (c.align_char, c.align_op) for c in ar.chars if c.col == COL}
    assert got.get(11) == ("人", "equal"), \
        f"2 票该赢 1 票，实得 {got.get(11)}"


def test_witness_fingerprint_filled_from_book_references_when_not_legacy(tmp_path,
                                                                          monkeypatch, ws):
    """`witness_fingerprint` 按 `references` 全部文件算（`core/step.py::
    _with_witness_fingerprint`），换一份证人文件内容就会变；`legacy` 策略
    不填这个字段（继续用 `corpus_fingerprint`）。"""
    from open_guji_cv.steps.align_ref import AlignRefParams as P
    _write_corpus(ws, "a.txt", "甲乙丙丁" * 10)
    _write_corpus(ws, "b.txt", "戊己庚辛" * 10)
    book = make_book(BOOK, references=[{"file": "a.txt", "quality": "best"},
                                        {"file": "b.txt", "quality": "mid"}])
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)

    from open_guji_cv.core.step import STEPS
    step = STEPS["align_ref"]
    ctx.params["align_ref"] = P()
    p1 = ctx.params_for(step)
    assert p1.witness_fingerprint == "", "legacy 不该填 witness_fingerprint"

    ctx.params["align_ref"] = P(witness_strategy="majority_vote")
    p2 = ctx.params_for(step)
    fp_before = p2.witness_fingerprint
    assert fp_before

    _write_corpus(ws, "b.txt", "壬癸子丑" * 10)   # 换掉第二份证人的内容
    ctx.params["align_ref"] = P(witness_strategy="majority_vote")
    p3 = ctx.params_for(step)
    assert p3.witness_fingerprint != fp_before, "换了证人文件内容，指纹该变"


# ---------------------------------------------------------------------------
# uncontested_relax（任务卡 D-align_ref锚定召回-全唐文，2026-09-27）：
# v006 全书实测发现「最高票簇 1-4 票」失败页里绝大多数没有竞争簇（
# `avg_hits_per_hit_gram`≈1、`n_clusters`==1），是刻本侧连续 8 字全对太难，
# 不是套语碰撞——见 `AlignRefParams.uncontested_relax` 模块头。这里用可控的
# 合成语料复现三种情形：唯一无竞争低票页（该收）、有竞争簇的低票页（不该
# 收）、命中率不够的低票页（不该收）。
# ---------------------------------------------------------------------------

# 目标串本身不含重复子串，嵌进「甲乙丙丁…」这类互不相干的填充文字里，
# 保证除嵌入处外语料里不会有第二处巧合命中。
_UR_TARGET = "文華殿大學士臣紀昀等奉敕撰經進四庫全書總目提要恭呈御覽伏候聖裁謹奏"
_UR_FILLER_A = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥零壹貳參肆伍陸柒捌玖拾"
_UR_FILLER_B = "東西南北中上下前後左右春夏秋冬金木水火土日月星辰風雲雷電山川湖海"


def _ur_corpus_text(*, duplicate: bool = False) -> str:
    if duplicate:
        # 语料里把目标串重复一遍——真「套语碰撞」的最小复现：两处命中票数
        # 相当，谁都不占绝对优势。
        return _UR_FILLER_A * 3 + _UR_TARGET + _UR_FILLER_B * 3 + _UR_TARGET + _UR_FILLER_A * 3
    return _UR_FILLER_A * 3 + _UR_TARGET + _UR_FILLER_B * 3


def _ur_hyp(error_positions: tuple[int, ...] = (5, 15, 25)) -> str:
    """把 `_UR_TARGET` 在给定位置换成形近字混淆的近似——用来控制「留下几个
    干净的 8-gram」。默认三个位置量出来正好留 4 个干净窗口（< 绝对下限 5），
    且只在真实位置命中、没有竞争簇（见模块头「uncontested_relax」一节的
    prototype 实测）。"""
    chars = list(_UR_TARGET)
    for pos in error_positions:
        chars[pos] = "錯"
    return "".join(chars)


def test_uncontested_relax_off_by_default():
    assert AlignRefParams().uncontested_relax is False


def test_uncontested_relax_recovers_uncontested_low_vote_page(tmp_path, monkeypatch, ws):
    """核心场景：3 处形近字错误，只留 4 个干净的 8-gram（< 绝对下限 5），
    但语料里只有这一处命中、没有竞争簇——`uncontested_relax` 应该收下，
    且锚定后的字符仍是**语料字**（等长 replace 位一样吃 `replace_len_gate`，
    不是把兜底当成放宽单字采信）。"""
    hyp = _ur_hyp()
    ctx, _ = _ctx_with_corpus(tmp_path, monkeypatch, chars=hyp,
                              corpus_text=_ur_corpus_text())

    legacy = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert not legacy.anchored, f"这个场景本该锚不上（legacy）：{legacy.note}"
    assert legacy.anchor_via == "ngram"

    ctx.params["align_ref"] = AlignRefParams(corpus=ctx.params["align_ref"].corpus,
                                             uncontested_relax=True)
    relaxed = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert relaxed.anchored, f"低票兜底该收但没收：{relaxed.note}"
    assert relaxed.anchor_via == "uncontested"
    text = "".join(c.align_char for c in sorted(relaxed.chars, key=lambda c: c.slot))
    # 三处形近字错位没有匹配上下文，difflib 会把它们判成 delete（不是等长
    # replace），`_labels_from_ops` 照 `align_label` 原有规则把 delete 段整段
    # 丢弃——这是复用既有过闸逻辑的正常结果，不是这条新判据的行为。真正要
    # 守住的是：锚上的字全部是**语料字**、顺序不乱、错位那三个字不会污染
    # 输出（不会出现「錯」，也不会把语料窗口以外的字带进来）。
    assert "錯" not in text
    assert text == "".join(ch for i, ch in enumerate(_UR_TARGET) if i not in (5, 15, 25))


def test_uncontested_relax_does_not_override_contested_cluster(tmp_path, monkeypatch, ws):
    """语料里把目标串重复一遍（真套语碰撞）：两处命中票数相当，
    `uncontested_relax` 必须原样报「锚不上」，不能瞎猜一个。"""
    hyp = _ur_hyp()
    ctx, _ = _ctx_with_corpus(tmp_path, monkeypatch, chars=hyp,
                              corpus_text=_ur_corpus_text(duplicate=True))
    ctx.params["align_ref"] = AlignRefParams(corpus=ctx.params["align_ref"].corpus,
                                             uncontested_relax=True)
    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert not ar.anchored, "有竞争簇时不该被兜底收进去"
    assert ar.anchor_via == "ngram"


def test_uncontested_relax_still_rejects_low_equal_frac(tmp_path, monkeypatch, ws):
    """就算没有竞争簇，候选窗口命中率太低（这里只留头 8 字对、其余全错）
    也不该收——兜底判据是「双重门槛」，不是只看有没有竞争簇。"""
    hyp = list(_UR_TARGET)
    for i in range(9, len(hyp)):
        hyp[i] = "錯"
    ctx, _ = _ctx_with_corpus(tmp_path, monkeypatch, chars="".join(hyp),
                              corpus_text=_ur_corpus_text())
    ctx.params["align_ref"] = AlignRefParams(corpus=ctx.params["align_ref"].corpus,
                                             uncontested_relax=True)
    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert not ar.anchored, "命中率太低时不该被兜底收进去"


def test_uncontested_relax_needs_at_least_min_votes(tmp_path, monkeypatch, ws):
    """`uncontested_min_votes` 挡住「一票都没有」的页——这类页该继续报
    「候选太少」/「一个 n-gram 都没命中」，不该被这条参数掩盖。"""
    ctx, _ = _ctx_with_corpus(tmp_path, monkeypatch, corpus_text="甲乙丙丁" * 500)
    ctx.params["align_ref"] = AlignRefParams(corpus=ctx.params["align_ref"].corpus,
                                             uncontested_relax=True)
    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert not ar.anchored
    assert ar.anchor_via == "ngram"

