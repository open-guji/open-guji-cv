# -*- coding: utf-8 -*-
"""Step9 结果整理 · 9.2' 文本版分段：只吃 9.1 分行 md，输出自然段（不查任何产物）。

## 为什么要有这一版（对比 `reading_layout.py`）

`reading_layout.py` 判"这一列排没排满"要回查 Step3 `n_body_slots` 与 Step7
`seed_admit`——那是**工作区里的中间产物**，书整完就删（guji-workspace README：
「整完即删」），book-text 里只剩 md；md 还可能被手改过。而 9.1 md 里其实已经
带着排满与否所需的全部信息：

    一列的"占位数"（extent） = 行首挪抬数 − 抬头数 + 本列字位数

字位数在夹注上要换算：`<a|b>`（双行夹注）占 max(len a, len b) 格，不是
len a + len b；`[[]]`、`□{..}` 各占 1 格；单行小注 `:jz[x]{type=单行}` 占 len x。
实测两册（bxgb、四库总目 vol03）整册 md：排满的列占位数集中在 1~3 个值上
（bxgb 只有 21；vol03 为 19/20/21），其余是短列（段末、标题、条目尾）。

## 规则（v0）

1. **列未排满 → 这一列是段尾**，下一列另起一段。"排满"= 占位数 ∈ FULL 集合。
   FULL 集合默认从整册占位数直方图自动找（占比 ≥ `peak_ratio` 的值，且 ≥ 本册最大
   众数 − 2），也可由调用方用 `full=` 显式给。
2. 版心／空列（空行）不分段；页界（`#第N页`）不分段，只插页码标记。
3. 行首抬头 `^` 且没有后随挪抬 `.`（真抬头：另起一行、高出版心）→ 在它**前面**也分段。
4. 夹注 `<a|b>` 去掉 `|`；同一页内相邻的两条夹注（上一列尾 + 下一列头，实为一条
   跨列夹注）合并成一条。

## 不确定点（写进 `Para.notes`，交给 LLM/人复核）

- 占位数 = FULL 最小值 − 1 的"差一格"列：多半是 Step3 把一个排除格（切坏/墨污）
  丢了，而不是真的段尾。**不自动断也不自动连**——默认按"没排满"断，并记 note。
- 同一列既有 `^` 又有 `.`（Step3 抬头误判，vol03 常见）：按挪抬处理，`^` 忽略。
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field

_PAGE = re.compile(r"^#第(\d+)页\s*$")
_PREFIX = re.compile(r"^(\^*)(\.*)")
# 一个字位单元：夹注 / 指令式单行小注 / 阙文 / 原刻残 / 单字
_UNIT = re.compile(
    r"<(?P<jz>[^<>]*)>"
    r"|:jz\[(?P<dj>[^\]]*)\](?:\{[^}]*\})?"
    r"|(?P<gap>\[\[[^\]]*\]\])"
    r"|(?P<box>□(?:\{[^}]*\})?)"
    r"|(?P<ch>.)", re.S)
_JZ_ADJ = re.compile(r"<([^<>]*)><([^<>]*)>")


@dataclass
class Line:
    page: int
    idx: int            # 页内第几列（含空行，从 1 起）
    raised: int
    kg: int
    body: str           # 去掉 ^ . 前缀后的 9.1 文本
    slots: int          # 本列字位数（夹注已换算）

    @property
    def blank(self) -> bool:
        return self.body == ""

    @property
    def eff(self) -> int:
        """开头点数：`.` 为正、`^` 为负，同一数轴。真抬头（无挪抬）才算负。"""
        return self.kg if self.kg else -self.raised

    @property
    def extent(self) -> int:
        return self.eff + self.slots

    @property
    def true_raised(self) -> bool:
        """真抬头：有 `^` 且没有 `.`。`^..` 是 Step3 误判（见模块头）。"""
        return self.raised > 0 and self.kg == 0


def count_slots(body: str) -> int:
    n = 0
    for m in _UNIT.finditer(body):
        if m.group("jz") is not None:
            a, _, b = m.group("jz").partition("|")
            n += max(len(a.replace("[[]]", "x")), len(b.replace("[[]]", "x")))
        elif m.group("dj") is not None:
            n += len(m.group("dj").replace("[[]]", "x"))
        else:
            n += 1
    return n


def parse_md(md: str) -> list[Line]:
    out: list[Line] = []
    page, idx = 0, 0
    for raw in md.splitlines():
        m = _PAGE.match(raw)
        if m:
            page, idx = int(m.group(1)), 0
            continue
        idx += 1
        if raw.strip() == "":
            out.append(Line(page, idx, 0, 0, "", 0))
            continue
        p = _PREFIX.match(raw)
        body = raw[p.end():].rstrip()
        out.append(Line(page, idx, len(p.group(1)), len(p.group(2)), body, count_slots(body)))
    return out


def infer_full(lines: list[Line], peak_ratio: float = 0.03) -> tuple[set[int], set[int]]:
    """从整册字位数和占位数直方图分别找"排满"的集合：(full_slots, full_extents)。"""
    h_ext = collections.Counter(l.extent for l in lines if not l.blank)
    h_slot = collections.Counter(l.slots for l in lines if not l.blank)
    tot = sum(h_ext.values())
    if not tot:
        return set(), set()
    m_ext = max(h_ext, key=lambda e: (h_ext[e], e))
    p_ext = {e for e, c in h_ext.items() if c / tot >= peak_ratio and e >= m_ext - 2} | {m_ext}
    m_slot = max(h_slot, key=lambda s: (h_slot[s], s))
    p_slot = {s for s, c in h_slot.items() if c / tot >= peak_ratio and s >= m_slot - 2} | {m_slot}
    return p_slot, p_ext


@dataclass
class Para:
    text: str                       # 9.1 记号保留的自然段文本（页码标记用 `\x00p{N}\x00` 占位）
    pages: tuple[int, int]
    kind: str = "body"              # body | title
    notes: list[str] = field(default_factory=list)


PAGE_MARK = "\x00p{}\x00"


def _clean_body(body: str) -> str:
    """`<a|b>` → `<ab>`（横排不需要转行位置）。"""
    return re.sub(r"<([^<>|]*)\|([^<>]*)>", lambda m: "<" + m.group(1) + m.group(2) + ">", body)


def segment(lines: list[Line], full: set[int] | tuple[set[int], set[int]] | None = None) -> tuple[list[Para], dict]:
    if full is None:
        full_slots, full_ext = infer_full(lines)
    elif isinstance(full, tuple):
        full_slots, full_ext = full
    else:
        full_slots, full_ext = full, full

    near = (min(full_ext) - 1) if full_ext else None

    paras: list[Para] = []
    cur: list[str] = []
    cur_pages: list[int] = []
    cur_notes: list[str] = []
    cur_page_seen: int | None = None
    stats = collections.Counter()

    def flush() -> None:
        nonlocal cur, cur_pages, cur_notes
        if cur:
            text = "".join(cur)
            # 同一页内，上一列尾夹注 + 下一列头夹注 = 一条跨列夹注，合并
            prev = None
            while prev != text:
                prev = text
                text = _JZ_ADJ.sub(lambda m: "<" + m.group(1) + m.group(2) + ">", text)
            paras.append(Para(text, (cur_pages[0], cur_pages[-1]), "body", cur_notes))
        cur, cur_pages, cur_notes = [], [], []

    prev_full: bool | None = None   # 上一条非空列是否排满
    prev_line: Line | None = None
    for ln in lines:
        if ln.blank:
            continue
        # 真抬头另起一段
        if ln.true_raised and cur:
            flush()
            stats["break_raised"] += 1
        elif prev_full is False and cur:
            flush()
            stats["break_short"] += 1
            if prev_line is not None and prev_line.extent == near:
                paras[-1].notes.append(
                    f"p{prev_line.page}c{prev_line.idx}: 占位 {prev_line.extent}=满列−1，"
                    f"疑似丢格（排除格）而非段尾：「…{prev_line.body[-6:]}」→「{ln.body[:6]}…」")
                stats["near_full_break"] += 1
        if ln.page != cur_page_seen:
            cur.append(PAGE_MARK.format(ln.page))
            cur_page_seen = ln.page
        if not cur_pages or cur_pages[-1] != ln.page:
            cur_pages.append(ln.page)
        cur.append(_clean_body(ln.body))
        prev_full = (ln.slots in full_slots) or (ln.extent in full_ext)
        prev_line = ln
    flush()
    stats["paragraphs"] = len(paras)
    stats["lines"] = sum(1 for l in lines if not l.blank)
    return paras, {"full_slots": sorted(full_slots), "full_extents": sorted(full_ext), **stats}


# ── 书级 profile：分段规则里"这本书特有"的那部分 ─────────────────────────────
# 通用规则（排满判据）管不到的：段首并不落在列首（如日记体，同一列中间换了一天）。
# profile 只放**可机械判定**的正则；判不准的交给 LLM（见 `punct_llm.py`）。

#: 日记体条目起首：「（十一月）二十九日辛亥」——（月）日 + 干支。
_DIARY_DATE = (r"(?:[閏闰]?[正二三四五六七八九十]{1,2}月)?[初]?[一二三四五六七八九十]{1,3}日"
               r"[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]")

PROFILES: dict[str, dict] = {
    "default": {},
    "diary": {"split_before": _DIARY_DATE},
}

_MARK = re.compile(r"\x00p(\d+)\x00")
_ONLY_MARKS = re.compile(r"(?:\x00p\d+\x00)*")


def split_paragraphs_by_regex(paras: list[Para], pattern: str) -> list[Para]:
    """在 `pattern` 命中处（非段首）把一段切成两段；页码标记留在它原来的位置，
    命中恰好紧跟页码标记时，切在标记**之前**（标记跟着后一段走）。"""
    rx = re.compile(pattern)
    out: list[Para] = []
    for p in paras:
        cuts: list[int] = []
        for m in rx.finditer(p.text):
            pos = m.start()
            while True:                              # 往前吃掉紧邻的页码标记
                mk = re.search(r"\x00p\d+\x00$", p.text[:pos])
                if not mk:
                    break
                pos = mk.start()
            if pos > 0 and not _ONLY_MARKS.fullmatch(p.text[:pos]) and (not cuts or cuts[-1] != pos):
                cuts.append(pos)
        if not cuts:
            out.append(p)
            continue
        bounds = [0] + cuts + [len(p.text)]
        page = p.pages[0]
        for a, b in zip(bounds, bounds[1:]):
            seg = p.text[a:b]
            marks = [int(x) for x in _MARK.findall(seg)]
            start = marks[0] if seg.startswith("\x00p") else page
            end = marks[-1] if marks else page
            page = end
            out.append(Para(seg, (start, end), p.kind, list(p.notes) if a == 0 else []))
    return out


def reflow(md: str, profile: str = "default", full: set[int] | None = None) -> tuple[list[Para], dict]:
    """9.1 md → 自然段（未标点）。"""
    lines = parse_md(md)
    paras, stats = segment(lines, full)
    sb = PROFILES[profile].get("split_before")
    if sb:
        before = len(paras)
        paras = split_paragraphs_by_regex(paras, sb)
        stats["profile_splits"] = len(paras) - before
        stats["paragraphs"] = len(paras)
    stats["profile"] = profile
    return paras, stats
