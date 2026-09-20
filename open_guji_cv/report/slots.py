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
| 排除名单·非字 | `char` | 有，`doubts` 含 `excluded`，`evidence.excluded` 理由 `not_a_char` | 墨污/切坏图块，**根本不是字** | `excluded=True`，跳过不占位 |
| 排除名单·切坏/残 | `char` | 有，理由 `seg_defect` / `damaged` | **字确实在这儿**，只是图块不能进库 | `defect=True`，占位，出阙文（damaged 由 Step7 给 `□`） |
| 阙文 | `char` | 有，`admit=False and char is None` | 确实是字但认不出 | `unreadable=True` |

排除名单按理由分两路是 2026-09-20 bxgb 对勘查出来的：155 条名单里 131 条是 seg_defect
（人裁 truncated/contaminated），此前一律当非字跳过，「舉手一揖」的 手、「十一月」的 月
都从文本里消失，对勘报成 129 条「整理本有刻本无」、80 条正落在这些格上。

另有**單行小注** `kind="jiazhu_solo"`（Step3 1.11 起，`row_boundaries.CELL_KINDS`）：
小字只占右半、左半空着，`sub=None`，与 Step7 的记录按 `(slot, "")` 直接对上；
9.1 出不带 `|` 的 `<注>`。

2026-09-11 用户核实 vol02 p1-20：最初版本把 excluded 也标成阙文 `[[]]`，
20 处里 19 处其实是 excluded。混成一件事会让「这一格本不该存在」和「这格是字
但认不出」读不出区别——前者不用管，后者要回 Step7 审。

## Step3 与 Step7 对不上的格（`stale`）不静默兜底

「Step7 有这个 (slot,sub) 但 Step3 cells 查不到」已知**两种**成因，别当成一种：

1. **單行小注的旧记法**（`_lookup_cell` 认回来，**不记 stale**）：`【正己】`这类只占
   半列、左半没字的人名注，Step3 ≤1.10 借 `jiazhu_a` 的壳记 `sub='a'`，而 Step7
   按「一个字」记 `sub=None`。2026-09-19 实测 bxgb：78 条假 stale 全是这一型，
   100% 无例外；vol02 零例。**Step3 1.11 起它自成 `jiazhu_solo`、`sub=None`，
   直接对上**——这条兜底只为 1.11 前写出的产物留着，bxgb 从 Step3 重跑过之后可删。
2. **产物过期**：Step3 局部重切后下游没跟上（`guji status` 会把这页标成"过期"）。
   2026-09-11 实测 vol01 p89col7 是这样一个真实个例（全书 810 个夹注字位里只有它）。

只有第 2 种才追加进 `stale` 由调用方报告——**不是 join 逻辑错，但也不该被悄悄
吃掉**。两种混报的代价是实打实的：报"产物过期"会让人去重跑 Step7，跑完一条
不少，白费一轮。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.spec import page_key
from ..errors import ProductMissing
from ..products.kinds.cells import CellRec, PageCells
from ..products.kinds.recog import AdmitRec, PageAdmit
from ..products.store import ProductStore
from ..utils.jiazhu_order import sort_by_reading

CELLS_STEP = "row_segment"          # 刻本链的产出者；现代链是 row_segment_runs，见 cells_step()
CELLS_KIND = "cells"
ADMIT_STEP = "seed_admit"
ADMIT_KIND = "seed_admit"


def cells_step(book: str) -> str:
    """这册书的 `cells` 是哪一步产的。

    同一种产物在两条链上由不同的 Step 产出（刻本 `row_segment` / 现代印刷
    `row_segment_runs`），管线里本来就有 `Pipeline.producer_of` 负责这件事
    （三模式方案「地基 2」）。Step9 不进管线、自己读产物，所以要自己查一次——
    写死 `row_segment` 会让现代印刷本在 9.1 直接报「没有 Step3 产物」
    （2026-09-15 北行日錄实测）。查不出来就退回刻本链那个，行为不变。
    """
    try:
        from ..core.book import load_book
        from ..core.pipeline import default_pipeline_id, load_pipeline
        bk = load_book(book)
        producer = load_pipeline(default_pipeline_id(bk)).producer_of(CELLS_KIND)
        if producer is not None:
            return producer.spec.id            # producer_of 给的是 Step 对象，id 在 spec 上
    except Exception:
        pass
    return CELLS_STEP


@dataclass
class SlotRec:
    """一个字位。`id` 是全管线通用主键 `book:page:col:slot[a|b]`，
    深链、金标、事件、比对报告都用它对齐。"""
    id: str
    page: int
    col: int
    slot: int
    sub: str | None
    kind: str                    # char | blank | jiazhu_a | jiazhu_b | jiazhu_solo
    char: str | None             # 字形层；None = 阙文或 blank
    reading: str | None          # 文意读法；None = 与 char 相同
    admit: bool
    channel: str | None
    excluded: bool
    unreadable: bool
    human: bool                  # 人裁过（channel == "human"）
    defect: bool = False         # 在排除名单上但**是字**（seg_defect/damaged）：占位，文本出阙文；见 _to_slot
    guess: str | None = None     # damaged 格人给的「最像哪个字」（Step7 evidence.guess），9.1 出 □{guess=X}
    doubts: list[str] = field(default_factory=list)

    @property
    def is_text(self) -> bool:
        """参与字符比对的位：blank 与 excluded 不参与（它们不是「一个字」）。
        阙文**参与**——版面上那里确实有字，只是认不出，漏掉它会让后面的字全部错位。"""
        return self.kind != "blank" and not self.excluded


