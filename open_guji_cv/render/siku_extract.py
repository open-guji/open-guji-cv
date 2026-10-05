# -*- coding: utf-8 -*-
"""整册标点层（A4）＋实体层（A5）流水线：`NNN.lines.md` → punct / entity / rich.md。

接 `scripts/test_vol02_extract.py`（只跑 vol02 第 3～15 页、路径写死）的活，
改成可整册跑、可断点续跑的流水线；CLI 在 `scripts/siku_volume_extract.py`。

## 数据流

1. **底本 → 字流 + 坐标**（`parse_lines_md`）：每个"纯字"（夹注字、`[[]]`/`□` 记
   作 `□`）一个 `Slot`，坐标 `页:列:格[子列]`。超框抬头用负格位，`^` 抬一格的
   首字是 −1、第二字直接是 1（**没有第 0 格**——旧脚本会数出 0）。夹注
   `<左|右>` 左行子列 `a`、右行子列 `b`，各自从同一格起数。
2. **分段**：沿用 `reflow_text.reflow`；段落的纯字顺序与第 1 步逐字对账
   （`StreamMap`），对不上的字记入报告、坐标留空，不猜。
3. **LLM 一问两答**：每块（≤`limit` 字，只在小注外切）问一次，同时要标点与专名
   （书名《》、`{人:…}` `{地:…}` `{官:…}` `{朝:…}`），省一半调用。缓存沿用
   `PunctClient` 的 `.punct_cache`，断点续跑即命中缓存。
4. **只插标点、不改字**：做法同 `punct_llm.align_punct`——模型输出剥掉标点/专名
   记号后与送出文本逐字对齐，只取标点与专名边界；改字超过 `max_bad_ratio` 的块
   作废重问一次，仍超就**整块不标点、不出专名**，写进报告。专名区间里只要有一个
   字对不上就丢掉这个专名。
5. **匹配 book-index**：`BookIndexMatcher`；同名多条的不挂（记"同名 N 条待消歧"），
   宁可漏挂不误挂。
6. 产出 `NNN.punct.json` / `NNN.entity.json` / `NNN.rich.md` / `new_candidate` 清单 /
   运行报告。`sample_*` 出抽检核对表，`score_*` 收回人裁后算一致率、误挂率。
"""
from __future__ import annotations

import bisect
import csv
import difflib
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .entity_extract import (
    BookIndexMatcher, EntityAnnotation, apply_entities_and_punctuations_to_markdown, build_entity_json)
from .punct_extract import PunctAnnotation, build_punct_json, tokenize as render_tokenize
from .punct_llm import _OPENERS, _chunks, clean_output, tokenize as llm_tokenize
from .reflow_text import reflow

# ── 1. 底本 → 字流 + 坐标 ───────────────────────────────────────────────

_PAGE = re.compile(r"^<!--\s*p(\d+)\s*-->$")
_PREFIX = re.compile(r"^(\^*)(\.*)")
_UNIT = re.compile(
    r"<(?P<jz>[^<>]*)>"
    r"|:jz\[(?P<dj>[^\]]*)\](?:\{[^}]*\})?"
    r"|(?P<gap>\[\[[^\]]*\]\])"
    r"|(?P<box>□(?:\{[^}]*\})?)"
    r"|(?P<ch>.)", re.S)
_INNER = re.compile(r"(?P<gap>\[\[[^\]]*\]\])|(?P<box>□(?:\{[^}]*\})?)|(?P<ch>.)", re.S)


@dataclass(frozen=True)
class Slot:
    ch: str
    page: int
    col: int
    grid: int
    sub: str = ""          # "" | "a" | "b"

    @property
    def anchor(self) -> str:
        return f"{self.page}:{self.col}:{self.grid}{self.sub}"


def _inner_chars(s: str) -> list[str]:
    out = []
    for m in _INNER.finditer(s):
        if m.group("ch") is not None:
            if not m.group("ch").isspace():
                out.append(m.group("ch"))
        else:
            out.append("□")
    return out


