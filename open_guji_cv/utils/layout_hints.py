"""人标的版面提示（册 yaml 的 `layout_hints:`），给自由版式管线 `keben_free` 用。

不追求全自动：特殊页由人先说「这页是什么版面、分几块、每块几列」，算法照着做。
没标的页全自动。写法（页号可写区间；坐标是原图像素、左上原点，与 `preclean:` 同）：

    layout_hints:
      1-3: skip                     # 整页不切（书衣、空白页）；等同 {type: skip}
      31: {cols: [12, 12]}          # 自动分出的块依次 12、12 列
      18: {cols: 12}                # 每个自动块都 12 列
      9:                            # 人圈块：给了 box 就不再自动分块，按列出的顺序读
        blocks:
          - {box: [60, 900, 1530, 2780], cols: 13}
          - {box: [60, 180, 1530, 880], kind: skip}   # 插图，不切
      40: {blocks: [{kind: skip}, {kind: skip}, {}]}  # 不给 box：按序对上自动块，前两块不切

`kind` 目前只有 `text`（缺省）与 `skip`。`cols` 不给就自估。
"""

from __future__ import annotations

from dataclasses import dataclass, field

PAGE_TYPES = ("body", "skip")
BLOCK_KINDS = ("text", "skip")


@dataclass
class BlockHint:
    box: tuple[int, int, int, int] | None = None     # x0, y0, x1, y1（原图像素，左上原点）
    cols: int | None = None
    kind: str = "text"


@dataclass
class PageHint:
    type: str = "body"
    cols: int | list[int] | None = None
    blocks: list[BlockHint] = field(default_factory=list)

    @property
    def manual_blocks(self) -> bool:
        return any(b.box is not None for b in self.blocks)

    def cols_for(self, i: int) -> int | None:
        """第 i 个块（从 0 起）的列数提示：blocks[i].cols 优先，再看页级 cols。"""
        if i < len(self.blocks) and self.blocks[i].cols:
            return self.blocks[i].cols
        if isinstance(self.cols, list):
            return self.cols[i] if i < len(self.cols) and self.cols[i] else None
        return self.cols

    def kind_for(self, i: int) -> str:
        return self.blocks[i].kind if i < len(self.blocks) else "text"


def _pages(key) -> list[int]:
    s = str(key).strip()
    if "-" in s:
        a, b = s.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(s)]


def _block(d) -> BlockHint:
    d = dict(d or {})
    kind = str(d.get("kind", "text"))
    if kind not in BLOCK_KINDS:
        raise ValueError(f"layout_hints 块 kind 只能是 {BLOCK_KINDS}，写的是 {kind!r}")
    box = d.get("box")
    if box is not None:
        if len(box) != 4:
            raise ValueError(f"layout_hints 块 box 要 4 个数 [x0, y0, x1, y1]，写的是 {box!r}")
        box = tuple(int(v) for v in box)
    cols = d.get("cols")
    return BlockHint(box=box, cols=None if cols is None else int(cols), kind=kind)


def parse_layout_hints(raw) -> dict[int, PageHint]:
    """yaml 的 `layout_hints:` → {页号: PageHint}。形状不对在读配置时就报。"""
    if not raw:
        return {}
    out: dict[int, PageHint] = {}
    for key, v in raw.items():
        if isinstance(v, str):
            v = {"type": v}
        v = dict(v or {})
        typ = str(v.get("type", "body"))
        if typ not in PAGE_TYPES:
            raise ValueError(f"layout_hints 第 {key} 页 type 只能是 {PAGE_TYPES}，写的是 {typ!r}")
        cols = v.get("cols")
        if isinstance(cols, list):
            cols = [None if c is None else int(c) for c in cols]
        elif cols is not None:
            cols = int(cols)
        hint = PageHint(type=typ, cols=cols, blocks=[_block(b) for b in (v.get("blocks") or [])])
        if hint.manual_blocks and not all(b.box is not None for b in hint.blocks):
            raise ValueError(f"layout_hints 第 {key} 页：blocks 要么都给 box（人圈块），要么都不给（对自动块）")
        for p in _pages(key):
            out[p] = hint
    return out
