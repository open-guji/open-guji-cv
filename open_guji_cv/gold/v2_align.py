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


@dataclass
class PageGold:
    book: str
    page: int
    anchored: bool
    n_chars: int = 0
    n_conversion: int = 0
    chars: list[GoldChar] = field(default_factory=list)
    note: str = ""


def _slots_from_decision(dec) -> tuple[list[tuple[int, int, str]], dict]:
    """Step6 的 `context_decision` → `label_page` 要的 slots + 溯源表。

    只收**定了字**的位（`char` 非空）——弃权位没有假设可对齐，硬塞进去会让
    整列错位。列间按 col 升序、列内按 slot 升序，就是阅读顺序。
    """
    slots: list[tuple[int, int, str]] = []
    meta: dict[tuple[int, int], str] = {}
    for cc in sorted(dec.columns, key=lambda c: c.col):
        if not cc.ok:
            continue
        for r in sorted(cc.chars, key=lambda x: (x.slot, x.sub or "")):
            if not r.char:
                continue
            slots.append((cc.col, r.slot, r.char))
            meta[(cc.col, r.slot)] = r.source
    return slots, meta


def align_page(book: str, page: int, store, corpus: str,
               corpus_index: dict) -> PageGold:
    from ..clustering.align_label import label_page
    from ..core.spec import page_key

    dec = store.read(book, "context_decide", page_key(page), "context_decision")
    if dec is None:
        return PageGold(book=book, page=page, anchored=False, note="没有定字产物")
    slots, meta = _slots_from_decision(dec)
    if len(slots) < 12:
        return PageGold(book=book, page=page, anchored=False,
                        note=f"定字太少（{len(slots)}），锚不住")

    labels, ok = label_page(str(page), slots, book, corpus, corpus_index)
    if not ok:
        return PageGold(book=book, page=page, anchored=False, note="8-gram 锚定失败")

    out: list[GoldChar] = []
    n_conv = 0
    for lab in labels:
        # AlignedLabel.instance_id 是 book:page:col:idx——我们传进去的 idx 就是 slot
        parts = lab.instance_id.split(":")
        col, slot = int(parts[2]), int(parts[3])
        # hyp = 转写（v2 定的字形）；char = 金标（整理本给的文意读法）
        shape, reading = lab.hyp, lab.char
        conv = shape != reading
        n_conv += conv
        out.append(GoldChar(
            id=lab.instance_id, page=page, col=col, slot=slot,
            shape=shape, reading=reading,
            align_op=lab.op, op_run=lab.op_run,
            conversion=conv, source=meta.get((col, slot), "")))
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