def _next_grid(g: int) -> int:
    return 1 if g == -1 else g + 1


def _advance(g: int, n: int) -> int:
    for _ in range(n):
        g = _next_grid(g)
    return g


def parse_lines_md(text: str, count_blank_columns: bool = False) -> list[Slot]:
    """`NNN.lines.md` → 逐字 `Slot`。

    `count_blank_columns`：空行算不算一列。默认不算（与 vol02 前 15 页那版
    `002.punct.json` 的口径一致）；guji-format 04/05 若规定空列也占列号，改 True。
    """
    slots: list[Slot] = []
    page, col = 0, 0
    for raw in text.splitlines():
        line = raw.strip()
        pm = _PAGE.match(line)
        if pm:
            page, col = int(pm.group(1)), 0
            continue
        if not line:
            if count_blank_columns:
                col += 1
            continue
        col += 1
        mp = _PREFIX.match(line)
        raised, dots = len(mp.group(1)), len(mp.group(2))
        body = line[mp.end():]
        # `^..` 是 Step3 抬头误判（见 reflow_text 模块头），按挪抬算
        g = (dots + 1) if dots else (-raised if raised else 1)
        for u in _UNIT.finditer(body):
            if u.group("jz") is not None:
                left, _, right = u.group("jz").partition("|")
                lc, rc = _inner_chars(left), _inner_chars(right)
                ga = g
                for c in lc:
                    slots.append(Slot(c, page, col, ga, "a"))
                    ga = _next_grid(ga)
                gb = g
                for c in rc:
                    slots.append(Slot(c, page, col, gb, "b"))
                    gb = _next_grid(gb)
                g = _advance(g, max(len(lc), len(rc)))
            elif u.group("dj") is not None:
                for c in _inner_chars(u.group("dj")):
                    slots.append(Slot(c, page, col, g))
                    g = _next_grid(g)
            elif u.group("gap") is not None or u.group("box") is not None:
                slots.append(Slot("□", page, col, g))
                g = _next_grid(g)
            else:
                ch = u.group("ch")
                if ch.isspace():
                    continue
                slots.append(Slot(ch, page, col, g))
                g = _next_grid(g)
    return slots


def to_reflow_md(text: str) -> str:
    """`<!-- pN -->` → reflow 认的 `#第N页`。"""
    return re.sub(r"^\s*<!--\s*p(\d+)\s*-->\s*$", r"#第\1页", text, flags=re.M)


# ── 2. 段落字序 ↔ 底本字流 对账 ───────────────────────────────────────────

def para_tokens(para_text: str) -> list[tuple[str, str]]:
    """段落 → [(原文片段, 给 LLM 的字)]；空白不送、不计字。"""
    return [(o, "" if p.isspace() else p) for o, p in llm_tokenize(para_text)]


def _is_char(p: str) -> bool:
    return p not in ("", "<", ">")


@dataclass
class StreamMap:
    """段落拼接字序（render 下标）→ 底本 `Slot` 下标。"""
    to_slot: list[int | None]
    unmatched: int = 0

    @classmethod
    def build(cls, para_chars: list[str], slots: list[Slot]) -> "StreamMap":
        base = [s.ch for s in slots]
        if para_chars == base:
            return cls(list(range(len(base))))
        sm = difflib.SequenceMatcher(None, para_chars, base, autojunk=False)
        to: list[int | None] = [None] * len(para_chars)
        for tag, i1, i2, j1, _ in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    to[i1 + k] = j1 + k
        return cls(to, sum(1 for t in to if t is None))


# ── 3. LLM 输出解析与对齐 ───────────────────────────────────────────────

