"""参考整理本 → 逐实例金标（char-ocr / context-correction 两个测试集的共用地基）。

`align_eval` 只回答「这一页对了多少字」；建测试集要的是更细一格的东西：
**每一个图块实例的金标字是什么**。两者共用同一套锚定逻辑，区别在于
这里要把 `SequenceMatcher` 的 opcode 落回到 `page:col:idx` 上。

## 为什么金标可以来自对齐（不是循环论证）

金标的**取值**来自用户提供的整理本，与被测的任何 OCR 引擎无关；转写
只用来**定位**（锚定偏移）。但定位这一步确实依赖转写质量，于是引入一个
必须写进 `known_limitation` 的偏置：**锚不上的页不进样本**，而锚不上的
页往往正是识别最差的页。所以本集上的准确率是**乐观**的，只能用于
「同一批样本上比较不同算法」，不能当作全书真实字准确率。

## 逐块采信规则（这一节是本模块的全部难点）

`SequenceMatcher` 给出四类 opcode，能安全落到实例上的只有前两类：

- ``equal``：逐位对应，金标 = 参考字。放心采信。
- ``replace`` 且两侧等长：逐位对应，金标 = 参考字——**这一类才是识别
  错误的样本**，只取 equal 会让金标集变成「OCR 已经对的那些字」，
  在上面测出来的准确率恒为 100%，是自证。
- ``replace`` 两侧不等长 / ``insert`` / ``delete``：切分多切或漏切，
  位置对应关系已经断了，逐位落标必错。**一律标 uncertain 并排除**。

等长 `replace` 也不是无条件可信：一段长替换内部可能同时藏着一次漏切和
一次多切，凑巧长度相抵，逐位对应仍然是错的。故再加一道**锚夹**判据：
替换段长度 ≤ ``MAX_REPLACE_RUN``，且左右都紧邻长度 ≥ ``MIN_FLANK`` 的
``equal`` 段。夹不住的照样标 uncertain。被排除的数量必须报出来——
排除得越多，剩下的样本越偏向「容易的地方」。
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from .align_eval import WINDOW_PAD, anchor_page, build_ngram_index
from .extractor import load_index

MAX_REPLACE_RUN = 3   # 等长替换段最长采信多少字
MIN_FLANK = 2         # 替换段左右各需多长的 equal 段做锚夹


@dataclass
class GoldItem:
    """一个图块实例的金标。"""
    instance_id: str
    page: str
    col: int
    idx: int
    pos: int            # 在页转写序列中的位置（0 起）
    gold: str           # 参考整理本给出的字
    transcribed: str    # 当次转写给出的字（仅供分析，不是金标）
    opcode: str         # equal | replace
    patch_path: str


@dataclass
class PageGold:
    page: str
    anchored: bool
    ref_offset: int | None
    n_instances: int
    items: list[GoldItem]
    n_uncertain: int          # 落在 insert/delete/夹不住的替换段里，被排除
    ref_window: str           # 对齐窗口内的参考文本（供上下文字段使用）


def _accept_opcodes(opcodes: list[tuple]) -> list[tuple[str, int, int, int, int]]:
    """从 opcode 序列里挑出可逐位落标的段（见模块 docstring 的规则）。"""
    out: list[tuple[str, int, int, int, int]] = []
    for k, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            out.append(("equal", i1, i2, j1, j2))
            continue
        if tag != "replace" or (i2 - i1) != (j2 - j1):
            continue
        if (i2 - i1) > MAX_REPLACE_RUN:
            continue
        prev_ok = k > 0 and opcodes[k - 1][0] == "equal" \
            and (opcodes[k - 1][2] - opcodes[k - 1][1]) >= MIN_FLANK
        next_ok = k + 1 < len(opcodes) and opcodes[k + 1][0] == "equal" \
            and (opcodes[k + 1][2] - opcodes[k + 1][1]) >= MIN_FLANK
        if prev_ok and next_ok:
            out.append(("replace", i1, i2, j1, j2))
    return out


def gold_for_page(page: str, instances: list, text: str, corpus: str,
                  corpus_index: dict[str, list[int]]) -> PageGold:
    """单页：转写序列 + 实例序列 → 逐实例金标。

    ``instances`` 必须已按 (col, idx) 排序，且与 ``text``（去掉换行的页
    转写）**逐位对应**——这是 `labeling.rank_book` 写 `text/` 时的顺序，
    两边任何一处改了顺序，这里的金标就会整体错位。
    """
    offset = anchor_page(text, corpus_index)
    if offset is None:
        return PageGold(page, False, None, len(instances), [], len(instances), "")

    lo = max(0, offset)
    hi = min(len(corpus), offset + len(text) + WINDOW_PAD)
    window = corpus[lo:hi]
    sm = difflib.SequenceMatcher(None, text, window, autojunk=False)
    accepted = _accept_opcodes(sm.get_opcodes())

    items: list[GoldItem] = []
    covered: set[int] = set()
    for tag, i1, i2, j1, j2 in accepted:
        for k in range(i2 - i1):
            pos = i1 + k
            if pos >= len(instances):
                continue
            inst = instances[pos]
            covered.add(pos)
            items.append(GoldItem(
                instance_id=inst.id, page=page, col=inst.col, idx=inst.idx,
                pos=pos, gold=window[j1 + k], transcribed=text[pos],
                opcode=tag, patch_path=inst.patch_path))
    return PageGold(page, True, offset, len(instances), items,
                    len(instances) - len(covered), window)


def gold_for_book(book_out_dir: str | Path, corpus_path: str | Path
                  ) -> tuple[list[PageGold], str]:
    """整册：读 phase4 实例 + phase6 转写 → 每页金标。返回 (每页金标, 语料全文)。

    实例顺序与 `labeling.rank_book` 完全一致：页内按 (col, idx) 升序，
    即列从右到左、列内从上到下。
    """
    from collections import defaultdict

    book = Path(book_out_dir)
    corpus = Path(corpus_path).read_text(encoding="utf-8")
    index = build_ngram_index(corpus)

    by_page: dict[str, list] = defaultdict(list)
    for inst in load_index(book / "phase4_chars"):
        by_page[inst.page].append(inst)

    text_dir = book / "phase6_labels" / "text"
    out: list[PageGold] = []
    for page in sorted(by_page, key=lambda p: (len(p), p)):
        tp = text_dir / f"{page}.txt"
        if not tp.exists():
            continue
        text = tp.read_text(encoding="utf-8").replace("\n", "")
        insts = sorted(by_page[page], key=lambda i: (i.col, i.idx))
        if len(text) != len(insts):
            # 顺序契约被破坏，逐位落标不再可信——整页弃用而不是硬对齐
            out.append(PageGold(page, False, None, len(insts), [],
                                len(insts), ""))
            continue
        out.append(gold_for_page(page, insts, text, corpus, index))
    return out, corpus
