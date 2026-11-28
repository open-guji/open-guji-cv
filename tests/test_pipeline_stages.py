"""四大步（2026-11-22）：骨架 `stages:` 把三条链的步骤分进 layout／cut／read／decide，
`--from/--to` 可写大步名。只是分组，不改步骤顺序。"""
from __future__ import annotations

import pytest

from open_guji_cv.core.pipeline import expand_stages, list_pipelines, load_pipeline

STAGES = ["layout", "cut", "read", "decide"]


@pytest.mark.parametrize("pid", list_pipelines())
def test_every_step_in_exactly_one_stage_in_order(pid):
    pl = load_pipeline(pid)
    assert list(pl.stages) == STAGES
    flat = [s for st in STAGES for s in pl.stages[st]]
    assert flat == pl.steps          # 每步恰好归一个大步，且大步首尾相接、顺序同管线


def test_keben_stage_members():
    pl = load_pipeline("keben_body_v2")
    assert pl.stages["layout"] == ["page_survey", "invert_detect", "border_detect", "seal_detect"]
    assert pl.stages["cut"] == ["column_warp", "column_band", "column_end", "column_geometry", "row_segment", "cell_shrink"]
    assert pl.stages["read"] == ["glyph_match", "glyph_near", "rare_candidates", "glyph_candidate", "cell_traits", "glyph_analyzer"]
    assert pl.stages["decide"] == ["align_ref", "context_decide", "context_rank", "cell_state", "seed_admit"]
    assert pl.stage_of("align_ref") == "decide"   # 整理本对位归 4 定字（2026-11-22 用户定）
    assert pl.stage_of("cell_shrink") == "cut"
    assert pl.stage_of("column_warp") == "cut"   # 拉直归 2 切字（2026-11-22 用户定）


def test_slice_by_stage_name():
    pl = load_pipeline("keben_body_v2")
    assert pl.slice("cut", "cut") == ["column_warp", "column_band", "column_end", "column_geometry", "row_segment", "cell_shrink"]
    assert pl.slice("layout", "cut")[-1] == "cell_shrink"
    assert pl.slice("read", None) == ["glyph_match", "glyph_near", "rare_candidates", "glyph_candidate", "cell_traits", "glyph_analyzer", "align_ref", "context_decide", "context_rank", "cell_state", "seed_admit"]
    assert pl.slice("row_segment", "read")[-1] == "glyph_analyzer"   # 步骤 id 与大步名可混用


def test_step_claimed_by_two_stages_rejected():
    sk = {"slots": {}, "stages": {"a": ["x"], "b": ["x"]}}
    with pytest.raises(ValueError, match="同时归大步"):
        expand_stages({}, sk, ["x"])
