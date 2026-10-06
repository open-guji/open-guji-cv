# -*- coding: utf-8 -*-
"""字位流：一页的定字结果按阅读顺序摊平成一串 `SlotRec`。

**9.1 排版与 9.3 比对共用这一份**——此前两边各有一套 join：
`render/guji_markdown.py::render_page`（出 `char`）与
`scripts/build_collation_report.py::page_slots`（出 `char`，未放行位退到
ctx/库/OCR 猜测）。同一页在「最终文本」里和「被比对的文本」里是两串不同的字，
比对报告说的每一条差异都未必指向最终文本里那个字。归一到这里。

## 取字规则（设计档 04 §三·1，两处分歧在此裁定）

- `char` ＝ **字形，照录图上的形**，排版与比对都以它为准（2026-09-26 起没有「读法」）；
- **未放行（`admit=False`）且不在排除名单上的位，`char` 一律 `None`，不退到库/
  OCR 猜测**。原型那样做的结果是 vol01 251 条「改」里 221 条是未审位的库 top1
  猜测——噪声盖过信号，而这些位本来就该由「未审阅数」这个指标去报，不该混进
  差异清单。调用方要显示时自行渲染成 `□`（比对）或 `[[]]`（9.1 的阙文记号）。
  **2026-09-27 前这条口径没有真的执行**：`seed_admit._pick_char()` 给人审卡
  用的 AI 猜测即便 `admit=False` 也写进 `AdmitRec.char`，本函数一度原样
  `char=rec.char` 搬了过去，让「机器自己也不确定」的位在 9.3 对勘里被当成了
  认错字（R 道 `R-形近溯源` 单查出 vol03 5 格皆属此类）。`_to_slot` 现在把
  这类猜测挪进 `guess` 字段，只给对勘锚定撑密度（`report/collate.py::
  _anchor_char`），不再冒充定论的 `char`。

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
    admit: bool
    channel: str | None
    excluded: bool
    unreadable: bool
    human: bool                  # 人裁过（channel == "human"）
    defect: bool = False         # 在排除名单上但**是字**（seg_defect/damaged，或人已给字）：占位，没给字出阙文；见 _to_slot
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
    # 名单上但人已给了字（Step7 `evidence.human_char`，overview#403 缺口 B）：字位占住、
    # 文本出人给的字；`defect=True` 留给下游知道图块有缺陷（文本里不带标记）。非字不算。
    human_char = (rec.evidence or {}).get("human_char") if on_list and reason != "not_a_char" else None
    if human_char:
        defect = True
    excluded = on_list and not defect
    # 印章／污损遮挡格（Step7 `occluded_gate`，overview#195）：不放行，但用户定「文本产物
    # 照常输出这个字」——`char` 是整理本的默认字（坐标对位优先），不是机器猜测，照出；
    # 坐标对位说这一位是空格（印章切出来的假格）的，当非字跳过，不占位。seed_admit 的印章区
    # 通道（`lane_seal`，overview#433）把这类格判成非字放行（`admit=True`、`char=None`），同样跳过。
    occ = (rec.evidence or {}).get("occluded") or None
    if occ and occ.get("ref_blank") and (not rec.admit or rec.char is None):
        excluded = True
    # cell 真查不到时（`_lookup_cell` 连单行小字注都没认出来）按正文字处理
    # （已记 stale），不猜它是夹注或 blank——猜错会让读序和夹注配对一起错，
    # 比少一格的后果大。
    kind = cell.kind if cell is not None else "char"
    admit = bool(rec.admit)
    char = rec.char
    guess = (rec.evidence or {}).get("guess") or None
    # 未放行、不在排除名单上的格：`rec.char` 是 `seed_admit._pick_char()` 给
    # 人审卡用的「AI 猜测」，`admit=False` 时也照写（人审 UI 要看它）。本层此前
    # 原样把它当成「这格定下来的字」搬进 `char`，9.3 对勘就把「机器自己也不
    # 确定」的位算成了认错字——本模块头早就定了「不退到库/OCR 猜测」的口径，
    # 这里之前没真的执行（2026-09-27 R 道溯源单查出：vol03 5 格全部 `admit=
    # False`，被对勘误记成 sub.confusable）。猜测挪进 `guess`：9.1 渲染看不到
    # 它（`unreadable=True` 时直接出 `[[]]`，走不到 `guess` 判断那一步，见
    # `render/guji_markdown.py::_char_text`），9.3 对勘的 8-gram 锚定还用得上
    # （`report/collate.py::_anchor_char`，保持锚定串密度不变，不降低锚定率）。
    # 排除名单（defect/excluded）不走这条——那两类的 `char` 已经是 Step7 自己
    # 给的占位（damaged 的 `□`、seg_defect 的 `None`），不是 `_pick_char` 的
    # 候选猜测，动它会破坏既有的阙文渲染（见 tests/test_slots_excluded_reason.py）。
    if not admit and not on_list and not (occ and char):
        guess = guess or char
        char = None
    if human_char:
        char = human_char
    return SlotRec(
        id=rec.id, page=page, col=col, slot=rec.slot, sub=rec.sub, kind=kind,
        char=char, admit=admit,
        channel=rec.channel, excluded=excluded, defect=defect,
        guess=guess,
        unreadable=(not admit and char is None and not excluded),
        human=(rec.channel == "human" or bool(human_char)),
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
