"""管线重组方案 B 第一期（2026-11-03）：套书缺省参数、按套书选管线、可选上游缺席。"""

import pytest

from helpers import make_book
from open_guji_cv.core import seg_set as S
from open_guji_cv.core.engine import Engine
from open_guji_cv.core.pipeline import (Pipeline, base_param_layers, base_params, default_pipeline_id,
                                        list_pipelines, load_pipeline)
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore


def test_every_pipeline_yaml_loads():
    """守卫：哪条管线加载不了，`default_pipeline_id` 会把它吞掉、悄悄退回刻本链（modern_body 10-22～11-03 就是这样）。"""
    for pid in list_pipelines():
        load_pipeline(pid)


def test_pipeline_follows_seg_set():
    assert default_pipeline_id(make_book(seg_set="beixing")) == "modern_body"
    assert default_pipeline_id(make_book(seg_set="zengguang_youxue")) == "keben_free"
    assert default_pipeline_id(make_book(seg_set="shiji_wyg")) == "keben_body_v2"
    assert default_pipeline_id(make_book(edition="modern")) == "modern_body"
    assert default_pipeline_id(make_book()) == "keben_body_v2"
    # 旧写法 pipeline: 仍然优先
    assert default_pipeline_id(make_book(seg_set="beixing", pipeline="keben_body_v2")) == "keben_body_v2"


def test_every_seg_set_has_a_pipeline():
    assert set(S.SEG_SET_PIPELINE) == set(S.SEG_SETS)
    for pid in S.SEG_SET_PIPELINE.values():
        load_pipeline(pid)


def test_seg_set_defaults_replace_pipeline_params():
    pl = load_pipeline("modern_body")
    assert pl.params == {}                          # 搬到 impl/modern/defaults.yaml
    bp = base_params(pl, make_book(edition="modern"))
    assert bp["column_gate"] == {"count_mode": "detected", "width_tol": 0.5}
    assert bp["cell_shrink"] == {"frame_guard": False, "inner_frame_cut": False, "inner_frame_profile": False}
    assert bp["glyph_match"] == {"norm_stroke": 3, "exclude_self": True}
    names = [n for n, _ in base_param_layers(pl, make_book(edition="modern"))]
    assert names == ["管线 yaml", "套书缺省（beixing）"]
    assert base_params(load_pipeline("keben_body_v2"), make_book()) == {}


def test_run_pipeline_picks_seg_set_when_book_has_none():
    """CLI `--pipeline` 换了管线、册 yaml 没写 seg_set：缺省参数跟这趟跑的管线走。"""
    assert S.seg_set_for_run(make_book(), "modern_body") == "beixing"
    assert S.seg_set_for_run(make_book(seg_set="shiji_wyg"), "modern_body") == "shiji_wyg"
    assert S.seg_set_for_run(make_book(), None) == "siku_zongmu"


def test_book_params_over_seg_set_defaults(tmp_path):
    book = make_book(edition="modern", params={"cell_shrink": {"frame_guard": True},
                                               "glyph_match": {"norm_stroke": None}})
    eng = Engine(book, load_pipeline("modern_body"), store=ProductStore(tmp_path / "p"),
                 cache=ImageCache(tmp_path / "c"), log=lambda s: None)
    assert eng.ctx.params_for(STEPS["cell_shrink"]).frame_guard is True
    gm = eng.ctx.params_for(STEPS["glyph_match"])
    assert gm.norm_stroke == STEPS["glyph_match"].spec.params().norm_stroke   # null = 回 Step 默认
    assert gm.exclude_self is True
    assert eng.ctx.params_for(STEPS["column_gate"]).count_mode == "detected"


