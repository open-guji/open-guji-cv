"""cells：Step3 单列文字切分的产物（numeric）。

坐标在**列图坐标**（COLUMN_PX，左上原点）；`quad_page` 是同一格四角经 Step2
逆映射回原图、再换算到规范空间 raw_page_px@top-right 的结果（没有映射时为 None）。
slot 编号：正文 1..n_body_slots，抬头格 -n_raised..-1，跳过 0；pos 是 1 起的物理位置。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_serializer

from ...core.spec import COLUMN_PX, ProductKindSpec
from ...core.step import register_kind

Point = tuple[float, float]


class CellRec(BaseModel):
    slot: int
    pos: int
    y0: float
    y1: float
    x0: float
    x1: float
    kind: str                      # char | blank | jiazhu_a | jiazhu_b | jiazhu_solo | punct（现代链）
    sub: str | None = None         # a / b / None（jiazhu_solo 也是 None：單行小注不配对，见 row_boundaries.CELL_KINDS）
    order: int
    gap_center: float | None = None
    ink_ratio: float = 0.0
    raised: bool = False
    suspect_jiazhu_body: bool = False      # 疑似被缝位骗过的整宽正文字（jiazhu_split.suspect_full_width_cells）
    quad_page: list[Point] | None = None   # 原图规范空间四角 [(x,y)…]，右上原点
    seam_top: list[int] | None = None      # 折线缝（列图坐标，每 x 一个 y，从 x0 起）；见 seg/seam.py
    seam_bottom: list[int] | None = None
    flags: list[str] = Field(default_factory=list)   # 现代链 row_segment_runs 的项级标记（small / tall / punct_absorbed）


class SeamCandidate(BaseModel):
    """一个「切点候选」在某个 char–char 相邻处的一条可选切线（列图坐标）。

    候选的单位是**切点**不是格位：一个切点同时决定 slot k 的下边界与 slot k+1 的上边界。
    所以候选挂在 `ColumnCells` 上，与 `boundaries` 对齐，而不是挂在 `CellRec` 上
    （那样同一组数据要存两份，且表达不了「同时动上下两格」）。
    """
    kind: str                      # straight | seam_narrow | seam_wide | unet_seam | period_up | period_dn（后三种 = L3 扩池，只在升级切点上出现）
    y: list[int] | None = None     # 折线逐列 y（从 content_x[0] 起）；straight 为 None
    seam_ink: int = 0              # 这条线穿过的墨量（下游打分可用，也便于审计）
    dev_max: int = 0               # 相对直线的最大偏移 px（0 = 与直线重合）
    agree: float | None = None     # U-Net 裁判的置信加权一致率 [0,1]（seg/cut_select.py）；没过裁判为 None
    dis_unet: int | None = None    # 与 U-Net 归属分歧的最大连通块 px（2026-09-15 L2′ 升级门槛看它）


class CutPointCandidates(BaseModel):
    """第 k 个切点（slot k 与 slot k+1 之间）的全部候选。

    `chosen` 是现役算法选中的下标；其余候选**留着不删**——它们是攒给下游打分函数的样本。
    """
    k: int                         # 切点序号，与 boundaries 对齐
    y: float                       # 直线位置（= boundaries[k]），便于下游不查表
    slot_above: int
    slot_below: int
    candidates: list[SeamCandidate] = Field(default_factory=list)
    chosen: int | None = None      # 现役选中的候选下标；None = 这个切点没有候选
    chosen_by: str | None = None   # 谁选的：rule（现役规则）| unet（裁判改选，2026-09-14 起）| human（裁决表收敛）
    escalate: bool = False         # L2′（2026-09-15）：所选切法与 U-Net 分歧块 ≥100px，本层拿不准，交下游再审；顺序闸按它出卡
    escalate_reason: str | None = None
    origin: str = "touching"       # touching（直线穿墨）| split_suspect（L0′：直线干净但一矮一高且矮格墨满，只为探针而建）


class ColumnCells(BaseModel):
    col: int
    ok: bool                       # segment_column 有解
    error: str | None = None
    n_body_slots: int
    n_raised: int = 0
    period: float | None = None
    ref_w: float | None = None
    content_x: tuple[float, float] | None = None
    border_top: float | None = None
    border_bottom: float | None = None
    top_slack: float = 0.0
    boundaries: list[float] = Field(default_factory=list)
    cells: list[CellRec] = Field(default_factory=list)
    cut_candidates: list[CutPointCandidates] = Field(default_factory=list)
    """直线格线穿墨的 char–char 相邻处的全部候选切线；不下传候选时为空。"""
    em: float | None = None            # 现代链：本列字身高估计
    pitch: float | None = None         # 现代链：本列字–字中心距
    flags: list[str] = Field(default_factory=list)   # 现代链列级标记（suspect_jiazhu / empty）


class PageCells(BaseModel):
    page: int
    period: float | None
    ref_w: float | None
    columns: list[ColumnCells]

    alt_columns: list[ColumnCells] = Field(default_factory=list)
    """备选切法（row_segment `alt_cut`，2026-11-03）：格位表与图不合的列另切一份不带先验的格网，Step4/5 照样裁、认，
    由 align_ref 坐标对位挑和整理本吻合多的那份（`PageAlignRef.alt_cols`）。不和 `columns` 混放——`.column(col)`
    只取第一个同号列。空表**不落盘**（见下），没开 `alt_cut` 的产物逐字节不变。"""

    @model_serializer(mode="wrap")
    def _drop_empty_alt(self, handler):
        d = handler(self)
        if isinstance(d, dict) and not d.get("alt_columns"):
            d.pop("alt_columns", None)
        return d

    def with_alt(self, cols):
        """把 `cols` 里列号的列换成备选那份的副本（align_ref 试算、seed_admit 取选中份共用）；`cols` 空就原样返回。"""
        cols = set(cols or ())
        if not cols:
            return self
        alt = {c.col: c for c in self.alt_columns}
        return self.model_copy(update={"columns": [alt.get(c.col, c) if c.col in cols else c for c in self.columns],
                                        "alt_columns": []})

    def column(self, col: int) -> ColumnCells | None:
        return next((c for c in self.columns if c.col == col), None)


CELLS = register_kind(ProductKindSpec(
    id="cells", title="Step3 字格", storage="numeric", unit="column",
    schema=PageCells, coord_space=COLUMN_PX))
