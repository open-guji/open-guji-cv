# -*- coding: utf-8 -*-
"""字位流：一页的定字结果按阅读顺序摊平成一串 `SlotRec`。

**9.1 排版与 9.3 比对共用这一份**——此前两边各有一套 join：
`render/guji_markdown.py::render_page`（出 `reading or char`）与
`scripts/build_collation_report.py::page_slots`（出 `char`，未放行位退到
ctx/库/OCR 猜测）。同一页在「最终文本」里和「被比对的文本」里是两串不同的字，
比对报告说的每一条差异都未必指向最终文本里那个字。归一到这里。

## 取字规则（设计档 04 §三·1，两处分歧在此裁定）

- `char` ＝ **字形层，照录图上的形**，比对以它为准；
- `reading` ＝ 文意读法（整理本参与的通道才填），只参与分类
  （`char != ref` 且 `reading == ref` ⇒ 管线已知的转换，不是新发现的差异）；
- **未放行且 `char is None` 的位输出 `None`，不退到库/OCR 猜测**。原型那样做的
  结果是 vol01 251 条「改」里 221 条是未审位的库 top1 猜测——噪声盖过信号，
  而这些位本来就该由「未审阅数」这个指标去报，不该混进差异清单。
  调用方要显示时自行渲染成 `□`（比对）或 `[[]]`（9.1 的阙文记号）。

## 三种「没有字」的格必须分开（真实数据教训，别合并）

| | Step3 `cells.kind` | Step7 有 `AdmitRec`？ | 含义 | 在流里 |
|---|---|---|---|---|
| 版式留白 | `blank` | **没有** | 行首挪抬那几格、列末空格 | `kind="blank"`，`char=None` |
| 排除名单 | `char` | 有，`doubts` 含 `excluded` | 切坏的图块/墨污，**根本不是字** | `excluded=True` |
| 阙文 | `char` | 有，`admit=False and char is None` | 确实是字但认不出 | `unreadable=True` |

2026-09-11 用户核实 vol02 p1-20：最初版本把 excluded 也标成阙文 `[[]]`，
20 处里 19 处其实是 excluded。混成一件事会让「这一格本不该存在」和「这格是字
但认不出」读不出区别——前者不用管，后者要回 Step7 审。

## Step3 与 Step7 对不上的格（`stale`）不静默兜底

「Step7 有这个 (slot,sub) 但 Step3 cells 查不到」目前唯一已知成因是 Step3 局部
重切后下游没跟上（`guji status` 会把这页标成"过期"）。2026-09-11 实测 vol01 p89
col7 就是这样一个真实个例（全书 810 个夹注字位里只有它不匹配）。**不是 join
逻辑错，但也不该被悄悄吃掉**——追加进 `stale` 由调用方统一报告。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.spec import page_key
from ..errors import ProductMissing
from ..products.kinds.cells import CellRec, PageCells
from ..products.kinds.recog import AdmitRec, PageAdmit
from ..products.store import ProductStore
from ..utils.jiazhu_order import sort_by_reading

CELLS_STEP = "row_segment"
CELLS_KIND = "cells"
ADMIT_STEP = "seed_admit"
ADMIT_KIND = "seed_admit"


@dataclass
class SlotRec:
    """一个字位。`id` 是全管线通用主键 `book:page:col:slot[a|b]`，
    深链、金标、事件、比对报告都用它对齐。"""
    id: str
    page: int
    col: int
    slot: int
    sub: str | None
    kind: str                    # char | blank | jiazhu_a | jiazhu_b
    char: str | None             # 字形层；None = 阙文或 blank
    reading: str | None          # 文意读法；None = 与 char 相同
    admit: bool
    channel: str | None
    excluded: bool
    unreadable: bool
    human: bool                  # 人裁过（channel == "human"）
    doubts: list[str] = field(default_factory=list)

    @property
    def is_text(self) -> bool:
        """参与字符比对的位：blank 与 excluded 不参与（它们不是「一个字」）。
        阙文**参与**——版面上那里确实有字，只是认不出，漏掉它会让后面的字全部错位。"""
        return self.kind != "blank" and not self.excluded


def page_slots(store: ProductStore, book: str, page: int,
               stale: list[str] | None = None) -> list[SlotRec]:
    """一页的字位流，**按阅读顺序**（列升序，列内 `sort_by_reading`）。

    `stale`：Step7 有记录但 Step3 cells 查不到的条目，格式 `p{page}col{col}:slot{n}{a|b}`，
    追加进这个列表，不在这一层报告（见模块头）。
    """
    if stale is None:
        stale = []
    key = page_key(page)
    cells: PageCells | None = store.read(book, CELLS_STEP, key, CELLS_KIND)  # type: ignore[assignment]
    admit: PageAdmit | None = store.read(book, ADMIT_STEP, key, ADMIT_KIND)  # type: ignore[assignment]
    if admit is None:
        raise ProductMissing(f"{book} 第 {page} 页没有 {ADMIT_STEP} 产物（先跑到 Step7）")
    if cells is None:
        raise ProductMissing(f"{book} 第 {page} 页没有 {CELLS_STEP} 产物（先跑到 Step3）")

    cells_by_col: dict[int, dict[tuple[int, str], CellRec]] = {}
    for col_cells in cells.columns:
        cells_by_col[col_cells.col] = {(c.slot, c.sub or ""): c for c in col_cells.cells}

    out: list[SlotRec] = []
    for col_admit in sorted(admit.columns, key=lambda c: c.col):
        if not col_admit.ok or not col_admit.chars:
            continue
        by_key = cells_by_col.get(col_admit.col, {})
        for rec in sort_by_reading(col_admit.chars):
            cell = by_key.get((rec.slot, rec.sub or ""))
            if cell is None:
                stale.append(f"p{page}col{col_admit.col}:slot{rec.slot}{rec.sub or ''}")
            out.append(_to_slot(book, page, col_admit.col, rec, cell))
    return out


def _to_slot(book: str, page: int, col: int, rec: AdmitRec, cell: CellRec | None) -> SlotRec:
    excluded = "excluded" in (rec.doubts or [])
    # cell 查不到时按正文字处理（已记 stale），不猜它是夹注或 blank——
    # 猜错会让读序和夹注配对一起错，比少一格的后果大。
    kind = cell.kind if cell is not None else "char"
    return SlotRec(
        id=rec.id, page=page, col=col, slot=rec.slot, sub=rec.sub, kind=kind,
        char=rec.char, reading=rec.reading, admit=bool(rec.admit),
        channel=rec.channel, excluded=excluded,
        unreadable=(not rec.admit and rec.char is None and not excluded),
        human=(rec.channel == "human"),
        doubts=[d.split("(")[0] for d in (rec.doubts or [])],
    )


def blank_lead_count(store: ProductStore, book: str, page: int, col: int) -> int:
    """行首挪抬格数：从 `slot=1` 起、`sub=None` 连续多少个 `kind=="blank"`。

    **必须从 Step3 `cells` 数，不能从 Step7 `seed_admit` 数**——Step7 对 `blank`
    格根本不产出 `AdmitRec`（vol02 p0004 col3：cells 里 slot 1/2 是 blank，
    seed_admit 里最小的 slot 直接是 3），想在字位流里「顺便」数出来是死代码。
    所以这个量单开一个函数回查 Step3，不塞进 `SlotRec`。
    """
    cells: PageCells | None = store.read(book, CELLS_STEP, page_key(page), CELLS_KIND)  # type: ignore[assignment]
    if cells is None:
        return 0
    col_cells = next((c for c in cells.columns if c.col == col), None)
    if col_cells is None:
        return 0
    by_key = {(c.slot, c.sub or ""): c for c in col_cells.cells}
    n, slot = 0, 1
    while by_key.get((slot, "")) is not None and by_key[(slot, "")].kind == "blank":
        n += 1
        slot += 1
    return n
