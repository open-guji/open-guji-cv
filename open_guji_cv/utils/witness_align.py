# -*- coding: utf-8 -*-
"""列级证人对齐：`line_is_column=true` 的整理本 → 逐字位的候选标签。

刻本链的 Step5-d `align_ref` 用 8-gram 把整理本锚到页转写上，锚定串靠库 top1 / OCR 填——
新书库是空的、OCR 又关着，锚不上。现代排印本有更硬的结构可用：整理本**一行 = 一列**
（北行日錄校對本），只要 Step3 切出的项数与该行的字符数相等，字位与字符就是一一对应，
不需要任何识别结果。对不上的列整列不给标签（不猜）。

这不是金标，是**文本这一路的证据**（provenance=align）：拿它播种字形库必须再配一路零同源的
形状证据（字体模板 cov），见 `scripts`/CLI 里的播种命令；拿它当判据 A 的真值也要先过人裁。

已知的证人噪声（北行日錄校對本实测）：换行错位、【】小注前后省略「、」「。」、漏字、
脚注行乱放——都表现为「项数不等」被整列跳过，不会漏进标签。

输出（工作区 `products/<book>/witness_align/labels.jsonl`，一行一个字位）：
    {"page", "col", "slot", "char", "kind": "char"|"punct", "witness_line": 影印页码, "line_idx"}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

FOOTNOTE_RE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]")
PAGE_MARK_RE = re.compile(r"^\d{4}$")
PUNCT = set("，。、；：「」『』（）《》〈〉！？…—·")


@dataclass
class WitnessBlock:
    page_no: int | None
    lines: list[str]


def read_witness_blocks(path: Path) -> list[WitnessBlock]:
    """按影印页码分块（页码行是块的**末尾**）。"""
    blocks: list[WitnessBlock] = []
    cur: list[str] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if PAGE_MARK_RE.fullmatch(s):
            blocks.append(WitnessBlock(int(s), cur))
            cur = []
        elif s:
            cur.append(s)
    if cur:
        blocks.append(WitnessBlock(None, cur))
    return blocks


def merge_note_lines(lines: list[str]) -> list[str]:
    """【 未闭合就并下一行（双行小注跨行）；脚注行丢掉；【】本身去掉。"""
    out: list[str] = []
    buf: str | None = None
    for l in lines:
        if FOOTNOTE_RE.match(l):
            continue
        buf = l if buf is None else buf + l
        if buf.count("【") > buf.count("】"):
            continue
        out.append(buf.replace("【", "").replace("】", ""))
        buf = None
    if buf:
        out.append(buf.replace("【", "").replace("】", ""))
    return out


def page_item_cells(cells_doc: dict, line_index_doc: dict) -> list[tuple[int, list[dict]]]:
    """一页 → [(col, [非 blank 的项…])]，跳过空列位与小字整列（脚注）。"""
    skip = {ln["col"] for ln in line_index_doc["lines"]
            if ln["kind"] == "empty" or "small_col" in ln.get("flags", [])}
    out = []
    for c in cells_doc["columns"]:
        if c["col"] in skip or not c["ok"]:
            if c["col"] not in skip:
                out.append((c["col"], None))     # 未过闸的列占位，让序号对得上
            continue
        items = [x for x in c["cells"] if x["kind"] != "blank"]
        if not items and "empty" in c.get("flags", []):
            continue
        out.append((c["col"], items))
    return out


def align_book(book, *, first_page_no: int, witness: Path, products_root: Path,
               log=print) -> dict:
    """扫描页 k ↔ 影印页 first_page_no + k − 1；逻辑页 2k−1（上栏）/ 2k（下栏）。
    写 `products/<book>/witness_align/labels.jsonl`，返回统计。"""
    blocks = read_witness_blocks(witness)
    prod = products_root / book.id
    # 每个扫描页的列（上栏 + 下栏）
    def scan_cols(k: int):
        cols = []
        for pg in (2 * k - 1, 2 * k):
            cp = prod / "row_segment_runs" / f"p{pg:04d}.json"
            lp = prod / "line_detect" / f"p{pg:04d}.json"
            if not cp.exists() or not lp.exists():
                continue
            cells_doc = json.loads(cp.read_text(encoding="utf-8"))["cells"]
            li = json.loads(lp.read_text(encoding="utf-8"))["line_index"]
            for col, items in page_item_cells(cells_doc, li):
                cols.append((pg, col, items))
        return cols

    n_scans = max((int(p.stem[1:]) for p in (prod / "row_segment_runs").glob("p*.json")), default=0)
    n_scans = (n_scans + 1) // 2
    all_cols = {k: scan_cols(k) for k in range(1, n_scans + 1)}
    # 影印页码 → 行；双页块按前一页探出的列数拆
    page_lines: dict[int, list[str]] = {}
    for b in blocks:
        if b.page_no is None:
            continue
        lines = merge_note_lines(b.lines)
        if len(lines) > 45:
            k_prev = b.page_no - 1 - first_page_no + 1
            n_prev = len(all_cols.get(k_prev, []))
            page_lines[b.page_no - 1] = lines[:n_prev]
            page_lines[b.page_no] = lines[n_prev:]
        else:
            page_lines[b.page_no] = lines

    out_dir = prod / "witness_align"
    out_dir.mkdir(parents=True, exist_ok=True)
    n_lab = n_cols_ok = n_cols = 0
    with open(out_dir / "labels.jsonl", "w", encoding="utf-8") as f:
        for k in range(1, n_scans + 1):
            pno = first_page_no + k - 1
            lines = page_lines.get(pno)
            cols = all_cols.get(k, [])
            if not lines or not cols:
                continue
            for i, ((pg, col, items), line) in enumerate(zip(cols, lines)):
                n_cols += 1
                if items is None or len(items) != len(line):
                    continue
                n_cols_ok += 1
                for it, ch in zip(items, line):
                    kind = "punct" if ch in PUNCT else "char"
                    f.write(json.dumps({"page": pg, "col": col, "slot": it["slot"], "char": ch,
                                        "kind": kind, "cell_kind": it["kind"],
                                        "witness_page": pno, "line_idx": i}, ensure_ascii=False) + "\n")
                    n_lab += 1
    stats = {"scans": n_scans, "columns": n_cols, "columns_aligned": n_cols_ok, "labels": n_lab,
             "out": str(out_dir / "labels.jsonl")}
    log(f"[witness-align] 列 {n_cols_ok}/{n_cols} 项数相等 → {n_lab} 个字位标签 → {stats['out']}")
    return stats
