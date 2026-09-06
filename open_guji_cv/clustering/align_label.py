"""整理本对齐 → 逐实例金标字（`label_origin: "align"` 的产出口）。

`align_eval.py` 量的是**页级准确率**（这一页转写对了几个字），本模块要的是
**逐实例的字标签**：`vol01:42:3:7 → "曰"`。两者共用同一套锚定与局部对齐，
差别在于这里必须把对齐结果**还原到实例编号**上，因此多两层约束：

1. **载体不是金标**：转写（`ranked.json` 的 `best`）只用来把这一页挂到语料
   的正确位置上，字标签一律取**语料**里的字。`equal` 段两者相同，
   `replace` 段取语料字——后者恰恰是转写错了的位置，是这批标注里最有价值的
   部分（聚类脏簇就藏在那里），丢掉它等于只收管线已经做对的样本。
   `insert`/`delete` 段（切分多切/漏切）整段丢弃：那里的实例与语料字
   **对不上号**，硬配会把错标灌进金标。

2. **编号会漂**：`page:col:idx` 是**当前切分产物**的编号，上游一改就指向
   别的格子（making-datasets.md 第一步）。所以每页都做结构一致性校验——
   `ranked.json` 与当前 `index.jsonl` 的「每列多少格」必须逐列相同，
   不同就整页丢弃。这不是洁癖：实测 vol01 201 页里有 139 页结构已经变了
   （转写产自更早一次 phase4），不校验就会把标签系统性地错位一格。

对齐载体有两种来源：

- `phase6_labels/ranked.json` 的转写（原设计）——但它只有在 label 步骤
  与切分同版重跑过时才可用；881d777 之后的转写全是 `<unk>`（重跑没带
  OCR 源），载体作废。
- **OCR 载体**（`scripts/build_ocr_carrier.py`，2026-08-23 起首选）：
  逐图块 RapidOCR top1 + s2t，与切分永远同版。G5 在 book9 金标上的实测
  top1 88.75%，比旧转写载体（86.4%）还高。用 `slots_by_page` 参数传入。

用法见 `scripts/build_clustering_dataset.py`。
"""

from __future__ import annotations

import difflib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .align_eval import WINDOW_PAD, anchor_page, build_ngram_index


BLANK_INK = 0.05                   # 近空格位判据（见 clean_labels）


def is_han(ch: str) -> bool:
    """金标字必须是汉字。语料自带换行，对齐窗口会把 `\\n` 当成一个字发出来。"""
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
            or 0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x2A6DF)


def clean_labels(labels, index: dict) -> tuple[list, dict]:
    """两条清洗规则。线索都取自对齐之外（extractor 的量），不是「看着不像就删」。

    1. **非汉字**：语料带换行，对齐窗口会把 `\\n` 当成一个字发出来。
    2. **`replace` + 格位可疑**：`replace` 位的标签**只靠位置**站着——图像证据
       恰恰是反对它的（转写认成了别的字）。所以只要切分自检对这一格有独立
       怀疑，就否掉：
       - `ink_ratio < 0.05`：近空格位。实测 vol01 命中 8 个，**全在页 150 每列
         最后一格**，目视 100% 是空格；
       - `frame_bars`（版框横线）：实测 vol02 命中 8 个，目视 8/8 是纯横线。

    `equal` 位不套第 2 条：转写与语料两边都指向同一个字，证据强得多。
    实测低墨的 `equal` 12 个全是「一」（一横本来就淡），带 `frame_bars` 的
    `equal` 在 vol01 有 11 个、目视 11/11 是真字（横线只是压在字块边上）。
    代价是漏掉极少数「两边都错到一块去」的（vol02 有 1 个：纯横线格位被
    转写认成「一」，语料那位置恰好也是「一」）——写进 known_limitation。
    """
    kept, dropped = [], {"non_han": 0, "blank_replace": 0, "frame_bars_replace": 0}
    for x in labels:
        if not is_han(x.char):
            dropped["non_han"] += 1
            continue
        rec = index.get(x.instance_id, {})
        if x.op == "replace":
            if rec.get("ink_ratio", 1.0) < BLANK_INK:
                dropped["blank_replace"] += 1
                continue
            if "frame_bars" in rec.get("flags", ()):
                dropped["frame_bars_replace"] += 1
                continue
        kept.append(x)
    return kept, dropped


