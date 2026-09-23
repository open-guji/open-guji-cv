# -*- coding: utf-8 -*-
"""9.3 与整理本对比校验：字位流 × 证人 → 分类差异 + 列结构裁定。

设计见 `overview` 仓 `项目进展/图片初步数字化/进度/Step9-结果整理/04-与整理本对比校验.md`，
证人清单见同目录 `05-整理本清单.md`。前身是 `scripts/build_collation_report.py`
（2026-09-06，vol01 全册跑过），本模块把它的口径搬进包里并补四件事：
共享字位流、多证人、转换方向、列结构。

## 三条不要动的口径（前身踩出来的，全在这里）

1. **对齐前先归语义层，分类按原字**：刻本「厯」对整理本「一歷」，按原字
   difflib 会配成 厯→一 ＋ 缺 歷；归一后 厯≡歷 才配得上，「一」才正确记成
   整理本多。但 `equal` 段内必须**逐字看原字**——第一版没看，144 条异体被吞成 37。
2. **窗口头尾各留 `WINDOW_PAD`，贴页首/页尾的 op 一律丢**：余量本身不是缺字。
   它不一定表现为纯 insert——页末最后一格若不一致，difflib 会给「1 字 vs 61 字」
   的不等长 replace（实测 p11/p33 各冒 50+ 条假 missing）。代价：页首/页末真缺
   看不见，记在案。
3. **整理本多出的连续一串合成一条**：p5 整列 21 字缺失若拆成 21 条，
   只会把同一张截条图重复 21 遍。

## 与 `align_ref` 产物的关系：**不能直接用它**

Step5-d 的 `align_ref` 走**采信闸**（equal 全收；等长 replace 段长 ≤3 且被 equal
夹住），insert/delete/长 replace 全部丢弃——那是为了出干净金标。而 9.3 要看的
「增删」恰恰在被丢的那部分，所以本模块自己跑一遍全 opcode 对齐。
闸不能动：放宽它会污染准入与金标。

## 为什么要按 channel 分层报

约 85% 的字是「与整理本一致」才放行的（vol01 20,778 位里 dual 15,903 ＋
match_ref 1,748，`steps/seed_admit.py`）。拿同一份整理本再比一遍，这 85% 恒等
——**是回声不是校验**。有信息量的是人裁、match_solo、context、未放行位。
`summarize()` 因此按 `kind × channel` 出表，不给单一总一致率。
"""
from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass, field

from ..clustering.align_eval import WINDOW_PAD, anchor_page
from ..clustering.align_label import is_han
from ..clustering.variants import VariantMap
from ..eval.round_check import _same_char
from ..products.store import ProductStore
from .absent import absent_runs
from .slots import SlotRec, page_slots
from .witness import Witness, col_verdict

#: 阙文/无字位在比对串里的占位符。**必须占一格**——跳过会让后面的字全部前移，
#: 错位比「这一格不知道是什么」严重得多。
PLACEHOLDER = "□"

_VM: VariantMap | None = None


def _vm() -> VariantMap:
    global _VM
    if _VM is None:
        _VM = VariantMap.load()
    return _VM


@dataclass
class Diff:
    """一条差异。`id` 是全管线主键，深链直接用它。"""
    id: str
    page: int
    col: int
    slot: int
    sub: str | None
    kind: str
    char: str          # 我们的字（阙文为 □，missing 为空）
    ref: str           # 证人的字（extra 为空；missing 时是一整串）
    witness: str       # 证人 label
    channel: str | None = None
    admit: bool = False
    human: bool = False
    reading: str | None = None
    n: int = 1         # missing 串长
    hyp_ctx: str = ""
    ref_ctx: str = ""


@dataclass
class ColDiff:
    """一列的结构裁定（只有 `line_is_column` 的证人给得出）。"""
    page: int
    col: int
    kind: str          # col.ok | col.short | col.long | col.drift
    delta: int         # 我们的字数 − 证人行长
    witness: str