SIKU_PROMPT = """请给下面这段《欽定四庫全書總目》原文加现代标点，并标出专名。

要求：
1. 标点用 ，。、；：？！ 以及引号「」『』；不要用省略号、破折号、括号。
2. 书名、篇名用《》包起来，如《子夏易傳》《漢書·藝文志》。
3. 人名写成 {{人:卜子夏}}，地名 {{地:江南}}，官职 {{官:太常博士}}，朝代 {{朝:唐}}。只标有把握的专名，书名不要再套 {{}}。
4. 文中的 < 和 > 是双行小注的起止记号，必须原样保留在原位；小注里面的文字也要加标点、标专名。
5. □ 表示缺字，原样保留，不要猜补。
6. 一个字都不能改：不纠错、不换成简体、不补字、不删字、不调换次序。
7. 只输出处理好的那段文字，不要任何解释，不要换行。

原文：
{text}"""

RETRY_SUFFIX = "\n（上次改动了原文的字，这次请逐字照抄，只加标点和专名记号。）"

TAG_TYPES = {"人": "people", "地": "place", "官": "office", "朝": "dynasty", "书": "work", "書": "work"}
PUNCT_MARKS = set("，。、；：？！「」『』")
# 模型偶尔会用的其它标点：剥掉、不入库（规范里只收上面这套）
DROP_MARKS = set("（）()…—·,.;:?!\"'“”‘’《》{}")
_TAG_OPEN = re.compile(r"\{(人|地|官|朝|书|書)[:：]")


@dataclass
class Parsed:
    stripped: str
    punct_before: dict[int, str]                    # stripped 下标 → 插在该字前的标点
    spans: list[tuple[str, int, int]]               # (type, start, end) 于 stripped


def parse_annotated(out: str) -> Parsed:
    stripped: list[str] = []
    punct: dict[int, str] = {}
    spans: list[tuple[str, int, int]] = []
    work_stack: list[int] = []
    tag_stack: list[tuple[str, int]] = []
    i = 0
    while i < len(out):
        c = out[i]
        m = _TAG_OPEN.match(out, i)
        if m:
            tag_stack.append((TAG_TYPES[m.group(1)], len(stripped)))
            i = m.end()
            continue
        if c == "}":
            if tag_stack:
                t, s = tag_stack.pop()
                if len(stripped) > s:
                    spans.append((t, s, len(stripped)))
        elif c == "《":
            work_stack.append(len(stripped))
        elif c == "》":
            if work_stack:
                s = work_stack.pop()
                if len(stripped) > s:
                    spans.append(("work", s, len(stripped)))
        elif c in PUNCT_MARKS:
            punct[len(stripped)] = punct.get(len(stripped), "") + c
        elif c in DROP_MARKS or c.isspace():
            pass
        else:
            stripped.append(c)
        i += 1
    return Parsed("".join(stripped), punct, sorted(spans, key=lambda x: (x[1], -x[2])))


@dataclass
class ChunkResult:
    ok: bool
    bad: int
    n: int
    punct: dict[int, str]                           # chunk plain 下标 → 插在该位置前
    spans: list[tuple[str, int, int]]               # chunk plain 下标区间
    note: str = ""
    subs: list[tuple[int, str, str]] = field(default_factory=list)   # (plain 下标, 底本字, 模型字)


def align_chunk(plain: str, out: str
                ) -> tuple[dict[int, str], list[tuple[str, int, int]], int, list[tuple[int, str, str]]]:
    """模型输出 → (标点 {plain 下标: 插在其前}, 专名 [(type, s, e)], 增删的字数, 等长换字)。

    等长换字（没→沒、日→曰）不挪位置，标点照样落得准，单算、不计入增删；
    原文仍一字不动，换字记进报告供底本定字参考。增删（模型补出整条小注）才是要作废的。
    """
    p = parse_annotated(clean_output(out))
    sm = difflib.SequenceMatcher(None, plain, p.stripped, autojunk=False)
    qmap: dict[int, int] = {}
    bad = 0
    subs: list[tuple[int, str, str]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1
                              and all(_is_char(plain[i]) for i in range(i1, i2))):
            for k in range(i2 - i1):
                qmap[j1 + k] = i1 + k
            if tag == "replace":
                subs += [(i1 + k, plain[i1 + k], p.stripped[j1 + k]) for k in range(i2 - i1)]
        else:
            bad += max(i2 - i1, j2 - j1)
    keys = sorted(qmap)

    def fwd(q: int) -> int:
        k = bisect.bisect_left(keys, q)
        return qmap[keys[k]] if k < len(keys) else len(plain)

    punct: dict[int, str] = {}
    for q, mark in p.punct_before.items():
        t = fwd(q)
        punct[t] = punct.get(t, "") + mark
    spans: list[tuple[str, int, int]] = []
    for typ, s, e in p.spans:
        if all(q in qmap for q in range(s, e)) and qmap[e - 1] - qmap[s] == e - 1 - s:
            spans.append((typ, qmap[s], qmap[e - 1] + 1))
    return punct, spans, bad, subs


