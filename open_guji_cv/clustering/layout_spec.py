"""页面列布局的统一输出格式（行列识别的对外契约）。

为什么需要这个格式
------------------
原先版式识别只给一个标量 `chars_per_line`。它把两个**刚性程度完全不同**
的维度压成了一个数：

- **横向**（列数、列位置）：刚性。界行是物理刻在版上的，实测职名页与
  正文页的列间距一样规整（变异系数 1.4%~2.4%），全页共享一个周期。
- **纵向**（列内字的排布）：弹性。职名页官衔字拉开到 ~3.5 倍格高，
  长标题又被压缩到 ~0.5 倍，同一页里不同列可以完全不同。

一个标量既表达不了「这一列 21 字那一列 15 字」，也无法承载「这一列
根本不在网格上」。于是下游只能靠隐式回退（先试弹性切分、不行退回刚性），
判错了也无从发现——实测两册里有 77 列正文被误判成弹性、丢掉约 926 个
字位。本格式把这层判断**显式化**，使它可以被单独标注、单独评测。

判别定义（标注与评测共用，不得含糊）
------------------------------------
- `rigid`   字距 = 1×格高。判据是**字距**，不是字数也不是相位：
            · 只有几个字、后面全空 → 仍是 rigid（目录页大量如此）；
            · 抬头列（「上」「朝」「聖義」被抬到格线之上）整体相位偏移，
              但字距未变 → 仍是 rigid。相位偏移是另一个更易修正的问题，
              混进列型会让这个标签失去指导意义。
- `elastic` 字距 ≠ 1×格高。实测两种子型都存在且同样常见：
            · 拉开——职名官衔字距 ~3.5×（vol01/127 那类）；
            · 压缩——长标题挤进同列高，字距 ~0.5×（vol01/107 第 6 列
              23 字塞进 9 格那类）。

`n_chars`（有墨字位数，不含空位）为**可选**：本数据集的目标是列型判别，
逐列人工数字数成本过高且非必需，未标注时评测跳过字数指标。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1

# blank/uncertain 不是"第三种排版"，是标注状态：
#   blank     整列无字，谈不上落不落格 —— 评测时单独计，不混进分类指标
#   uncertain 人工也判不准（抬头错位、残损页）—— 评测时**跳过**，
#             宁可让样本少一点，也不能往金标里灌噪声
LAYOUTS = ("rigid", "elastic", "blank", "uncertain")
SCORED_LAYOUTS = ("rigid", "elastic")     # 只有这两类进分类指标
PAGE_CLASSES = ("body", "roster", "edict", "toc", "cover", "mixed")


@dataclass
class ColumnSpec:
    """一列的布局描述。"""
    index: int                 # 从右到左编号，1 = 最右列
    left_x: float
    right_x: float
    layout: str                # rigid | elastic | blank | uncertain
    n_chars: int | None = None  # 有墨字位数；金标可不标（见模块文档）

    def __post_init__(self) -> None:
        if self.layout not in LAYOUTS:
            raise ValueError(f"未知列型 {self.layout!r}，应为 {LAYOUTS}")


@dataclass
class PageLayout:
    """一页的列布局。横向参数在 grid，纵向逐列在 columns。"""
    book: str
    page: str
    image_size: dict           # {"width": int, "height": int}
    n_cols: int
    cell_h: float              # 书级格高（纵向刚性常量）
    columns: list[ColumnSpec] = field(default_factory=list)
    page_class: str | None = None
    edition_tag: str | None = None
    source_item: str | None = None
    pipeline_version: str | None = None
    label_origin: str | None = None      # human | heuristic | align
    schema_version: int = SCHEMA_VERSION

    # ── 派生量：不存盘，按需计算 ──────────────────────────

    @property
    def n_elastic(self) -> int:
        return sum(1 for c in self.columns if c.layout == "elastic")

    @property
    def scored_columns(self) -> list["ColumnSpec"]:
        """进入分类指标的列（排除空列与存疑列）。"""
        return [c for c in self.columns if c.layout in SCORED_LAYOUTS]

    def derived_page_class(self) -> str:
        """未显式标注时，由列型分布导出页型。空列不参与判定。"""
        scored = self.scored_columns
        if not scored:
            return "cover"
        n_e = sum(1 for c in scored if c.layout == "elastic")
        if n_e == 0:
            return "body"
        if n_e == len(scored):
            return "roster"
        return "mixed"

    # ── 序列化 ────────────────────────────────────────────

    def to_dict(self) -> dict:
        d = asdict(self)
        d["page_class"] = self.page_class or self.derived_page_class()
        return d

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=1),
            encoding="utf-8")

    @classmethod
    def from_dict(cls, d: dict) -> "PageLayout":
        d = dict(d)
        d.pop("schema_version", None)
        cols = [ColumnSpec(**c) for c in d.pop("columns", [])]
        return cls(columns=cols, **d)

    @classmethod
    def load(cls, path: str | Path) -> "PageLayout":
        return cls.from_dict(json.loads(
            Path(path).read_text(encoding="utf-8")))


def from_char_grid(grid: dict, book: str, page: str,
                   **meta) -> PageLayout:
    """phase3 网格 JSON → PageLayout（管线当前判断的快照）。

    列型取 `spread_col` 标记；有墨字位数取 type == "char" 的格数。
    这是**预测**，不是金标——金标由人工标注产生，两者用同一格式，
    才能直接逐列比对。
    """
    cols: list[ColumnSpec] = []
    for c in grid.get("columns", []):
        if c.get("skipped"):
            continue
        cells = c.get("cells", [])
        cols.append(ColumnSpec(
            index=int(c["index"]),
            left_x=float(c["left_x"]),
            right_x=float(c["right_x"]),
            layout="elastic" if c.get("spread_col") else "rigid",
            n_chars=sum(1 for x in cells if x.get("type") == "char"),
        ))
    cols.sort(key=lambda c: -c.index)
    return PageLayout(
        book=book, page=page,
        image_size=grid.get("image_size", {}),
        n_cols=len(cols),
        cell_h=float(grid.get("grid", {}).get("cell_h", 0.0)),
        columns=cols, **meta)
