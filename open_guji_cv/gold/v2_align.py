"""v2 产物 × 整理本 → 自动金标。

九步跑完之后手上只有**覆盖率**（same 多少、定字多少），没有**准确率**——
1359 个 same 里有几个是对的，不量就不知道。这个模块用整理本给大部分字位
自动落金标，把人工从「逐字标 1933 条」降到「裁几百条难例」。

## 两个身份分开了（2026-09-09，Step5-d 归位）

**对齐**（8-gram 锚定 + `difflib` 过闸，产出逐字位 `align_char`/`align_op`）
挪去了 `steps/align_ref.py`，成了与 `glyph_match`/`ocr_candidates`/
`context_decision` 平级的正式 Step——它同时是四路证据里的文本那一路，
之前挤在这个「金标生成器」模块里，导致它的产物没有独立指纹与过期传播。

本模块现在只做**金标派生**：优先读 `align_ref` 的产物（指纹对得上才用，
见 `_aligned_chars`），把 `shape`（v2 定的刻本形，仍从 `context_decision`/
`glyph_match`/`ocr_candidates` 现算——这部分本来就不是"对齐"）与
`align_ref` 给的 `reading`/`align_op`/`op_run` 拼成 `GoldChar`。

调用方传了非默认 `corpus_path`（`build_rare_char_set.py`/
`survey_review_queue.py` 的 `--corpus`）、或还没跑过 `align_ref` 时，
**现算一遍兜底**（复用同一份 `clustering.align_label.label_page`，算法不变）
——不能让脚本传自定义语料却读到 `align_ref` 缓存的默认语料结果。

## 怎么锚（算法在 `align_ref` 里，这里只是简述）

`clustering/align_label.label_page`：定字串 → 8-gram 锚到整理本 →
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

DEFAULT_CORPUS = "corpus/zongmu_wenyuange_wikisource.txt"


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


def _aligned_chars(book: str, page: int, store, slots: list[tuple[int, int, str, str]],
                   corpus_text: str, corpus_index: dict, corpus_path: str | Path,
                   ) -> dict[tuple[int, int, str], tuple[str, str, int]] | None:
    """{(col, slot, sub): (align_char, align_op, ref_run)}——过闸位才在里面。

    优先读 `align_ref` 的产物（省一次 8-gram 锚定 + difflib，且吃得到它的
    指纹过期传播）；产物缺失、未锚定、或调用方传的语料与产物指纹对不上
    （脚本用 `--corpus` 传了非默认语料）时现算一遍兜底——算法与 `align_ref`
    内部完全相同（同一份 `clustering.align_label.label_page`），只是不进
    Step 缓存。返回 None 代表锚不上。
    """
    from ..core.spec import page_key
    from ..steps.context_decide import corpus_fingerprint
    fp = corpus_fingerprint([str(corpus_path)]) if corpus_path else ""
    ref = store.read(book, "align_ref", page_key(page), "align_ref")
    if ref is not None and ref.anchored and fp and ref.corpus_fingerprint == fp:
        return {(c.col, c.slot, c.sub or ""): (c.align_char, c.align_op, c.ref_run)
                for c in ref.chars}

    from ..clustering.align_label import label_page
    labels, ok = label_page(str(page), slots, book, corpus_text, corpus_index)
    if not ok:
        return None
    out: dict[tuple[int, int, str], tuple[str, str, int]] = {}
    for lab in labels:
        # AlignedLabel.instance_id 是 book:page:col:slot[a|b]——idx 就是 slot，
        # 夹注半格带 a/b 后缀（2026-09-06；此前不带，a/b 互相覆盖，
        # gold 里一条夹注格都没有，判据 A 从来没量过夹注）。
        parts = lab.instance_id.split(":")
        col, tail = int(parts[2]), parts[3]
        sub = tail[-1] if tail[-1:] in ("a", "b") else ""
        slot = int(tail[:-1] if sub else tail)
        out[(col, slot, sub)] = (lab.char, lab.op, lab.op_run)
    return out


def align_page(book: str, page: int, store, corpus: str, corpus_index: dict,
               corpus_path: str | Path = "") -> PageGold:
    from ..core.spec import page_key
    from ..steps.align_ref import slots_from_decision

    dec = store.read(book, "context_decide", page_key(page), "context_decision")
    if dec is None:
        return PageGold(book=book, page=page, anchored=False, note="没有定字产物")
    # 库/OCR 供弃权位兜底（见 slots_from_decision）；缺了也能跑，只是覆盖低
    match = store.read(book, "glyph_match", page_key(page), "glyph_match")
    ocr = store.read(book, "ocr_candidates", page_key(page), "ocr_candidates")
    slots, meta = slots_from_decision(dec, match, ocr)
    if len(slots) < 12:
        return PageGold(book=book, page=page, anchored=False,
                        note=f"定字太少（{len(slots)}），锚不住")

    aligns = _aligned_chars(book, page, store, slots, corpus, corpus_index, corpus_path)
    if aligns is None:
        return PageGold(book=book, page=page, anchored=False, note="8-gram 锚定失败")

    out: list[GoldChar] = []
    n_conv = 0
    for col, slot, sub, hyp in slots:
        al = aligns.get((col, slot, sub))
        if al is None:
            continue          # 没过闸（insert/delete/长 replace/没被 equal 夹住）
        reading, op, op_run = al
        # hyp = 转写（v2 定的字形）；reading = 金标（整理本给的文意读法）
        conv = hyp != reading
        n_conv += conv
        iid = f"{book}:{page}:{col}:{slot}{sub}"
        out.append(GoldChar(
            id=iid, page=page, col=col, slot=slot, sub=sub or None,
            shape=hyp, reading=reading, align_op=op, op_run=op_run,
            conversion=conv, source=meta.get((col, slot, sub), "")))
    return PageGold(book=book, page=page, anchored=True,
                    n_chars=len(out), n_conversion=n_conv, chars=out)


def align_book(book: str, pages: list[int], store,
               corpus_path: str | Path = DEFAULT_CORPUS) -> list[PageGold]:
    from ..clustering.align_label import build_ngram_index
    text = Path(corpus_path).read_text(encoding="utf-8")
    index = build_ngram_index(text)
    return [align_page(book, pg, store, text, index, corpus_path) for pg in pages]


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