def test_bare_run_context_sees_seg_set_defaults(tmp_path):
    """不经 Engine 直接建的 RunContext（`guji cache get／warm`、控制台、审阅卡）与 Engine 取同一份参数：
    以前套书缺省整层丢掉，再生的列图、字块与跑步时出的不同（史記 r39 03:177:8:21b，2026-11-11）。"""
    from open_guji_cv.core.step import RunContext
    book = make_book(edition="modern", params={"cell_shrink": {"frame_guard": True},
                                               "glyph_match": {"norm_stroke": None}})
    eng = Engine(book, load_pipeline("modern_body"), store=ProductStore(tmp_path / "p"),
                 cache=ImageCache(tmp_path / "c"), log=lambda s: None)
    bare = RunContext(book, ProductStore(tmp_path / "p"), ImageCache(tmp_path / "c"), log=lambda s: None)
    assert bare.params_for(STEPS["column_gate"]).count_mode == "detected"          # 套书缺省
    assert bare.params_for(STEPS["cell_shrink"]).frame_guard is True                # 册配置压过套书缺省
    assert bare.params_for(STEPS["cell_shrink"]).inner_frame_cut is False           # 套书缺省
    for sid in STEPS:
        assert bare.params_for(STEPS[sid]).model_dump() == eng.ctx.params_for(STEPS[sid]).model_dump(), sid


def test_optional_upstream_absent_from_pipeline():
    pl = load_pipeline("modern_body")
    assert not pl.provides("seals")                 # cell_shrink 的可选上游，这条链没有生产者
    assert pl.provides("borders") and pl.provides("raw_page")


def test_hard_upstream_still_required():
    with pytest.raises(ValueError, match="cell_shrink"):
        Pipeline(id="t_bad", title="t", steps=["cell_shrink"]).validate()


def test_optional_upstream_in_wrong_order_still_rejected():
    """管线里有生产者却排在后面：仍报（只是整条链都没有生产者时才当缺席）。"""
    steps = list(load_pipeline("keben_body_v2").steps)
    steps.remove("seal_detect")
    steps.insert(steps.index("cell_shrink") + 1, "seal_detect")
    with pytest.raises(ValueError, match="seals"):
        Pipeline(id="t_order", title="t", steps=steps).validate()


# ── 方案 B 第二期：骨架 + 槽位 ──────────────────────────────────────────

import yaml

from open_guji_cv.core.pipeline import PIPELINES_DIR, SKELETON_ID, expand_slots

# 展开前写死在三个 yaml 里的步骤表（2026-11-03 之前）：展开结果必须逐项相同，各书产物目录与指纹才不动。
_COMMON_TAIL = ["cell_shrink", "glyph_match", "rare_candidates", "align_ref", "context_decide", "seed_admit"]
_EXPECT = {
    "keben_body_v2": ["page_survey", "invert_detect", "border_detect", "seal_detect", "column_warp", "row_segment", *_COMMON_TAIL],
    "modern_body": ["page_survey", "invert_detect", "line_detect", "column_crop", "row_segment_runs", *_COMMON_TAIL],
    "keben_free": ["page_survey", "invert_detect", "block_detect", "column_trace", "line_ocr", "cell_cut"],
}


@pytest.mark.parametrize("pid", sorted(_EXPECT))
def test_slot_expansion_keeps_step_lists(pid):
    assert load_pipeline(pid).steps == _EXPECT[pid]


def test_skeleton_is_not_a_pipeline():
    assert SKELETON_ID not in list_pipelines()
    assert sorted(list_pipelines()) == sorted(_EXPECT)


def _skeleton():
    return yaml.safe_load((PIPELINES_DIR / f"{SKELETON_ID}.yaml").read_text(encoding="utf-8"))


def test_expand_slots_errors():
    sk = _skeleton()
    with pytest.raises(ValueError, match="缺必填槽位"):
        expand_slots({"slots": {"layout": ["border_detect"]}}, sk)
    with pytest.raises(ValueError, match="没有的槽位"):
        expand_slots({"slots": {"layout": [], "columns": [], "cells": [], "layuot": []}}, sk)
    with pytest.raises(ValueError, match="列表"):
        expand_slots({"slots": {"layout": "border_detect", "columns": [], "cells": []}}, sk)


def test_chain_cannot_mix_steps_and_slots(tmp_path):
    (tmp_path / "_skeleton.yaml").write_text((PIPELINES_DIR / "_skeleton.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "t_mix.yaml").write_text("id: t_mix\nsteps: [page_survey]\nslots: {layout: [], columns: [], cells: []}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不能同时写"):
        load_pipeline("t_mix", tmp_path)


def test_every_chain_has_a_seg_set():
    """每条链至少被一套书的 SEG_SET_PIPELINE 指到，没有悬空的链 yaml。"""
    assert set(list_pipelines()) == set(S.SEG_SET_PIPELINE.values())
