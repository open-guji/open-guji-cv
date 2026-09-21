# -*- coding: utf-8 -*-
"""Step6 上下文裁决包壳（阶段 B1）。

守两条铁律（context_step 模块头写死的，换任何模型都不许破）：
字形层不可改写（只在候选内重排）、门槛化不做全局重排（拿不准就弃权）。

2026-09-20 重写：原先四条都读工作区里 vol01/24 跑出来的产物，没跑过就 skip。
这一步只读产物、不碰图像，所以现在自己把上游证据与**一份 200 字的小语料**
摆好再跑真的 `run_page`——三条分支（db_same / context / prior）都能稳定造出来，
不用指望「这次跑批恰好有」。

⚠️ 语料必须显式指到测试自己那份：`ContextDecideParams.general_corpus_dir`
默认 `"corpus/external"` 是**相对 cwd** 解析的（不走 `core.workspace`），
在仓根下跑就会去读仓里那两份 15 MB 的泛古籍语料——既慢（实测单条用例
36 秒 → 0.3 秒）又把测试绑在了会变的生产数据上。
"""

from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_match, write_product
from open_guji_cv.core.engine import params_hash
from open_guji_cv.core.step import KINDS, STEPS
from open_guji_cv.steps.context_decide import ContextDecideParams, corpus_fingerprint

BOOK, PAGE, COL = "tbook", 1, 1

#: 小语料：只要够让 n-gram 认出「文華殿」这一串就行。
CORPUS_TEXT = "文華殿大學士臣紀昀等奉敕撰。" * 200


def _run(tmp_path, monkeypatch, *, recs, corpus_text: str = CORPUS_TEXT):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text(corpus_text, encoding="utf-8")
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    ctx.params["context_decide"] = ContextDecideParams(
        corpus=str(corpus),
        general_corpus_dir=str(tmp_path / "no_general_corpus"))
    write_product(ctx, "glyph_match", PAGE,
                  glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    return STEPS["context_decide"].run_page(ctx, PAGE)["context_decision"]


def _recs():
    """一列三个字位，正好覆盖三条分支：库 same / 上下文定得下 / 定不下。"""
    return [
        dict(slot=1, verdict="same", char="文", cov=0.999, matched_id="g1"),
        dict(slot=2, verdict="unsure", cov=0.96, candidates=[("華", 0.60), ("垂", 0.55)]),
        dict(slot=3, verdict="unsure", cov=0.80, candidates=[("殿", 0.55), ("展", 0.54)]),
    ]


def test_registered_and_declares_corpus_need():
    assert "context_decide" in STEPS and "context_decision" in KINDS
    assert "corpus" in STEPS["context_decide"].spec.needs


def test_corpus_fingerprint_lands_in_params_and_moves_the_hash():
    """语料换了同一批候选的裁决就会变——指纹必须进参数、进哈希。"""
    p = ContextDecideParams()
    assert p.corpus_fingerprint
    a = ContextDecideParams(corpus_fingerprint="aaaa")
    b = ContextDecideParams(corpus_fingerprint="bbbb")
    assert params_hash(a) != params_hash(b)
    assert corpus_fingerprint([]) == "nocorpus"


def test_same_tier_is_inherited_not_rearranged(tmp_path, monkeypatch):
    """库 same 档必须原样继承。

    库匹配的 match_precision 是 ≥0.999 的硬约束，让 LM 去重排它只会净亏
    ——1681 槽位实测无条件重排在任何 λ 下都是负的（λ=0.95 仍救 17/坏 34）。

    这里**故意让语料跟库判的字唱反调**：语料里「文」后面从来不接别的，
    而给 slot 1 的库判决是 same。语料再怎么想改也不许改。
    """
    d = _run(tmp_path, monkeypatch, recs=_recs())
    dmap = {r.id: r for cc in d.columns for r in cc.chars}
    same_id = f"{BOOK}:{PAGE}:{COL}:1"
    dec = dmap[same_id]
    assert dec.char == "文", f"库判 文，裁决改成了 {dec.char}——字形层被改写了"
    assert dec.source == "db_same"
    assert dec.margin == 1.0, "same 档不该参与打分"


def test_context_never_invents_a_char_outside_the_candidates(tmp_path, monkeypatch):
    """只在候选内重排——定出来的字必须是库给的候选之一，不许凭空冒出来。"""
    d = _run(tmp_path, monkeypatch, recs=_recs())
    cands = {r["slot"]: {c for c, _ in r.get("candidates", [])} for r in _recs()}
    for cc in d.columns:
        for r in cc.chars:
            if r.source != "context":
                continue
            assert r.char in cands[r.slot], \
                f"{r.id} 定出 {r.char}，不在候选 {cands[r.slot]} 里"


def test_low_margin_abstains_instead_of_guessing(tmp_path, monkeypatch):
    """门槛化：margin 不过阈就弃权（char=None），不硬猜。

    两侧都验：语料撑得住的（華/殿）要定下来，语料里压根没有的两个字
    要弃权——只验一侧的话判据删掉也照样绿。
    """
    gate = ContextDecideParams().margin_gate

    d = _run(tmp_path, monkeypatch, recs=_recs())
    by_slot = {r.slot: r for cc in d.columns for r in cc.chars}
    assert by_slot[2].source == "context" and by_slot[2].char == "華", by_slot[2]
    assert by_slot[2].margin >= gate

    # 语料里没有的候选：定不下来，必须弃权
    blind = _run(tmp_path, monkeypatch, recs=[
        dict(slot=1, verdict="unsure", cov=0.9, candidates=[("鼈", 0.51), ("鼇", 0.50)]),
    ])
    r = blind.columns[0].chars[0]
    assert r.source == "prior" and r.char is None, \
        f"语料给不出信息却硬猜了 {r.char}（margin={r.margin}）"

    for cc in d.columns:
        for r in cc.chars:
            if r.source == "context":
                assert r.char and r.margin >= gate, \
                    f"{r.id} 报了 context 却没过阈：margin={r.margin}"
            if r.source == "prior":
                assert r.char is None, f"{r.id} 没过阈却给了字 {r.char}"


def test_decided_text_reads_in_slot_order(tmp_path, monkeypatch):
    """端到端产出的列文本按 slot 顺序拼得出来——这是六步全链的形状验收。

    2026-09-20 改：原先钉的是 vol01 p24 c1 读出来含「文華殿」「文淵」两个
    锚点。那是**对某本真书某一页的质量断言**，属评测范畴（`guji eval run`
    里有整理本对勘），不是代码行为；产物不在就 skip，云端从没跑过。
    现在在自备语料上钉同一条形状：定得下来的字按读序连得成串。
    """
    d = _run(tmp_path, monkeypatch, recs=_recs())
    cc = d.column(COL)
    assert cc is not None
    text = "".join(r.char or "" for r in sorted(cc.chars, key=lambda x: x.slot))
    assert text == "文華殿", f"读出来是「{text}」"