class Asker(Protocol):
    def ask(self, user: str) -> str: ...


def run_chunk(plain: str, client: Asker, max_bad_ratio: float = 0.02,
              prompt: str = SIKU_PROMPT, max_sub_ratio: float = 0.05) -> ChunkResult:
    user = prompt.format(text=plain)
    best: tuple[dict[int, str], list, int, list] | None = None

    def ok(r) -> bool:
        return r[2] <= max_bad_ratio * len(plain) and len(r[3]) <= max(1, max_sub_ratio * len(plain))

    err = ""
    for attempt in range(2):
        try:
            out = client.ask(user if attempt == 0 else user + RETRY_SUFFIX)
        except Exception as e:                                   # noqa: BLE001 — 记入报告，不中断整册
            err = f"LLM 调用失败：{e}"
            continue
        res = align_chunk(plain, out)
        if best is None or (ok(res), -res[2], -len(res[3])) > (ok(best), -best[2], -len(best[3])):
            best = res
        if ok(res):
            break
    n = sum(1 for c in plain if _is_char(c))
    if best is None:
        return ChunkResult(False, len(plain), n, {}, [], err)
    punct, spans, bad, subs = best
    if not ok(best):
        return ChunkResult(False, bad + len(subs), n, {}, [],
                           f"LLM 增删 {bad}、换字 {len(subs)}/{len(plain)}，本块不标点")
    return ChunkResult(True, bad, n, punct, spans, subs=subs)


# ── 4. 整册 ─────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    para: int
    plain: str                       # 送给 LLM 的串（含 < >）
    render_idx: list[int | None]     # plain 每个位置 → render 下标（< > 为 None）
    para_end: bool = True            # 本块是否到段尾（不到段尾的块，块尾标点不收）


@dataclass
class VolumeResult:
    puncts: list[PunctAnnotation]
    entities: list[EntityAnnotation]
    rich_md: str
    render_chars: list[str]
    anchors: list[str | None]        # render 下标 → 坐标
    report: dict[str, Any]


def build_chunks(paras_text: list[str], limit: int) -> tuple[list[Chunk], list[str], list[int]]:
    """段落 → 块；同时给出段落拼接字序与每段末字的 render 下标。"""
    chunks: list[Chunk] = []
    render_chars: list[str] = []
    para_last: list[int] = []
    for pi, text in enumerate(paras_text):
        toks = para_tokens(text)
        idx_map: list[int | None] = []
        for _, p in toks:
            if _is_char(p):
                idx_map.append(len(render_chars))
                render_chars.append(p)
            else:
                idx_map.append(None)
        para_last.append(len(render_chars) - 1)
        spans = _chunks(toks, limit)
        for a, b in spans:
            sub = [(o, p) for o, p in toks[a:b]]
            plain = "".join(p for _, p in sub)
            if not any(_is_char(p) for _, p in sub):
                continue
            ridx = [idx_map[a + k] for k, (_, p) in enumerate(sub) if p]
            rest = any(_is_char(p) for _, p in toks[b:])
            chunks.append(Chunk(pi, plain, ridx, para_end=not rest))
    return chunks, render_chars, para_last