@dataclass
class PageResult:
    page: int
    anchored: bool
    n_slots: int = 0
    n_text: int = 0
    n_excluded: int = 0
    n_unreadable: int = 0
    n_equal: int = 0
    note: str = ""
    diffs: list[Diff] = field(default_factory=list)
    cols: list[ColDiff] = field(default_factory=list)
    absent_runs: list[dict] = field(default_factory=list)
    """证人里没有的段（按语/卷端题/卷末题），**不进 diffs**——见 report/absent.py。
    报告要单独说明「这里有一段、证人没有」，否则读者会奇怪这页字数怎么对不上。"""


def classify(char: str, reading: str | None, ref: str) -> str:
    """一个字位的差异性质。判定顺序固定、互斥，先命中者生效（04 卡 §二·3）。

    - `same`：字形一致；
    - `conv.known`：管线已记账的转换（`reading == ref`）——不是新发现的差异；
    - `variant.to_orthodox` / `variant.to_simp` / `variant.other`：同一个字的
      不同形，按**方向**分；
    - `sub.confusable`：T3 形近（己已巳、日曰、人入）——最可能是认错；
    - `sub.other`：其他不同字。

    「同字」判定复用 `eval/round_check._same_char`（T1 直接同、T2 要本书用字账
    背书、T3 永不），**别再写一套**——那个函数的分层是 2026-09-06 大→太 ×12
    的误判换来的。
    """
    if char == ref:
        return "same"
    if char == PLACEHOLDER:
        return "unreadable"
    if reading is not None and reading == ref:
        return "conv.known"
    if _same_char(char, ref):
        return _variant_direction(char, ref)
    # ⚠️ 简体判定要在 `_same_char` **之后、认错之前**单独来一遍。
    # `_same_char` 对 T2（互通/一对多）返回 False——學/学 就是 T2，
    # 若直接落进 `sub.*`，一个明显的「整理本用了简体」会被报成「我们认错字」，
    # 正是用户 2026-09-13 要求分开的两件事。这里不放宽 `_same_char`
    # （那会污染判据 A 与准入），只在本模块的分类上多问一句。
    if _is_simplified_of(char, ref):
        return "variant.to_simp"
    return "sub.confusable" if _is_confusable(char, ref) else "sub.other"


def _variant_direction(char: str, ref: str) -> str:
    """异体的方向：整理本取的是正字，还是简体？

    读 `variants.py` 的有向表 `regulars_of(异体) → [(正字, 来源标签…)]`
    （`directed` 那一节只收带方向的来源）。我们刻的是 `char`、整理本印的是
    `ref`，所以问的是「`ref` 是不是各来源指认的、`char` 的正字」。

    ⚠️ `SIMPLIFIED_SOURCES` 直接用 `variants.py` 的定义，别在这里另抄一份
    ——它含 `unihan:kTraditionalVariant`／`dypytz`，跟直觉不一样（模块注释说明
    「对繁体刻本方向是反的」），自己列清单必然抄漏。
    """
    try:
        from ..variants import SIMPLIFIED_SOURCES, regulars_of
        srcs = {r: set(tags) for r, tags in regulars_of(char)}.get(ref, set())
    except Exception:
        srcs = set()
    if srcs:
        # 简繁类来源单独成一档；其余带方向的来源（twedu/hydzd 等）＝指认正字
        return "variant.to_simp" if srcs <= set(SIMPLIFIED_SOURCES) else "variant.to_orthodox"
    # 方向表没有这一对：用 opencc 兜底判一次简体。语料本该是繁体，
    # 出现简体就是整理本用了简体，值得单独计数。
    if _is_simplified_of(char, ref):
        return "variant.to_simp"
    return "variant.other"


def _is_simplified_of(char: str, ref: str) -> bool:
    """`ref` 是不是 `char` 的简体。opencc 已是既有依赖（`scripts/prepare_corpus.py`
    在用），拿不到就返回 False，不装新东西。"""
    try:
        from opencc import OpenCC
        return OpenCC("t2s").convert(char) == ref and char != ref
    except Exception:
        return False


def _is_confusable(char: str, ref: str) -> bool:
    """T3 形近/通假——`variants.py` 的分级。这类差异最可能是我们认错了字。"""
    try:
        from ..variants import edge_tier
        return edge_tier(char, ref) == "T3"
    except Exception:
        return False


