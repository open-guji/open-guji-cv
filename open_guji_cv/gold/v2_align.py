"""v2 产物 × 整理本 → 自动金标。

九步跑完之后手上只有**覆盖率**（same 多少、定字多少），没有**准确率**——
1359 个 same 里有几个是对的，不量就不知道。这个模块用整理本给大部分字位
自动落金标，把人工从「逐字标 1933 条」降到「裁几百条难例」。

## 怎么锚

复用 `clustering/align_label.label_page`：定字串 → 8-gram 锚到整理本 →
`difflib` 对齐 → **采信闸**（`equal` 段全收；等长 `replace` 段要求段长 ≤3
且左右各有 ≥2 字的 `equal` 段贴身夹住）。闸是 G5 那边踩出来的，漏进来的
错标（卷→曰、己→已）全是长 replace 段或没被夹住的，不能松。

## ⚠️ 两条纪律

1. **金标只取「算法本来就对」的位置 = 自证**。`equal` 段恒等于当次转写，
   只收它测出来必然 100%。等长 `replace` 段才是错误样本，必须一起收——
   `align_op` 字段留着，评测时**分层读**。
2. **LM 语料就是整理本，金标也从它来**。评测 Step6 时必须把测试页的窗口
   从 LM 语料里挖掉（前后各多挖 200 字）并**打印挖了多少字**；打印为 0
   就是挖漏了，后面的数字一概作废。这个模块只产金标，挖洞是评测脚本的事，
   纪律记在这里免得忘。

## 字形 / 释读分开记（用户 2026-09-04 定）

「碰到已/巳、人/入 这类，先读字形，但是文本录入要按文意录（最好能记录
这个转换）」。所以每条金标带两个字段：

- `shape`：刻本上实际刻的形（v2 定字给的，字形层照录）；
- `reading`：文意上该读什么（整理本给的）。

两者不同就是一次**转换**，`conversion=True`。这跟 `GlyphDB.admit_instance`
的 `shape` / `char` 分岔是同一件事（charset_and_lm.md §四）：字形库存前者，
文本录入用后者，两条线不许互相污染。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..utils.jiazhu_order import sort_by_reading

DEFAULT_CORPUS = "corpus/zongmu_wuyingdian_reference.txt"


@dataclass
class GoldChar:
    """一个字位的自动金标。"""
    id: str                       # book:page:col:slot[a|b]
    page: int
    col: int
    slot: int
    shape: str                    # 刻本字形（v2 定的）
    reading: str                  # 文意读法（整理本给的）
    align_op: str                 # equal | replace —— 分层读，别混着算
    op_run: int = 1               # 所在对齐段长度，越长越可疑
    conversion: bool = False      # shape != reading，一次字形→文意的转换
    source: str = ""              # v2 定字来源：db_same | context | prior
    sub: str | None = None        # 夹注半格的 a/b，正文格 None（2026-09-06）


@dataclass
class PageGold:
    book: str
    page: int
    anchored: bool
    n_chars: int = 0
    n_conversion: int = 0
    chars: list[GoldChar] = field(default_factory=list)
    note: str = ""


def _slots_from_decision(dec, match=None, ocr=None
                        ) -> tuple[list[tuple[int, int, str]], dict]:
    """Step6 的 `context_decision` → `label_page` 要的 slots + 溯源表。

    ## 弃权位要用库/OCR 兜底填上，不能跳过（2026-09-04 改）

    原先只收**定了字**的位。理由当时是「弃权位没有假设可对齐」，但这恰好
    弄反了 `difflib` 的工作方式：对齐要的是一条**位位对应**的串，跳过一个
    位不会「留空」，而是把后面的字全部前移一格——弃权越多，错位越狠。

    实测代价极大：**p70 整页锚不上**（132 位只定出 72 个），而那页的文字
    在整理本里明明有（「繭紙朱題芸帙之名蟠屈鸞章」）。它是生僻字密集页，
    库里没样本、OCR 字表也不够，于是定字最少、最需要整理本帮忙的那些页，
    反而是最锚不上的——正好把整理本这路证据挡在了最该用它的地方。

    改成逐级兜底：**定字 → 库 kNN top1 → OCR top1**。兜底字只是**对齐载体**
    （`AlignedLabel.hyp`），金标取的是整理本给的 `char`，所以兜底字错了也
    不会污染金标，最多让那一位落进 `replace` 段（本来就该分层读）。

    实测 vol01 dev_set：锚上的金标 **1619 → 1897 / 1933**（83.8% → 98.1%），
    p70 从 0 → 115。

    `match` / `ocr` 传 None 时退回旧行为（只收定字位）。
    """
    mmap = {r.id: r for cc in (match.columns if match else []) for r in cc.chars}
    omap = {r.id: r for cc in (ocr.columns if ocr else []) for r in cc.chars}

    def _fallback(rid: str) -> str | None:
        m = mmap.get(rid)
        if m and m.candidates:
            return m.candidates[0][0]
        o = omap.get(rid)
        if o and o.topk:
            return o.topk[0][0]
        return None

    slots: list[tuple[int, int, str, str]] = []
    meta: dict[tuple[int, int, str], str] = {}
    # 有 match 时以它为准列举字位——context_decision 可能整列缺席（弃权），
    # 那样按 dec 列举会把整列丢掉，锚定串又会错位。
    src = match if match is not None else dec
    dmap = {r.id: r for cc in dec.columns for r in cc.chars} if dec else {}
    for cc in sorted(src.columns, key=lambda c: c.col):
        if not cc.ok:
            continue
        # ⚠️ **按阅读顺序**，不是 (slot, sub)（2026-09-06 修，同 context_decide）。
        # 夹注 a/b 是两行小字，(slot, sub) 排出来交错成「兩採淮進鹽本政」，
        # 8-gram 锚不上、difflib 还会把邻近正文一起拖进 replace 段。
        for r in sort_by_reading(cc.chars):
            d = dmap.get(r.id)
            ch = (d.char if d and d.char else None)
            source = (d.source if d and d.char else "")
            if ch is None and (match is not None or ocr is not None):
                ch = _fallback(r.id)
                source = "fallback"
            if not ch:
                continue
            sub = r.sub or ""
            slots.append((cc.col, r.slot, sub, ch))
            meta[(cc.col, r.slot, sub)] = source
    return slots, meta


def align_page(book: str, page: int, store, corpus: str,
               corpus_index: dict) -> PageGold:
    from ..clustering.align_label import label_page
    from ..core.spec import page_key

    dec = store.read(book, "context_decide", page_key(page), "context_decision")
    if dec is None:
        return PageGold(book=book, page=page, anchored=False, note="没有定字产物")
    # 库/OCR 供弃权位兜底（见 _slots_from_decision）；缺了也能跑，只是覆盖低
    match = store.read(book, "glyph_match", page_key(page), "glyph_match")
    ocr = store.read(book, "ocr_candidates", page_key(page), "ocr_candidates")
    slots, meta = _slots_from_decision(dec, match, ocr)
    if len(slots) < 12:
        return PageGold(book=book, page=page, anchored=False,
                        note=f"定字太少（{len(slots)}），锚不住")

    labels, ok = label_page(str(page), slots, book, corpus, corpus_index)
    if not ok:
        return PageGold(book=book, page=page, anchored=False, note="8-gram 锚定失败")

    out: list[GoldChar] = []
    n_conv = 0
    for lab in labels:
        # AlignedLabel.instance_id 是 book:page:col:slot[a|b]——idx 就是 slot，
        # 夹注半格带 a/b 后缀（2026-09-06；此前不带，a/b 互相覆盖，
        # gold 里一条夹注格都没有，判据 A 从来没量过夹注）。
        parts = lab.instance_id.split(":")
        col, tail = int(parts[2]), parts[3]
        sub = tail[-1] if tail[-1:] in ("a", "b") else ""
        slot = int(tail[:-1] if sub else tail)
        # hyp = 转写（v2 定的字形）；char = 金标（整理本给的文意读法）
        shape, reading = lab.hyp, lab.char
        conv = shape != reading
        n_conv += conv
        out.append(GoldChar(
            id=lab.instance_id, page=page, col=col, slot=slot, sub=sub or None,
            shape=shape, reading=reading,
            align_op=lab.op, op_run=lab.op_run,
            conversion=conv, source=meta.get((col, slot, sub), "")))
    return PageGold(book=book, page=page, anchored=True,
                    n_chars=len(out), n_conversion=n_conv, chars=out)


def align_book(book: str, pages: list[int], store,
               corpus_path: str | Path = DEFAULT_CORPUS) -> list[PageGold]:
    from ..clustering.align_label import build_ngram_index
    text = Path(corpus_path).read_text(encoding="utf-8")
    index = build_ngram_index(text)
    return [align_page(book, pg, store, text, index) for pg in pages]


def write_jsonl(golds: list[PageGold], out: str | Path) -> int:
    """落成一行一个字位的 jsonl——统一金标信封那边好收。"""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out, "w", encoding="utf-8") as f:
        for g in golds:
            for c in g.chars:
                f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
                n += 1
    return n