@dataclass
class AlignedLabel:
    """一个实例的对齐金标。"""

    instance_id: str
    page: str
    char: str        # 金标字：来自参考语料
    hyp: str         # 转写字：只是对齐载体，不是金标
    op: str          # "equal"（转写与语料一致）| "replace"（转写错，金标以语料为准）
    op_run: int      # 该实例所在对齐段的长度：replace 段越长越可疑，供清洗分层用


@dataclass
class PageLabelStat:
    page: str
    n_slots: int
    anchored: bool
    structure_ok: bool
    n_equal: int
    n_replace: int

    @property
    def n_labeled(self) -> int:
        return self.n_equal + self.n_replace


def slot_key(col: str | int, idx: str | int) -> tuple[int, int, str]:
    """(列, 格) → 可排序的键，能吃下**夹注子字**的 a/b 后缀。

    双行夹注（main 的「a/b 子列拆分」）把一格里的左右两个小字写成
    `…:9:2a` / `…:9:2b`——id 尾段带后缀，而 index 的 `idx` 字段仍是 2。
    直接 `int(idx)` 会炸（vol01 有 248 条这样的记录）。这里把尾段拆成
    数字 + 后缀：排序上 2a < 2b < 3，与 index 里的行序、与页面上的
    阅读顺序都一致。
    """
    m = re.match(r"^(-?\d+)([a-z]*)$", str(idx).strip())
    if not m:
        raise ValueError(f"格序号解析不了: {idx!r}")
    return (int(col), int(m.group(1)), m.group(2))


def page_slots(ranked: list[dict]) -> dict[str, list[tuple[int, int, str]]]:
    """ranked.json 的 results → {页: [(col, idx, 转写字), ...]}，页内按 (col, idx)。

    顺序必须与 `labeling.rank_book` 写 `text/{page}.txt` 时完全一致
    （列升序、列内 idx 升序、拼接后去掉换行），否则位置对不上。
    """
    by_page: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for r in ranked:
        _, page, col, idx = r["id"].split(":")
        by_page[page].append((*slot_key(col, idx), r["best"]))
    # 排序用带后缀的四元组（2a < 2b < 3），对外仍是 (col, idx, 字) 三元组
    return {p: [(c, i, t) for c, i, _, t in sorted(v)]
            for p, v in by_page.items()}