def _slot_char(s: SlotRec) -> str:
    """比对串里这一位出的字。**不退到库/OCR 猜测**（04 卡 §三·1）——
    原型那样做的结果是 vol01 251 条「改」里 221 条是未审位的库 top1 猜测，
    噪声盖过信号；未审位由体检表的「未审阅数」去报。"""
    return s.char or PLACEHOLDER


def diff_page(slots: list[SlotRec], w: Witness, page: int,
              pad: int = WINDOW_PAD) -> PageResult:
    """一页 × 一个证人 → 差异清单 ＋ 列结构裁定。"""
    text_slots = [s for s in slots if s.is_text]
    res = PageResult(page=page, anchored=False, n_slots=len(slots),
                     n_text=len(text_slots),
                     n_excluded=sum(1 for s in slots if s.excluded),
                     n_unreadable=sum(1 for s in slots if s.unreadable))
    if not text_slots:
        res.note = "没有可比对的字位"
        return res

    # 证人里根本没有的段（校勘按语、卷端题、卷末题）**先摘出去再对齐**：
    # 留着它们不但自己全报成差异，还会把整页的锚点带偏（见 report/absent.py）。
    vm0 = _vm()
    res.absent_runs = absent_runs(
        [{"id": s.id, "col": s.col, "sub": s.sub or "", "char": _slot_char(s)}
         for s in text_slots], w.text_norm, vm0.normalize_text)
    if res.absent_runs:
        skip = {i for a in res.absent_runs for i in a["ids"]}
        text_slots = [s for s in text_slots if s.id not in skip]
        if not text_slots:
            res.note = "整页都是证人无此段的内容"
            return res

    text = "".join(_slot_char(s) for s in text_slots)
    offset = anchor_page(text, w.index)
    if offset is None:
        res.note = "8-gram 锚定失败"
        return res
    res.anchored = True

    corpus = w.text
    lo, hi = max(0, offset - pad), min(len(corpus), offset + len(text) + pad)
    window = corpus[lo:hi]

    # 归语义层再对齐；长度变了就退回原字（归一不该改变字数，变了说明有多字映射，
    # 那会让 opcode 的下标对不回字位）
    vm = _vm()
    text_n, window_n = vm.normalize_text(text), vm.normalize_text(window)
    if len(text_n) != len(text) or len(window_n) != len(window):
        text_n, window_n = text, window

    sm = difflib.SequenceMatcher(None, text_n, window_n, autojunk=False)

    def ctx_hyp(i: int, k: int = 5) -> str:
        return text[max(0, i - k):i] + "【" + (text[i] if i < len(text) else "") + "】" + text[i + 1:i + 1 + k]

    def ctx_ref(j: int, k: int = 5, n: int = 1) -> str:
        a = lo + j
        return corpus[max(0, a - k):a] + "【" + corpus[a:a + n] + "】" + corpus[a + n:a + n + k]

    def emit(s: SlotRec, kind: str, ch: str, ref: str, i: int, j: int, n: int = 1) -> None:
        res.diffs.append(Diff(
            id=s.id, page=page, col=s.col, slot=s.slot, sub=s.sub, kind=kind,
            char=ch, ref=ref, witness=w.label, channel=s.channel, admit=s.admit,
            human=s.human, reading=s.reading, n=n,
            hyp_ctx=ctx_hyp(i), ref_ctx=ctx_ref(j, n=n)))

    # 字位 → 它在证人汉字流里的绝对 offset，供列结构比对用
    pos_of: dict[str, int] = {}

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            # 语义层相等 ≠ 字形相等：块内逐字看原字，卽/即 这类要记成异体
            for k in range(i2 - i1):
                s, ref = text_slots[i1 + k], window[j1 + k]
                pos_of[s.id] = lo + j1 + k
                kind = classify(_slot_char(s), s.reading, ref)
                if kind == "same":
                    res.n_equal += 1
                    continue
                emit(s, kind, _slot_char(s), ref, i1 + k, j1 + k)
            continue

        at_head, at_tail = i1 == 0, i2 >= len(text)
        if tag == "insert" and (at_head or i1 >= len(text)):
            continue
        L = min(i2 - i1, j2 - j1) if tag == "replace" else 0
        # 页首的不等长 replace：窗口侧前面那截是余量，等长部分跟窗口段**末尾** L 字配对
        jb = (j2 - L) if at_head else j1

        for k in range(L):
            s = text_slots[i1 + k]
            ref = window[jb + k]
            pos_of[s.id] = lo + jb + k
            if not is_han(ref):
                continue
            kind = classify(_slot_char(s), s.reading, ref)
            if kind == "same":
                res.n_equal += 1
                continue
            emit(s, kind, _slot_char(s), ref, i1 + k, jb + k)

        # 刻本多（text 侧余下的每格一条——图就是证据）
        for k in range(L, i2 - i1):
            s = text_slots[i1 + k]
            emit(s, "unreadable" if _slot_char(s) == PLACEHOLDER else "extra",
                 _slot_char(s), "", i1 + k, min(jb + L, max(len(window) - 1, 0)))

        # 整理本多（window 侧）：一串合成一条，挂到前一个字位上
        if at_head or at_tail:
            continue
        run = "".join(c for c in window[jb + L:j2] if is_han(c))
        if run:
            anchor_i = min(max(i1 + L - 1, 0), len(text_slots) - 1)
            s = text_slots[anchor_i]
            emit(s, "missing", "", run, anchor_i, jb + L, n=len(run))

    if w.line_is_column:
        res.cols = _col_diffs(text_slots, pos_of, w, page)
    return res