def _chunk_to_render(ch: Chunk, cr: ChunkResult) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, int]]]:
    """块内结果 → render 下标。标点：收尾类挂前一个字之后、起首类挂后一个字之前。"""
    n = len(ch.plain)
    prev_char: list[int | None] = [None] * (n + 1)      # 位置 t 之前最近的字
    last = None
    for t in range(n):
        prev_char[t] = last
        if ch.render_idx[t] is not None:
            last = ch.render_idx[t]
    prev_char[n] = last
    next_char: list[int | None] = [None] * (n + 1)
    nxt = None
    for t in range(n, -1, -1):
        if t < n and ch.render_idx[t] is not None:
            nxt = ch.render_idx[t]
        next_char[t] = nxt
    # 块在句中被切开时，模型总会在块尾补个句号——那不是它的判断，是截断。不收。
    last_t = max((t for t in range(n) if ch.render_idx[t] is not None), default=-1)
    pts: list[tuple[str, int, str]] = []
    for t, marks in sorted(cr.punct.items()):
        if not ch.para_end and t > last_t:
            continue
        for c in marks:
            if c in _OPENERS or c in "「『":
                if next_char[t] is not None:
                    pts.append((c, next_char[t], "before"))
            elif prev_char[t] is not None:
                pts.append((c, prev_char[t], "after"))
    ents: list[tuple[str, int, int]] = []
    for typ, s, e in cr.spans:
        idx = [ch.render_idx[t] for t in range(s, e) if ch.render_idx[t] is not None]
        if idx:
            ents.append((typ, idx[0], idx[-1] + 1))
    return pts, ents


#: 提要里冠在人名前的朝代（「漢鄭玄注」「魏王弼撰」）。模型常只标人名不标朝代，
#: 所以除了看前一个 {朝:…} 专名，也直接看名字前面的一两个字。
DYNASTIES = ("後漢", "東漢", "西漢", "前漢", "北魏", "後魏", "東晉", "西晉", "南唐", "後唐", "北齊",
             "後周", "北周", "南宋", "北宋", "三國", "五代", "蜀漢",
             "周", "秦", "漢", "魏", "晉", "宋", "齊", "梁", "陳", "隋", "唐", "遼", "金", "元", "明", "吳", "蜀")


def dynasty_before(chars: list[str], s: int, prev: EntityAnnotation | None) -> str | None:
    if prev is not None and prev.type == "dynasty" and prev.end_offset == s:
        return prev.text
    for d in DYNASTIES:                                 # 两字的排在前面，先试
        if s >= len(d) and "".join(chars[s - len(d):s]) == d:
            return d[-1] if d[0] in "後東西前北南" and len(d) == 2 else d
    return None


CONTEXT_BEFORE = 8
CONTEXT_NEXT_HEAD = 30


def name_before(chars: list[str], s: int, prev: EntityAnnotation | None,
                matcher: BookIndexMatcher) -> tuple[str, None] | None:
    """书名前紧挨着、模型没标出来的人名（「焦竑經籍志」「劉克莊後山集」）：前 3/2 字是
    book-index 里的人名就当撰人线索。不跨进前一个专名。"""
    floor = prev.end_offset if prev is not None else 0
    for n in (3, 2):
        if s - n >= floor:
            name = "".join(chars[s - n:s])
            if matcher.ids_by_name.get(("people", name)):
                return (name, None)
    return None


