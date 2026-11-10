"""大印压列时的印泥处理（书级钩子）的缺省实现：殿本不做，`row_segment` 照旧。

2026-11-10 从 `steps/row_segment.py` 搬出（Sheldon 定「先搬自成一块的」）：原书级开关 `seal_gap_slots_empty`、
`seal_inkcut` 只有史記文淵閣本（写本）开，实现搬进史記书仓 `code/seal_ink.py`（`code.yaml` 覆盖 `keben.seal_ink`）。
书配置里还写着这两个开关为 true、而本工作区 code/ 没覆盖本模块，`RowSegmentParams` 拒跑（见 `row_segment._RETIRED`）。

覆盖本模块的书级代码要给出下面同名的两样。
"""
from __future__ import annotations

#: 表首字与末字之间、表说空的格位落在印框里（`row_segment._in_seal`）也记空（`_blank_frame_junk` 的 `seal_gaps`）。
GAP_SLOTS_EMPTY: bool = False

#: 大印压着列首的列（`row_segment._under_stain`）先把印框行段里的印泥从列图里抹掉再挑格网：
#: `inkcut(img, rows: (y0, y1), ink_threshold: int, notes: bool) -> img`（只改切分用的列图）。None＝不剔。
inkcut = None
