"""切字旧评测集里已经跑不起或量的东西已不存在的，登记成 deprecated（CV2，bench 统一接口 P1，2026-11-28）。

登记了同名 bench，manager 的老评测器清单就不再列它，`guji bench list` 显示 deprecated 与理由，`run` 报 no_gold。
金标分片留在测试集仓不删（留档）。盘点见 ai-team `domain/CV/A22/bench盘点-2026-11-28.md`。

其余旧切分集（column_warp、side_rule、text_band、column_counts、seam、char_drop、truncation、jiazhu_tail、
frame_strip、instance_quality、recrop、touching_cuts）金标只有殿本（touching_cuts 另有北行），仍经老评测器适配照跑，
等在殿本上实跑核过再决定接成原生还是 deprecated。
"""
from __future__ import annotations

from pathlib import Path

from ..bench import BenchCtx, BenchResult, BenchSpec, register


def _gone(ctx: BenchCtx) -> Path:
    raise RuntimeError("deprecated bench，不跑")


def _none(ctx: BenchCtx, pred: Path) -> BenchResult:
    raise RuntimeError("deprecated bench，不跑")


_DEPRECATED = {
    # id: (分片, 量哪步, 理由)
    "page_crop": ("char-segmentation/page-crop", "旧 s3 裁页", "评测脚本 eval_page_crop.py 已不存在；现行管线不再裁页"),
    "crop_margin": ("char-segmentation/crop-margin", "旧 s3 裁边", "现行管线不再裁页；要 v1 中间产物（intermediate）"),
    "left_cut": ("char-segmentation/left-cut", "左缘救援", "评测脚本 eval_left_cut.py 已不存在；左右切点现由 2b 字带、cut-2b-band 量"),
    "right_cut": ("char-segmentation/right-cut", "右缘救援", "评测脚本 eval_right_cut.py 已不存在；同 left_cut"),
    "row_boundaries": ("char-segmentation/row-boundaries", "格线逐像素", "测试集已标退役（旧链路坐标系，2 页试点）；2d 格线由 cut-2d 量"),
    "column-split": ("border-detection/column-split", "界行落在字缝上（页级人裁）",
                     ("09-02 一轮页级人裁（殿本旧图源 60 页），裁的是当时 detect_borders 的结果、不带坐标，"
                     "评不了现行算法；列边对不对由 cut-2d（格四边形）、cut-gate 量。CV1 11-28 转来，CV2 定 deprecated")),
}

for _id, (_shard, _what, _why) in _DEPRECATED.items():
    register(BenchSpec(id=_id, title=f"（旧）{_what}", steps=(), owner="CV2", gold={}, needs=(), primary="",
                       run=_gone, score=_none, deprecated=_why))