def page_slots(store: ProductStore, book: str, page: int,
               stale: list[str] | None = None) -> list[SlotRec]:
    """一页的字位流，**按阅读顺序**（列升序，列内 `sort_by_reading`）。

    `stale`：Step7 有记录但 Step3 cells 真查不到的条目，格式
    `p{page}col{col}:slot{n}{a|b}`，追加进这个列表，不在这一层报告（见模块头）。
    **单行小字注那一型不算 stale**，由 `_lookup_cell` 认回来，见那个函数。
    """
    if stale is None:
        stale = []
    key = page_key(page)
    step = cells_step(book)
    cells: PageCells | None = store.read(book, step, key, CELLS_KIND)  # type: ignore[assignment]
    admit: PageAdmit | None = store.read(book, ADMIT_STEP, key, ADMIT_KIND)  # type: ignore[assignment]
    if admit is None:
        raise ProductMissing(f"{book} 第 {page} 页没有 {ADMIT_STEP} 产物（先跑到 Step7）")
    if cells is None:
        raise ProductMissing(f"{book} 第 {page} 页没有 {step} 产物（先跑到 Step3）")

    cells_by_col: dict[int, dict[tuple[int, str], CellRec]] = {}
    for col_cells in cells.columns:
        cells_by_col[col_cells.col] = {(c.slot, c.sub or ""): c for c in col_cells.cells}

    out: list[SlotRec] = []
    for col_admit in sorted(admit.columns, key=lambda c: c.col):
        if not col_admit.ok or not col_admit.chars:
            continue
        by_key = cells_by_col.get(col_admit.col, {})
        for rec in sort_by_reading(col_admit.chars):
            cell = _lookup_cell(by_key, rec)
            if cell is None:
                stale.append(f"p{page}col{col_admit.col}:slot{rec.slot}{rec.sub or ''}")
            out.append(_to_slot(book, page, col_admit.col, rec, cell))
    return out


def _lookup_cell(by_key: dict[tuple[int, str], CellRec], rec: AdmitRec) -> CellRec | None:
    """`(slot, sub)` 找 Step3 的格；找不到时认一次**旧记法的單行小注**再放弃。

    **过渡兜底，只对 Step3 ≤1.10 写出的产物有用。** 那时單行小注（`【正己】`这类
    人名注，只占半列、左半没字）借 `jiazhu_a` 的壳记 `sub='a'`，而 Step7 按「这就是
    一个字」记 `sub=None`，`(slot,'')` 查空，2026-09-19 实测 bxgb 报 78 条假 stale。
    1.11 起 Step3 直接发 `kind="jiazhu_solo"`、`sub=None`，第一行 `by_key.get` 就
    命中，走不到下面。bxgb 从 Step3 重跑过、旧产物洗掉之后，这段可以删。

    回查规则：`sub=None` 查不到就回查 `(slot,'a')`，且**仅当该 slot 没有 `b` 半**
    ——有 b 半说明是真双行夹注，Step7 少了半边那是另一回事，不能混进来当正常情况
    吃掉。认回来之后 `_to_slot` 拿 `cell.kind`（`jiazhu_a`）定 kind，9.1 照旧路径出
    `<…>`（不带 `|`，因为没有 b）。
    """
    cell = by_key.get((rec.slot, rec.sub or ""))
    if cell is not None or rec.sub:
        return cell
    if (rec.slot, "b") in by_key:
        return None                      # 真双行夹注缺了半边，是真不匹配
    return by_key.get((rec.slot, "a"))


def _to_slot(book: str, page: int, col: int, rec: AdmitRec, cell: CellRec | None) -> SlotRec:
    on_list = "excluded" in (rec.doubts or [])
    # 排除名单要按**理由**分两路（2026-09-20 bxgb 对勘查出来的）：
    #   not_a_char（非字：墨污/切坏图块）→ 这一格本不存在，跳过不占位；
    #   seg_defect / damaged（切坏、带残留、原刻残）→ **字确实在这儿**，只是图块
    #   不能进库；字位必须占住，文本层出阙文（damaged 的 □ 由 Step7 给）。
    # 此前一律按「非字」跳过——bxgb 155 条名单里 131 条是 seg_defect（人裁
    # truncated/contaminated：「舉手一揖」的 手、「十一月」的 月、「縉雲」的 縉），
    # 全被 9.1 吃掉，对勘报成 129 条「整理本有刻本无」，80 条正落在这些格上。
    # 与 Step7 给 damaged 占位的理由同一条（cv-segmentation §九 逐列对账）。
    # 老产物没有 evidence（Step7 早期）→ 按原来的口径当非字。
    reason = str((rec.evidence or {}).get("excluded", "")).split(":")[-1]
    defect = on_list and reason in ("seg_defect", "damaged")
    excluded = on_list and not defect
    # cell 真查不到时（`_lookup_cell` 连单行小字注都没认出来）按正文字处理
    # （已记 stale），不猜它是夹注或 blank——猜错会让读序和夹注配对一起错，
    # 比少一格的后果大。
    kind = cell.kind if cell is not None else "char"
    return SlotRec(
        id=rec.id, page=page, col=col, slot=rec.slot, sub=rec.sub, kind=kind,
        char=rec.char, reading=rec.reading, admit=bool(rec.admit),
        channel=rec.channel, excluded=excluded, defect=defect,
        guess=((rec.evidence or {}).get("guess") or None),
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
