# -*- coding: utf-8 -*-
"""字流证人对齐：`line_is_column=false` 的证人（换行与刻本不同）→ 逐字位候选标签。

`witness_align` 那条走的是**列级**对齐：证人一行 = 刻本一列，项数相等就一一对应，
不需要任何识别结果。**同书异版对不上这个结构**——北行日錄刻本（筒子页 9 列 × 21 字
无标点）与它的现代排印本校對本（17 列 × 14~16 字 + 标点）换行完全不同，一行 ≠ 一列。

所以这条把两边都拉成**一维字流**再做全局对齐：

- 刻本侧：Step3 的 `char` 格按阅读序（页 → 列右→左 → 格上→下）展开，
  版心（`line_index.kind == "margin"`）与非 `body` 列一律跳过；
- 证人侧：去掉标点、页码行、脚注行，只留汉字；
- 用 OCR top-1 当**锚**：`difflib.SequenceMatcher` 在「OCR 字流 ↔ 证人字流」上求最长
  匹配块，只有落在 `equal` 块里、且块长 ≥ `min_block` 的字位才给标签。

⚠️ **这不是金标，是文本一路的证据**（provenance=align）。按「自动放行必须两路零同源
互证」的纪律，拿它播种字形库必须再配一路形状证据（字体模板 top-1），见
`seed_witness.seed_from_witness`。OCR 在这里**只当锚、不当标签**——标签一律取证人字。

为什么只收 `equal` 块：OCR 准确率约 90%（北行日錄 p30 实测 ratio 0.898），
`replace` 块里 OCR 与证人不一致，可能是 OCR 错、也可能是两版异文（刻本「曾」作「會」、
「遊」作「游」），无法在这一层分辨——**不猜，整块跳过**。

输出（工作区 `products/<book>/witness_align/labels.jsonl`，一行一个字位，
格式与 `witness_align` 一致，`seed-witness` 直接消费）：
    {"page", "col", "slot", "char", "kind": "char", "cell_kind": "char",
     "witness_idx": 证人字流下标, "block_len": 所在 equal 块长度}
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

#: 只有落在这么长以上的 `equal` 块里才给标签。块越长，「两边恰好同错」的概率越低；
#: 8 与 `align_label` 的 8-gram 锚定同一个量级。实测块长分布见 CLI 打印的直方图。
MIN_BLOCK = 8

HAN_RE = re.compile(r"[一-鿿]")
FOOTNOTE_RE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]")
PAGE_MARK_RE = re.compile(r"^\d{4}$")


@dataclass
class CellRef:
    page: int
    col: int
    slot: int


@dataclass
class StreamAlignResult:
    labels: list[dict] = field(default_factory=list)
    n_cells: int = 0
    n_witness: int = 0
    n_ocr: int = 0
    n_equal: int = 0          # equal 块覆盖的字位数（未过 min_block 闸）
    n_labeled: int = 0        # 真正给出标签的字位数
    blocks: list[int] = field(default_factory=list)   # 各 equal 块长度
    ocr_agree: int = 0        # 标签处 OCR 与证人一致的个数（自检用，应当 ~100%）


def witness_char_stream(path: Path) -> str:
    """证人 txt → 纯汉字流。去页码行、脚注行、标点与所有非汉字。"""
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or PAGE_MARK_RE.match(s) or FOOTNOTE_RE.match(s):
            continue
        out.append("".join(HAN_RE.findall(s)))
    return "".join(out)


def book_cell_stream(products_root: Path, book_id: str) -> list[CellRef]:
    """刻本侧字流：Step3 `char` 格按阅读序。跳过版心与非 body 列。"""
    cells: list[CellRef] = []
    rs_dir = products_root / book_id / "row_segment"
    bd_dir = products_root / book_id / "border_detect"
    for f in sorted(rs_dir.glob("p*.json")):
        page = int(f.stem[1:])
        doc = json.loads(f.read_text(encoding="utf-8"))["cells"]
        kinds: dict[int, str] = {}
        bd = bd_dir / f.name
        if bd.exists():
            li = json.loads(bd.read_text(encoding="utf-8")).get("line_index")
            if li:
                kinds = {l["col"]: l["kind"] for l in li["lines"]}
        for col in sorted(doc["columns"], key=lambda c: c["col"]):
            if not col.get("ok"):
                continue
            if kinds and kinds.get(col["col"]) != "body":
                continue
            for cell in sorted(col["cells"], key=lambda x: x["slot"]):
                if cell.get("kind") == "char":
                    cells.append(CellRef(page, col["col"], cell["slot"]))
    return cells


def ocr_top1(products_root: Path, book_id: str) -> dict[tuple[int, int, int], str]:
    """(page, col, slot) → OCR top-1 字。缺页/缺格就没有这个键。"""
    out: dict[tuple[int, int, int], str] = {}
    d = products_root / book_id / "ocr_candidates"
    if not d.is_dir():
        return out
    for f in sorted(d.glob("p*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))["ocr_candidates"]
        for col in doc["columns"]:
            if not col.get("ok"):
                continue
            for ch in col["chars"]:
                if ch.get("topk"):
                    out[(doc["page"], col["col"], ch["slot"])] = ch["topk"][0][0]
    return out


def align_stream(book, *, witness: Path, products_root: Path,
                 min_block: int = MIN_BLOCK, log=print) -> StreamAlignResult:
    """字流对齐 → 逐字位标签。见模块 docstring 的纪律说明。"""
    res = StreamAlignResult()
    cells = book_cell_stream(products_root, book.id)
    wit = witness_char_stream(witness)
    ocr = ocr_top1(products_root, book.id)
    res.n_cells, res.n_witness = len(cells), len(wit)

    # OCR 字流：没有 OCR 结果的字位用 '�' 占位，保持与 cells 逐位对应
    ocr_seq = [ocr.get((c.page, c.col, c.slot), "�") for c in cells]
    res.n_ocr = sum(1 for c in ocr_seq if c != "�")
    if not cells or not wit:
        log("[stream-align] 字位或证人为空，放弃")
        return res
    if res.n_ocr < len(cells) * 0.5:
        log(f"[stream-align] ⚠️ OCR 只覆盖 {res.n_ocr}/{len(cells)} 个字位，"
            f"锚定会很稀疏——先把 ocr_candidates 跑全")

    sm = difflib.SequenceMatcher(None, ocr_seq, list(wit), autojunk=False)
    for a, b, n in sm.get_matching_blocks():
        if n == 0:
            continue
        res.blocks.append(n)
        res.n_equal += n
        if n < min_block:
            continue
        for k in range(n):
            c = cells[a + k]
            ch = wit[b + k]
            res.labels.append({
                "page": c.page, "col": c.col, "slot": c.slot,
                "char": ch, "kind": "char", "cell_kind": "char",
                "witness_idx": b + k, "block_len": n,
            })
            if ocr_seq[a + k] == ch:
                res.ocr_agree += 1
    res.n_labeled = len(res.labels)
    return res


def write_labels(res: StreamAlignResult, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as fh:
        for d in res.labels:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
