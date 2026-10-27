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
      9-24: {pitch: 115}            # 列距先验（px）：列数按块宽自估、列按等宽网格拟合
      35-92: {pitch: [null, 143]}   # 逐块给；null = 这块不给
      113-123: {splits: [915]}      # 分栏的大约 y（原图像素）：吸到附近的栏线，没线就吸到两栏间的空白

`kind` 目前只有 `text`（缺省）与 `skip`。`cols`、`pitch` 都不给就全自估。
同一页落在几条里时逐字段合并：区间宽的先、窄的后，后写的字段盖前面的（区间给 pitch、单页再给 cols 都生效）。
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
    pitch: float | None = None


@dataclass
class PageHint:
    type: str = "body"
    cols: int | list[int] | None = None
    blocks: list[BlockHint] = field(default_factory=list)
    pitch: float | list[float | None] | None = None
    splits: list[float] | None = None              # 人标分栏的大约 y（栏线浅或根本没线时）

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

    def pitch_for(self, i: int) -> float | None:
        """第 i 个块的列距先验：blocks[i].pitch 优先，再看页级 pitch。"""
        if i < len(self.blocks) and self.blocks[i].pitch:
            return self.blocks[i].pitch
        if isinstance(self.pitch, list):
            return self.pitch[i] if i < len(self.pitch) and self.pitch[i] else None
        return self.pitch

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
    cols, pitch = d.get("cols"), d.get("pitch")
    return BlockHint(box=box, cols=None if cols is None else int(cols), kind=kind,
                     pitch=None if pitch is None else float(pitch))


def _num_or_list(v, cast):
    if isinstance(v, list):
        return [None if c is None else cast(c) for c in v]
    return None if v is None else cast(v)


def parse_layout_hints(raw) -> dict[int, PageHint]:
    """yaml 的 `layout_hints:` → {页号: PageHint}。形状不对在读配置时就报。"""
    if not raw:
        return {}
    out: dict[int, PageHint] = {}
    # 区间宽的先、窄的后：单页的提示盖在区间提示上（逐字段，没写的字段不动）
    for key, v in sorted(raw.items(), key=lambda kv: -len(_pages(kv[0]))):
        if isinstance(v, str):
            v = {"type": v}
        v = dict(v or {})
        typ = v.get("type")
        if typ is not None and str(typ) not in PAGE_TYPES:
            raise ValueError(f"layout_hints 第 {key} 页 type 只能是 {PAGE_TYPES}，写的是 {typ!r}")
        blocks = [_block(b) for b in (v.get("blocks") or [])]
        if any(b.box is not None for b in blocks) and not all(b.box is not None for b in blocks):
            raise ValueError(f"layout_hints 第 {key} 页：blocks 要么都给 box（人圈块），要么都不给（对自动块）")
        cols, pitch = _num_or_list(v.get("cols"), int), _num_or_list(v.get("pitch"), float)
        splits = v.get("splits")
        if splits is not None:
            if not isinstance(splits, list):
                raise ValueError(f"layout_hints 第 {key} 页 splits 要写成 y 的列表，写的是 {splits!r}")
            splits = [float(y) for y in splits]
        for p in _pages(key):
            old = out.get(p, PageHint())
            out[p] = PageHint(type=str(typ) if typ is not None else old.type,
                              cols=cols if cols is not None else old.cols,
                              blocks=blocks or old.blocks,
                              pitch=pitch if pitch is not None else old.pitch,
                              splits=splits if splits is not None else old.splits)
    return out