def _col_diffs(text_slots: list[SlotRec], pos_of: dict[str, int],
               w: Witness, page: int) -> list[ColDiff]:
    """列结构裁定：每列首字的证人 offset 是否落在行首、列长是否等于行长。

    **独立于 difflib 的增删判断**——只要首字对上了，长度差就是硬信号
    （05 §二：命中行首的 2,867 列里 87.2% 长度相等，不等的主型是我们少一个字）。
    首字没进 `pos_of`（落在被丢弃的 insert/delete 段里）的列跳过，不猜。
    """
    by_col: dict[int, list[SlotRec]] = {}
    for s in text_slots:
        by_col.setdefault(s.col, []).append(s)

    out: list[ColDiff] = []
    for col in sorted(by_col):
        col_slots = by_col[col]
        start = pos_of.get(col_slots[0].id)
        if start is None:
            continue
        kind, delta = col_verdict(start, len(col_slots), w)
        out.append(ColDiff(page=page, col=col, kind=kind, delta=delta, witness=w.label))
    return out


def collate_page(store: ProductStore, book: str, page: int, witnesses: list[Witness],
                 stale: list[str] | None = None) -> dict[str, PageResult]:
    """一页 × 全部证人 → `{证人 label: PageResult}`。"""
    slots = page_slots(store, book, page, stale if stale is not None else [])
    return {w.label: diff_page(slots, w, page) for w in witnesses}


def merge_verdict(per_witness: dict[str, list[Diff]], witnesses: list[Witness]
                  ) -> dict[str, str]:
    """同一字位上多个证人的裁定 → `{id: witness_verdict}`（05 §三 的表）。

    按质量加权，**不是简单多数**：与最好的证人（光盘版）不一致优先怀疑我们错；
    「我们＝杳冥 ≠ 光盘」反而可疑——09-11 前 vol01 是跟着杳冥本选的字。
    """
    if len(witnesses) < 2:
        return {}
    best = witnesses[0].label
    by_id: dict[str, dict[str, Diff]] = {}
    for label, diffs in per_witness.items():
        for d in diffs:
            by_id.setdefault(d.id, {})[label] = d

    out: dict[str, str] = {}
    for cid, m in by_id.items():
        others = [lb for lb in m if lb != best]
        if best in m and others:
            refs = {m[lb].ref for lb in m}
            out[cid] = "all_disagree" if len(refs) > 1 else "witnesses_agree"
        elif best in m:
            out[cid] = "best_only"          # 只有最好的证人有异议
        else:
            out[cid] = "lesser_only"        # 光盘版认同我们，次等证人有异议 → 多半它错
    return out


def to_json(d: Diff | ColDiff) -> dict:
    return asdict(d)