def run_volume(lines_md: str, client: Asker, matcher: BookIndexMatcher | None, *,
               limit: int = 300, workers: int = 4, max_bad_ratio: float = 0.02,
               source: str = "llm", count_blank_columns: bool = False,
               progress: Callable[[int, int], None] | None = None) -> VolumeResult:
    slots = parse_lines_md(lines_md, count_blank_columns)
    paras, rstats = reflow(to_reflow_md(lines_md), "default")
    paras_text = [p.text for p in paras]
    chunks, render_chars, para_last = build_chunks(paras_text, limit)
    smap = StreamMap.build(render_chars, slots)
    anchors = [slots[j].anchor if j is not None else None for j in smap.to_slot]

    done = [0]

    def work(ch: Chunk) -> ChunkResult:
        r = run_chunk(ch.plain, client, max_bad_ratio)
        done[0] += 1
        if progress:
            progress(done[0], len(chunks))
        return r

    with ThreadPoolExecutor(max(1, workers)) as ex:
        results = list(ex.map(work, chunks))

    puncts: list[PunctAnnotation] = []
    raw_ents: list[tuple[str, int, int]] = []
    failed: list[dict[str, Any]] = []
    substitutions: list[dict[str, Any]] = []
    for ch, cr in zip(chunks, results):
        if not cr.ok:
            first = next((i for i in ch.render_idx if i is not None), None)
            failed.append({"para": ch.para, "anchor": anchors[first] if first is not None else None,
                           "chars": cr.n, "bad": cr.bad, "note": cr.note, "head": ch.plain[:20]})
            continue
        pts, ents = _chunk_to_render(ch, cr)
        for t, a, b in cr.subs:
            ri = ch.render_idx[t]
            substitutions.append({"anchor": anchors[ri] if ri is not None else None, "base": a, "model": b,
                                  "context": context(render_chars, ri, ri + 1, 8) if ri is not None else ""})
        for mark, ri, pos in pts:
            puncts.append(PunctAnnotation(mark=mark, kind="point", pos=pos, char_offset=ri,
                                          pre_char=render_chars[ri], anchor=anchors[ri], source=source))
        raw_ents.extend(ents)
    for pi, ri in enumerate(para_last[:-1]):
        if ri >= 0 and (pi == 0 or para_last[pi - 1] != ri):
            puncts.append(PunctAnnotation(mark="\n\n", kind="break", pos="after", char_offset=ri,
                                          pre_char=render_chars[ri], anchor=anchors[ri], source="rule:reflow"))
    puncts.sort(key=lambda a: (a.char_offset, a.pos != "before", a.kind == "break"))

    entities: list[EntityAnnotation] = []
    taken: set[int] = set()
    for typ, s, e in sorted(set(raw_ents), key=lambda x: (x[1], -x[2])):
        if any(k in taken for k in range(s, e)):           # 嵌套/重叠的只留外层
            continue
        taken.update(range(s, e))
        text = "".join(render_chars[s:e])
        prev = entities[-1] if entities else None
        hint = dynasty_before(render_chars, s, prev)
        author = ((prev.text, prev.target_id) if typ == "work" and prev is not None
                  and prev.type == "people" and prev.end_offset == s else None)
        if typ == "work" and author is None and matcher is not None:
            author = name_before(render_chars, s, prev, matcher)
        # 书名近旁：前 8 字（「蘇洵作易傳」「王與之周禮訂義」）；书名打头的段（提要书名行
        # 自成一段）再加下一段开头 30 字（撰人「宋沈該撰」在那里）
        pi = bisect.bisect_left(para_last, s)
        p_start = para_last[pi - 1] + 1 if pi else 0
        ctx = "".join(render_chars[max(p_start, s - CONTEXT_BEFORE):s])
        if s == p_start and pi + 1 < len(para_last):
            ctx += "|" + "".join(render_chars[para_last[pi] + 1:para_last[pi] + 1 + CONTEXT_NEXT_HEAD])
        tgt = (matcher.match(typ, text, dynasty_hint=hint, author_hint=author, context=ctx) if matcher
               else {"status": "new_candidate", "canonical_name": text})
        entities.append(EntityAnnotation(
            id=f"e{len(entities) + 1:05d}", type=typ, text=text,
            anchor_start=anchors[s] or "", anchor_end=anchors[e - 1] or "",
            start_offset=s, end_offset=e,
            target_status=tgt.get("status", "new_candidate"), target_id=tgt.get("entity_id"),
            target_name=tgt.get("canonical_name", text), target_href=tgt.get("href"),
            note=tgt.get("note"), source=source))

    tokens = []
    for pi, text in enumerate(paras_text):
        tokens.extend(render_tokenize(re.sub(r"\x00p(\d+)\x00", r"<!-- p\1 -->", text)))
    rich = apply_entities_and_punctuations_to_markdown(tokens, puncts, entities, include_breaks=True)

    n_chars = len(render_chars)
    failed_chars = sum(f["chars"] for f in failed)
    report = {
        "chars": n_chars, "slots": len(slots), "unmatched_chars": smap.unmatched,
        "paragraphs": len(paras), "chunks": len(chunks), "chunks_failed": len(failed),
        "chars_unpunctuated": failed_chars,
        "points": sum(1 for p in puncts if p.kind == "point"),
        "breaks": sum(1 for p in puncts if p.kind == "break"),
        "entities": len(entities),
        "matched": sum(1 for e in entities if e.target_status == "matched"),
        "new_candidate": sum(1 for e in entities if e.target_status == "new_candidate"),
        "by_type": {t: sum(1 for e in entities if e.type == t) for t in sorted({e.type for e in entities})},
        "reflow": {k: v for k, v in rstats.items() if isinstance(v, (int, str, list))},
        "model_substitutions": len(substitutions),
        "failed": failed,
        # 模型想换的字：原文没动，列出来给底本定字（A3）参考，日→曰 这类可能是底本错
        "substitutions": substitutions,
    }
    return VolumeResult(puncts, entities, rich, render_chars, anchors, report)


