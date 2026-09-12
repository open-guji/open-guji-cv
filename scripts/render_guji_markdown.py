# -*- coding: utf-8 -*-
"""Step9 结果整理 · 坐标转字符位：把 Step3/Step7 产物拼成 guji-markdown 文本。

    PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe \
        scripts/render_guji_markdown.py vol01 33 --out out.md
    PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe \
        scripts/render_guji_markdown.py vol01 33 34 35

设计见 `overview` 仓 `项目进展/图片初步数字化/进度/Step9-结果整理/01-结果排版.md`
（下称"设计档"）。只做设计档 §四 定的范围：单页/多页拼出 guji-markdown 文本，
不做整册体检表、不做与整理本比对——那是 Step9 另外两件事。

## 为什么不是 core.step.Step

跟 Step8 同一个理由（见 `open_guji_cv/feedback/step8.py`）：输入是**跨列跨页**
的汇总（一页的完整文本要等这一页所有列都读完才能拼），产物是给人看的 md 文件，
不是 `<book>/<step>/<page>/` 下的一份 `ProductKindSpec`。不进 `core.step.STEPS`，
不出现在 `pipelines/*.yaml` 里。

## join 规则（设计档 §一）

Step7 `seed_admit`（每字位的定字结果）本身不带版式信息，要靠 Step3 `cells`
补上「这一格是不是夹注/空白、抬头级数多少」。两边用 `(col, slot, sub)` 对齐；
列内阅读顺序不自己算，直接调用 `utils.jiazhu_order.sort_by_reading()`
——它只要求记录有 `.slot`/`.sub`，`AdmitRec` 天然满足。

## 四处已知边界（设计档 §三，未验先说清楚，别指望这版就是终版）

1. **抬头级数**优先读 `ColumnCells.n_raised`（离散、可靠，见设计档 §三·1 的
   实测：3419 列零例外）。这一版脚本读的是 Step3 产物，不会撞上"Step7 产物里
   抬头区空白格不出现导致数负数 slot 低估"那个坑——但如果以后有人把这个脚本
   改成只读 Step7 产物，要重新看这条。
2. **挪抬 `.` 不产出**——现有数据完全没有对应的几何信号，这版直接跳过，不编
   映射公式（设计档 §三·1 结论、§五"不要碰"）。
3. **阙文 `[[…]]`**：`admit=False and char is None` 时输出，这是协调者按现有
   字段定的规则，不是 Step7 的既有枚举值。
4. `<…>` 夹注转行 `|` 与后缀属性 `{k=v}`（这版脚本目前只用到夹注 `|`）已在
   `guji-markdown` 分支 `claude/attrs-and-jz-break-0911` 实现并测试通过，
   但**尚未合并到 guji-markdown main**——用这份输出去跑下游解析器之前，
   确认对方用的是哪个版本。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from open_guji_cv.core.spec import page_key  # noqa: E402
from open_guji_cv.products.kinds.cells import CellRec, PageCells  # noqa: E402
from open_guji_cv.products.kinds.recog import AdmitRec, PageAdmit  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.utils.jiazhu_order import sort_by_reading  # noqa: E402

CELLS_STEP = "row_segment"
CELLS_KIND = "cells"
ADMIT_STEP = "seed_admit"
ADMIT_KIND = "seed_admit"


def render_column(admit_recs: list[AdmitRec], cells_by_key: dict[tuple[int, str], CellRec],
                   n_raised: int, stale: list[str], col: int) -> str:
    """把一列的定字结果拼成一行 guji-markdown 源文本（不含结尾换行）。

    `cells_by_key`：`(slot, sub or "")` → `CellRec`，同一列的全部格子，
    用来查 `kind`（正文/夹注/空白）——`AdmitRec` 本身不带这个信息。

    `stale`：本次调用发现的「Step7 有这个 (slot,sub) 但 Step3 cells 查不到」
    的记录，追加进这个列表由调用方统一报告——**不静默兜底成正文字**。
    这种缺口目前唯一已知的成因是 Step3 局部重切后下游没跟上（`guji status`
    会把这页标成"过期"），2026-09-11 实测 vol01 p89 col7 就是这样一个真实
    个例（全书 810 个夹注字位里只有它不匹配），不是本脚本的 join 逻辑错误，
    也不是 Step3/Step7 语义分歧——但既然是「数据版本不同步」，就不该被这层
    悄悄吃掉、拼出一份看着正常实际是错的文本。
    """
    ordered = sort_by_reading(admit_recs)

    prefix = "^" * n_raised if n_raised > 0 else ""

    def lookup(r: AdmitRec) -> CellRec | None:
        """查一次记一次，调用点只许有这一个，避免同一条记录被记两遍。"""
        c = cells_by_key.get((r.slot, r.sub or ""))
        if c is None:
            stale.append(f"col{col}:slot{r.slot}{r.sub or ''}")
        return c

    _NO_CACHE = object()  # 哨兵：区分"没有缓存"与"缓存的查询结果就是 None（MISSING）"

    out: list[str] = []
    i = 0
    # 每条记录的 cell 只查一次，查完存这里；下一轮循环（不管是外层还是内层）
    # 先看这里有没有缓存，避免"内层 break 前查过、外层又重查"这种同条重复计数。
    pending: object = _NO_CACHE
    while i < len(ordered):
        rec = ordered[i]
        cell = lookup(rec) if pending is _NO_CACHE else pending
        pending = _NO_CACHE
        kind = cell.kind if cell is not None else "char"

        if kind in ("jiazhu_a", "jiazhu_b"):
            # 收集这一段连续夹注：sort_by_reading 已经把同一段的 a 全部排在
            # b 全部之前，这里只要顺着走、按 sub 分桶即可，不用重新判断相邻性。
            a_chars: list[str] = []
            b_chars: list[str] = []
            c: CellRec | None = cell
            while i < len(ordered):
                r = ordered[i]
                k = c.kind if c is not None else None
                if k not in ("jiazhu_a", "jiazhu_b"):
                    pending = c  # 留给外层用，不重查
                    break
                ch = _char_text(r)
                (a_chars if k == "jiazhu_a" else b_chars).append(ch)
                i += 1
                if i < len(ordered):
                    c = lookup(ordered[i])
            if a_chars and b_chars:
                out.append("<" + "".join(a_chars) + "|" + "".join(b_chars) + ">")
            else:
                out.append("<" + "".join(a_chars) + "".join(b_chars) + ">")
            continue

        if kind == "blank":
            i += 1
            continue

        out.append(_char_text(rec))
        i += 1

    return prefix + "".join(out)


def _char_text(rec: AdmitRec) -> str:
    """一个字位的输出文本。`admit=False and char is None` 视为阙文（设计档 §三·2）。"""
    if not rec.admit and rec.char is None:
        return "[[]]"
    return rec.reading or rec.char or "[[]]"


def render_page(store: ProductStore, book: str, page: int, stale: list[str]) -> str:
    """`stale`：本页发现的「Step7 有记录但 Step3 cells 查不到」条目，
    格式 `p{page}col{col}:slot{n}{a|b}`，追加进这个列表，不在这一层报告。
    """
    key = page_key(page)
    cells: PageCells | None = store.read(book, CELLS_STEP, key, CELLS_KIND)  # type: ignore[assignment]
    admit: PageAdmit | None = store.read(book, ADMIT_STEP, key, ADMIT_KIND)  # type: ignore[assignment]
    if admit is None:
        raise FileNotFoundError(f"{book} 第 {page} 页没有 {ADMIT_STEP} 产物（先跑到 Step7）")
    if cells is None:
        raise FileNotFoundError(f"{book} 第 {page} 页没有 {CELLS_STEP} 产物（先跑到 Step3）")

    cells_by_col: dict[int, dict[tuple[int, str], CellRec]] = {}
    n_raised_by_col: dict[int, int] = {}
    for col_cells in cells.columns:
        cells_by_col[col_cells.col] = {
            (c.slot, c.sub or ""): c for c in col_cells.cells
        }
        n_raised_by_col[col_cells.col] = col_cells.n_raised

    lines: list[str] = []
    for col_admit in sorted(admit.columns, key=lambda c: c.col):
        if not col_admit.ok or not col_admit.chars:
            continue
        cells_by_key = cells_by_col.get(col_admit.col, {})
        n_raised = n_raised_by_col.get(col_admit.col, 0)
        col_stale: list[str] = []
        lines.append(render_column(col_admit.chars, cells_by_key, n_raised, col_stale, col_admit.col))
        stale.extend(f"p{page}{s}" for s in col_stale)

    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book")
    ap.add_argument("pages", nargs="+", type=int)
    ap.add_argument("--out", default=None, help="输出文件（缺省打印到 stdout）")
    args = ap.parse_args()

    store = ProductStore()
    parts: list[str] = []
    stale: list[str] = []
    for page in args.pages:
        parts.append(f"#第{page}页")
        parts.append(render_page(store, args.book, page, stale))

    if stale:
        print(f"⚠ {len(stale)} 处 Step7 记录在 Step3 cells 里查不到对应格子"
              f"（Step3 局部重切后 Step7 没跟着重跑，见脚本 docstring）："
              f"{', '.join(stale)}", file=sys.stderr)
        print("这些字位按裸正文字兜底输出，可能把夹注/空白格拆错——"
              "先用 `python -m open_guji_cv status` 查这些页是否过期，"
              "重跑到 seed_admit 之后再信这份输出。", file=sys.stderr)

    text = "\n".join(parts) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"写入 {args.out}（{len(args.pages)} 页）")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