def _structure(slots: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
    """页结构指纹：全部 (列号, 格序号)。

    只比「每列几格」不够：同样是 20 格，`idx` 从 0 起还是从 1 起是两回事，
    编号对不上就会把标签挂到不存在的实例上（实测 vol02 页 80 就是这样）。
    """
    return sorted((col, idx) for col, idx, _ in slots)


def index_structure(index_path: str | Path,
                    cell_types: tuple[str, ...] | None = ("char",),
                    ) -> dict[str, list[tuple[int, int]]]:
    """当前 phase4 index.jsonl → {页: 结构指纹}。

    **只算 `cell_type == "char"` 的格**（2026-08-25 修）。指纹是拿来跟
    `carrier_slots(..., valid_ids=…)` 的输出比的，而调用方传的 valid_ids
    向来只含 char 实例——这边却把 `empty` 空格位也数进来，两边口径差几格，
    整页就被判 structure drift 丢掉。vol01 新切分实锤：第 21 页载体 179
    vs 指纹 181、第 24 页 179 vs 180，两页的过闸对齐因此**全灭**（各自
    120+ 个字位白白进了人工队列），而 20/22/23 页恰好没有空格位所以没事。
    `cell_types=None` 可以要回旧的全量口径。
    """
    per_page: dict[str, list[tuple[int, int]]] = defaultdict(list)
    with open(index_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            # 缺 cell_type 的精简行（旧产物、测试 fixture）当作 char——
            # 老口径本来就是全量，不能因为字段缺失把整页滤空
            if cell_types is not None \
                    and r.get("cell_type", "char") not in cell_types:
                continue
            # 夹注子字的后缀只在 id 里（idx 字段是 int），所以优先按 id 拆；
            # 没有 id 的精简行（测试 fixture、外部导出）退回 col/idx 字段
            if r.get("id") and r["id"].count(":") == 3:
                _, _, col, idx = r["id"].split(":")
            else:
                col, idx = r["col"], r["idx"]
            per_page[r["page"]].append(slot_key(col, idx))
    return {p: [(c, i) for c, i, _ in sorted(v)]
            for p, v in per_page.items()}


def label_page(page: str, slots: list[tuple], book: str,
               corpus: str, corpus_index: dict[str, list[int]],
               window_pad: int = WINDOW_PAD,
               ) -> tuple[list[AlignedLabel], bool]:
    """单页对齐 → 该页可标注的实例。返回 (标签, 是否锚定成功)。

    `slots` 是 `(col, slot, char)` 或 `(col, slot, sub, char)`（2026-09-06 加
    `sub`，夹注半格用）。**顺序即锚定串的顺序**，调用方负责按阅读顺序给——
    夹注两个子列若按 (slot, sub) 交错送进来，锚定串会是「兩採淮進鹽本政」，
    连累整页对齐。`sub` 非空时 `instance_id` 带后缀（`book:page:col:slot` + `a`/`b`），
    与 `cell_shrink` / `seed_admit` 的字位 id 一致。
    """
    norm = [(t[0], t[1], (t[2] or "") if len(t) > 3 else "", t[-1]) for t in slots]
    text = "".join(ch for _, _, _, ch in norm)
    offset = anchor_page(text, corpus_index)
    if offset is None:
        return [], False

    lo = max(0, offset)
    hi = min(len(corpus), offset + len(text) + window_pad)
    window = corpus[lo:hi]
    sm = difflib.SequenceMatcher(None, text, window, autojunk=False)

    out: list[AlignedLabel] = []
    ops = sm.get_opcodes()
    for n, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            pass
        elif tag == "replace" and (i2 - i1) == (j2 - j1):
            # G5 的采信规则（2ec0a00，OCR 载体噪声更大后必须有）：
            # replace 段的标签只靠位置站着，段一长或没被 equal 夹住，
            # 位置本身就不可信——实测漏进来的错标（卷→曰、己→已）全是
            # 这种。要求段长 ≤3 且左右都有 ≥2 字的 equal 段贴身夹住。
            if (i2 - i1) > 3:
                continue
            prev_ok = (n > 0 and ops[n - 1][0] == "equal"
                       and ops[n - 1][2] - ops[n - 1][1] >= 2)
            next_ok = (n + 1 < len(ops) and ops[n + 1][0] == "equal"
                       and ops[n + 1][2] - ops[n + 1][1] >= 2)
            if not (prev_ok and next_ok):
                continue
        else:
            # insert/delete/不等长 replace：实例与语料字对不上号，整段丢弃
            continue
        for k in range(i2 - i1):
            col, idx, sub, hyp = norm[i1 + k]
            gold = window[j1 + k]
            out.append(AlignedLabel(f"{book}:{page}:{col}:{idx}{sub}", page,
                                    gold, hyp, tag, i2 - i1))
    return out, True


def page_reference(page: str, slots: list[tuple[int, int, str]],
                   corpus: str, corpus_index: dict[str, list[int]],
                   window_pad: int = WINDOW_PAD,
                   ) -> dict[tuple[int, int], tuple[str | None, str]]:
    """免闸参考对齐：逐字位 best-effort 整理本字（**审查页面参考用，非金标**）。

    与 label_page 的区别：不设采信闸——equal 与等长 replace 段全部取
    对应语料字（replace 不限段长、不要求 equal 夹住），所以噪声比过闸
    标签大得多，只配当人眼参考；insert/delete/不等长段无对应（None）。
    非汉字参考（语料换行等）也置 None。返回 {(col, idx): (字|None, op)}。
    """
    text = "".join(ch for _, _, ch in slots)
    offset = anchor_page(text, corpus_index)
    if offset is None:
        return {}
    lo = max(0, offset)
    hi = min(len(corpus), offset + len(text) + window_pad)
    window = corpus[lo:hi]
    sm = difflib.SequenceMatcher(None, text, window, autojunk=False)
    out: dict[tuple[int, int], tuple[str | None, str]] = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        aligned = tag == "equal" or (tag == "replace" and (i2 - i1) == (j2 - j1))
        for k in range(i2 - i1):
            col, idx, _ = slots[i1 + k]
            ref = window[j1 + k] if aligned else None
            if ref is not None and not is_han(ref):
                ref = None
            out[(col, idx)] = (ref, tag)
    return out


def carrier_slots(carrier_path: str | Path,
                  valid_ids: set[str] | None = None,
                  ) -> dict[str, list[tuple[int, int, str]]]:
    """OCR 载体 jsonl（build_ocr_carrier.py 产出）→ slots_by_page。

    空识别用 '□' 占位：格位必须占住，否则页文本长度与实例数对不上，
    对齐窗口整体错位。

    ``valid_ids`` 给当前 index.jsonl 的实例 id 集合时，**丢掉载体里已经
    不存在的格位**。切分一重跑，载体就可能比索引多出/少掉格——多出的
    那一格会把整列文本后移一位，锚定照样"成功"但采信闸全灭：整页看着
    像"没锚定"，不报任何错。vol01 第 14 页实锤（切分 164→163 格，载体
    仍 164 条，过闸对齐从 162/180 掉到 0/163）。所以调用方**应当**把
    索引 id 传进来；载体缺格（索引有而载体无）无害（那一格没 OCR 而已），
    载体多格才致命。
    """
    by_page: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    dropped = 0
    with open(carrier_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if valid_ids is not None and r["id"] not in valid_ids:
                dropped += 1
                continue
            _, page, col, idx = r["id"].split(":")
            by_page[page].append((*slot_key(col, idx), r["char"] or "□"))
    if dropped:
        print(f"⚠ OCR 载体有 {dropped} 条已不在索引里（切分重跑过？）已丢弃；"
              f"建议重建载体：scripts/build_ocr_carrier.py")
    return {p: [(c, i, t) for c, i, _, t in sorted(v)]
            for p, v in by_page.items()}


def label_book(book: str, book_out_dir: str | Path, corpus_path: str | Path,
               pages: set[str] | None = None,
               corpus_index: dict[str, list[int]] | None = None,
               slots_by_page: dict[str, list[tuple[int, int, str]]] | None = None,
               ) -> tuple[list[AlignedLabel], list[PageLabelStat]]:
    """整册对齐标注。

    pages 给定时只处理这些页（正文页筛选交给调用方，见 page-type 金标）。
    slots_by_page 给定时用它当载体（OCR 载体），否则读 ranked.json。
    只有**结构一致且锚定成功**的页会产出标签。
    """
    book_out_dir = Path(book_out_dir)
    corpus = Path(corpus_path).read_text(encoding="utf-8")
    corpus_index = corpus_index if corpus_index is not None else build_ngram_index(corpus)

    if slots_by_page is None:
        with open(book_out_dir / "phase6_labels" / "ranked.json", encoding="utf-8") as f:
            ranked = json.load(f)["results"]
        slots_by_page = page_slots(ranked)
    current = index_structure(book_out_dir / "phase4_chars" / "index.jsonl")

    labels: list[AlignedLabel] = []
    stats: list[PageLabelStat] = []
    for page in sorted(slots_by_page, key=lambda p: (len(p), p)):
        if pages is not None and page not in pages:
            continue
        slots = slots_by_page[page]
        ok = _structure(slots) == current.get(page)
        if not ok:
            stats.append(PageLabelStat(page, len(slots), False, False, 0, 0))
            continue
        page_labels, anchored = label_page(page, slots, book, corpus, corpus_index)
        labels.extend(page_labels)
        stats.append(PageLabelStat(
            page, len(slots), anchored, True,
            sum(1 for x in page_labels if x.op == "equal"),
            sum(1 for x in page_labels if x.op == "replace")))
    return labels, stats


def summarize(stats: list[PageLabelStat]) -> dict:
    """页级汇总：分子分母都留着（比值单独看会骗人，见 making-datasets 第六步）。"""
    usable = [s for s in stats if s.structure_ok and s.anchored]
    return {
        "n_pages": len(stats),
        "n_structure_ok": sum(1 for s in stats if s.structure_ok),
        "n_anchored": len(usable),
        "n_slots_total": sum(s.n_slots for s in stats),
        "n_slots_usable_pages": sum(s.n_slots for s in usable),
        "n_labeled": sum(s.n_labeled for s in usable),
        "n_equal": sum(s.n_equal for s in usable),
        "n_replace": sum(s.n_replace for s in usable),
    }