# ── 5. 写盘 ─────────────────────────────────────────────────────────────

def write_outputs(res: VolumeResult, out_dir: Path, vol: int, *, book_id: str, title: str,
                  creator: str) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{vol:03d}"
    pj = build_punct_json(book_id, title, res.puncts, creator=creator)
    pj["volume"] = vol
    ej = build_entity_json(book_id, title, vol, res.entities, creator=creator)
    paths = {
        "punct": out_dir / f"{stem}.punct.json",
        "entity": out_dir / f"{stem}.entity.json",
        "rich": out_dir / f"{stem}.rich.md",
        "candidates": out_dir / f"{stem}.new_candidates.tsv",
        "report": out_dir / f"{stem}.extract_report.json",
    }
    paths["punct"].write_text(json.dumps(pj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["entity"].write_text(json.dumps(ej, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["rich"].write_text(res.rich_md + "\n", encoding="utf-8")
    write_candidates_tsv(res, paths["candidates"])
    paths["report"].write_text(json.dumps(res.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return paths


def context(chars: list[str], s: int, e: int, width: int = 12) -> str:
    return "".join(chars[max(0, s - width):s]) + "【" + "".join(chars[s:e]) + "】" + "".join(chars[e:e + width])


_SUGGEST = {
    "people": "book-index 无此人，建 Entity(people)；可借 CBDB 消歧",
    "work": "book-index 无此书，建 Work",
    "place": "地名，book-index 暂无地名库，先登记",
    "office": "官职，非建档对象，可不建",
    "dynasty": "朝代，非建档对象，可不建",
}


def write_candidates_tsv(res: VolumeResult, path: Path) -> int:
    """`new_candidate` 按 (类型, 名称) 去重；出处坐标给首见处，另列出现次数与其余坐标（≤5）。"""
    groups: dict[tuple[str, str], list[EntityAnnotation]] = {}
    for e in res.entities:
        if e.target_status == "new_candidate":
            groups.setdefault((e.type, e.text), []).append(e)
    order = ["work", "people", "place", "office", "dynasty"]
    rows = sorted(groups.items(), key=lambda kv: (order.index(kv[0][0]) if kv[0][0] in order else 9,
                                                  -len(kv[1]), kv[1][0].start_offset))
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["类型", "名称", "出处坐标", "上下文", "建议", "次数", "其余坐标"])
        for (typ, name), es in rows:
            e0 = es[0]
            sug = e0.note or _SUGGEST.get(typ, "")
            w.writerow([typ, name, e0.anchor_start, context(res.render_chars, e0.start_offset, e0.end_offset),
                        sug, len(es), " ".join(x.anchor_start for x in es[1:6])])
    return len(rows)


# ── 6. 抽检 ─────────────────────────────────────────────────────────────

def load_render_chars(lines_md: str) -> tuple[list[str], list[str | None]]:
    """不调 LLM，只重建 render 字序与坐标（抽检用）。"""
    slots = parse_lines_md(lines_md)
    paras, _ = reflow(to_reflow_md(lines_md), "default")
    _, chars, _ = build_chunks([p.text for p in paras], 10 ** 9)
    smap = StreamMap.build(chars, slots)
    return chars, [slots[j].anchor if j is not None else None for j in smap.to_slot]


def sample_punct(punct_json: dict, chars: list[str], n: int = 200, seed: int = 0) -> list[dict[str, Any]]:
    pts = [p for p in punct_json["punctuations"] if p["kind"] == "point"]
    rng = random.Random(seed)
    pick = sorted(rng.sample(range(len(pts)), min(n, len(pts))), key=lambda i: pts[i]["char_offset"])
    rows = []
    for k, i in enumerate(pick, 1):
        p = pts[i]
        o = p["char_offset"]
        if p["pos"] == "after":
            ctx = "".join(chars[max(0, o - 14):o + 1]) + "【" + p["mark"] + "】" + "".join(chars[o + 1:o + 15])
        else:
            ctx = "".join(chars[max(0, o - 14):o]) + "【" + p["mark"] + "】" + "".join(chars[o:o + 15])
        page = (p.get("anchor") or "").split(":")[0]
        rows.append({"序号": k, "坐标": p.get("anchor", ""), "书影页": page, "标点": p["mark"],
                     "上下文": ctx, "判定(对/错/多余)": "", "应为": "", "备注": ""})
    return rows


def sample_entities(entity_json: dict, chars: list[str], matcher: BookIndexMatcher | None,
                    n: int = 50, seed: int = 0) -> list[dict[str, Any]]:
    ents = [e for e in entity_json["entities"] if e["target"]["status"] == "matched"]
    rng = random.Random(seed)
    pick = sorted(rng.sample(range(len(ents)), min(n, len(ents))), key=lambda i: ents[i]["span"]["start_offset"])
    rows = []
    for k, i in enumerate(pick, 1):
        e = ents[i]
        s, t = e["span"]["start_offset"], e["span"]["end_offset"]
        tid = e["target"].get("entity_id", "")
        info = matcher.describe(tid) if matcher else ""
        rows.append({"序号": k, "坐标": e["anchor"]["start"], "书影页": e["anchor"]["start"].split(":")[0],
                     "类型": e["type"], "原文": e["text"], "上下文": context(chars, s, t, 15),
                     "挂到": tid, "条目": e["target"].get("canonical_name", ""), "条目信息": info,
                     "判定(对/误挂/非专名/类型错)": "", "备注": ""})
    return rows


def write_tsv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def score_tsv(path: Path) -> dict[str, Any]:
    """收回人裁后的核对表：标点表算一致率，实体表算正确率与误挂率。没裁的行不计。"""
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    col = next((c for c in (rows[0] if rows else {}) if c.startswith("判定")), None)
    verdicts = [r[col].strip() for r in rows if col and r.get(col, "").strip()]
    n = len(verdicts)
    out: dict[str, Any] = {"rows": len(rows), "judged": n}
    if not n:
        return out
    out["ok_rate"] = round(sum(v == "对" for v in verdicts) / n, 4)
    if "误挂" in (col or ""):
        out["mislink_rate"] = round(sum(v == "误挂" for v in verdicts) / n, 4)
    from collections import Counter
    out["verdicts"] = dict(Counter(verdicts))
    return out
