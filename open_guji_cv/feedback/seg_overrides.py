"""人定切分（列级、格级）的统一读取入口（A22，2026-11-12，Sheldon 定方案《切分三方向》第 4 步）。

总表、优先级与「该写哪种」见 `doc/切分覆盖.md`。本模块只做两件事：

1. 一处读齐本册的列级／格级人定切分（`feedback/lookup.py` 的各个 `resolved_*`），**按需读**：
   哪一项第一次被问到才去读那张表，所以职名页（只问 manual-cells）不会去读切线、事件日志，与改前同；
2. 把「同一列上几条都写了谁说了算」写在一处（`ColumnOverrides.blocks_layout`），`row_segment` 用。

和 `lookup` 一样：裁决内容不进产物指纹，靠交单从对应步骤重跑生效；但本模块的**代码**进 `row_segment` 的
`code_deps`（谁说了算的规则改了，产物要过期）。
页级的几何覆盖（`vline_overrides`、`hline_hints`、`page_kinds`…）是册配置参数，走参数层，不在这里。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

from . import lookup


@dataclass(frozen=True)
class ColumnOverrides:
    """一列上的人定切分。全空＝这一列没有人裁，算法照常切。

    优先级（`doc/切分覆盖.md` 第三节）：
    - `manual_cells` 非空：整列在切完后被替换，别的都不算数；
    - `head_raise`：抬头级数听它，格位表级数不同时表按它挪格号；
    - `blocks_layout`：有任一条格数／切线／钉线／小注强制，这一列整列不用格位表（连 `cuts`）——人裁按格号记，表一改格数格号就对不上。
    """
    manual_cells: list[dict] | None = None
    head_raise: int | None = None
    slots: "lookup.ResolvedColumn | None" = None
    cuts: dict[int, "lookup.ResolvedCut"] = field(default_factory=dict)
    """slot_above → 收敛到的候选（touching-cuts 的 cand／ok／seam_ok）。"""
    pins: dict[int, float] = field(default_factory=dict)
    """slot_above → 人拖过或认可过的线（当前列图 y）。"""
    solo: frozenset[int] = frozenset()
    forced_jiazhu: frozenset[int] = frozenset()
    forced_main: frozenset[int] = frozenset()

    @property
    def blocks_layout(self) -> bool:
        return (self.slots is not None or bool(self.cuts) or bool(self.pins) or bool(self.solo)
                or bool(self.forced_jiazhu) or bool(self.forced_main))

    @property
    def empty(self) -> bool:
        return self.manual_cells is None and self.head_raise is None and not self.blocks_layout


class SegOverrides:
    """一册的列级／格级人定切分。`SegOverrides(book, store=ctx.store)`，每次 `run_page` 新建一个（同改前每页读一次）。

    字典属性（`manual_cells`、`head_raise`、`slots`、`cuts`、`pins`、`solo`、`forced_jiazhu`、`forced_main`）
    与对应 `lookup.resolved_*` 的返回值逐项相同，第一次访问时才读。"""

    def __init__(self, book: str, store=None, log=None):
        self.book = book
        self._store = store
        self._log = log

    @cached_property
    def manual_cells(self) -> dict[tuple[int, int], list[dict]]:
        return lookup.resolved_manual_cells(self.book)

    @cached_property
    def cuts(self) -> dict[tuple[int, int, int], "lookup.ResolvedCut"]:
        return lookup.resolved_cuts(self.book)

    @cached_property
    def slots(self) -> dict[tuple[int, int], "lookup.ResolvedColumn"]:
        return lookup.resolved_slots(self.book)

    @cached_property
    def solo(self) -> dict[tuple[int, int], set[int]]:
        return lookup.resolved_solo_notes(self.book)

    @cached_property
    def forced_jiazhu(self) -> dict[tuple[int, int], set[int]]:
        return lookup.resolved_forced_jiazhu(self.book, self._log)

    @cached_property
    def forced_main(self) -> dict[tuple[int, int], set[int]]:
        return lookup.resolved_forced_main(self.book, self._log)

    @cached_property
    def head_raise(self) -> dict[tuple[int, int], int]:
        return lookup.resolved_head_raise(self.book)

    @cached_property
    def pins(self) -> dict[tuple[int, int, int], float]:
        return lookup.resolved_pins(self.book, self._store)

    def page_manual(self, page: int) -> dict[int, list[dict]]:
        """本页的整列钉子：`col → cells`。"""
        return {k[1]: v for k, v in self.manual_cells.items() if k[0] == page}

    def column(self, page: int, col: int) -> ColumnOverrides:
        key = (page, col)
        return ColumnOverrides(
            manual_cells=self.manual_cells.get(key),
            head_raise=self.head_raise.get(key),
            slots=self.slots.get(key),
            cuts={s: k for (pg, c, s), k in self.cuts.items() if pg == page and c == col},
            pins={s: y for (pg, c, s), y in self.pins.items() if pg == page and c == col},
            solo=frozenset(self.solo.get(key) or ()),
            forced_jiazhu=frozenset(self.forced_jiazhu.get(key) or ()),
            forced_main=frozenset(self.forced_main.get(key) or ()),
        )
