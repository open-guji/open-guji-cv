# -*- coding: utf-8 -*-
"""第四步 4c `cell_state`（CV4 P3b，2026-11-28）：探测器与收尾读产物的等价、格况分类、产物回环、参数摘要守卫。自造数据。"""
from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest

import open_guji_cv.feedback.lookup as lookup
import open_guji_cv.steps  # noqa: F401
from helpers import make_book, page_align_ref, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.kinds.cell_state import CELL_STATES, PageCellState
from open_guji_cv.products.kinds.chars import CharRec, ColumnChars, PageChars
from open_guji_cv.products.kinds.gate import GateManifest
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps import cell_state as cs
from open_guji_cv.steps import occlusion, seed_admit_cell_state as scs
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


def test_default_off_and_registered():
    spec = STEPS["cell_state"].spec
    assert spec.enabled_by == "enabled" and cs.CellStateParams().enabled is False
    assert "cell_state" in spec.produces
    assert "cell_state" in STEPS["char_decide"].spec.optional_consumes
    from open_guji_cv.core.pipeline import load_pipeline
    assert "cell_state" in load_pipeline("keben_body_v2").steps


def test_classify_priority_and_states():
    occ = (0.7, "山", "coord")
    assert cs.classify(occ=None, seal_blank=False, seg=[], ink=set(), half=False, ref_blank=False)[0] == "char"
    assert cs.classify(occ=occ, seal_blank=False, seg=["tall"], ink=set(), half=False, ref_blank=False)[0] == "occluded"
    assert cs.classify(occ=(0.7, None, "coord_blank"), seal_blank=False, seg=[], ink=set(), half=False, ref_blank=True)[0] == "seal"
    assert cs.classify(occ=None, seal_blank=True, seg=["tall"], ink=set(), half=False, ref_blank=False)[0] == "seal"
    assert cs.classify(occ=None, seal_blank=False, seg=[], ink={"ink_seal", "ink_speck"}, half=False, ref_blank=False)[0] == "seal"
    assert cs.classify(occ=None, seal_blank=False, seg=["speck"], ink={"ink_speck"}, half=False, ref_blank=True)[0] == "seg_bad"
    assert cs.classify(occ=None, seal_blank=False, seg=[], ink={"ink_speck"}, half=False, ref_blank=True)[0] == "non_char"
    assert cs.classify(occ=None, seal_blank=False, seg=[], ink={"ink_speck"}, half=True, ref_blank=True)[0] == "seg_bad"
    assert cs.classify(occ=None, seal_blank=False, seg=[], ink={"ink_speck"}, half=False, ref_blank=False)[0] == "seg_bad"
    assert {"char", "seal", "occluded", "seg_bad", "non_char"} <= set(CELL_STATES)


def test_seed_fields_cover_detector_params():
    """探测器读到的 `p.xxx`（凡是 SeedAdmitParams 的字段）都必须在 SEED_FIELDS 里，否则改了它本步产物不过期。"""
    fields = set(SeedAdmitParams.model_fields)
    used: set[str] = set()
    for mod, names in ((scs, ("_occluded", "_lib_reads_char", "_manual_seal_cells", "header_formula_lines", "seg_box_bad",
                              "ink_mark_facts", "jiazhu_uneven_spans")),
                       (occlusion, ("page_occluded", "page_seal_blank", "_drop_clean_cells"))):
        for n in names:
            tree = ast.parse(inspect.getsource(getattr(mod, n)).lstrip())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "p":
                    used.add(node.attr)
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                        and isinstance(node.args[0], ast.Name) and node.args[0].id == "p" and isinstance(node.args[1], ast.Constant)):
                    used.add(node.args[1].value)
    from open_guji_cv.steps.seed_admit_params import _CONSTANTS, _RETIRED
    missing = {u for u in used if u in fields} - set(cs.SEED_FIELDS)
    assert not missing, f"探测器读了但 SEED_FIELDS 没列：{missing}"
    assert not {u for u in used if u not in fields and u not in _CONSTANTS and u not in _RETIRED}, "探测器读了既不是字段也不是常量的东西"
    assert set(cs.SEED_FIELDS) <= fields, "SEED_FIELDS 列了不存在的字段"


def test_product_roundtrip_restores_detector_shapes():
    st = PageCellState(
        page=1, ran=["occluded", "seal_blank", "ink", "jiazhu_uneven", "header_formula", "seg_box"],
        occluded={"a:1:1:2": [0.5, None, "coord_blank"], "a:1:1:3": [0.9, "山", "coord"]},
        seal_blank=[{"col": 1, "slot": 2, "sub": "", "seal_score": 0.8, "overlap": 0.9}],
        ink_flags={"a:1:1:2": ["ink_seal"]}, speck_half=["a:1:1:4"],
        jiazhu_uneven={"3": [[2, 5], [7, 8]]}, header_lines={"3": "本紀第十一"}, seg_box={"a:1:1:5": ["tall"]})
    back = PageCellState.model_validate_json(st.model_dump_json())
    assert back.occluded_map() == {"a:1:1:2": (0.5, None, "coord_blank"), "a:1:1:3": (0.9, "山", "coord")}
    assert back.seal_blank_map() == {(1, 2, ""): {"seal_score": 0.8, "overlap": 0.9}}
    assert back.ink_facts() == ({"a:1:1:2": {"ink_seal"}}, {"a:1:1:4"})
    assert back.uneven_spans() == {3: [(2, 5), (7, 8)]} and back.header_line_map() == {3: "本紀第十一"}
    assert back.seg_box == {"a:1:1:5": ["tall"]}


# ── 端到端：收尾读产物与自己现算逐格相同 ────────────────────────────────────
def _box(slot, flags=(), h=90):
    return CharRec(id=f"{BOOK}:{PAGE}:{COL}:{slot}", slot=slot, pos=slot, idx=slot - 1, cell_type="char",
                   bbox_col=(0, 100 * (slot - 1), 90, 100 * (slot - 1) + h), bbox_page=(0, 100 * (slot - 1), 90, 100 * (slot - 1) + h),
                   height=h, width=90, flags=list(flags))


def _dot(slot):
    y = 100 * (slot - 1) + 35
    return _box(slot, ["ink_speck"]).model_copy(update={"bbox_page": (35, y, 55, y + 20), "width": 20, "height": 20})


def _ctx(tmp_path, monkeypatch, sa_params, cs_params=None):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    monkeypatch.setattr(lookup, "human_chars", lambda book, log=None, stale=None, bind=None, lost=None: {})
    params = {"char_decide": sa_params}
    if cs_params is not None:
        params["cell_state"] = cs_params
    return RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache), params=params, log=lambda s: None)


def _fill(ctx, boxes, ref_slots):
    chars = {1: "山", 2: "水", 3: "木", 4: "火", 5: "金"}
    recs = [dict(slot=s, verdict="same", cov=1.0, wmax=0.0, char=c, candidates=[(c, 1.0)]) for s, c in chars.items()]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=s, align_char=chars[s]) for s in ref_slots], col=COL))
    write_product(ctx, "cut_gate", PAGE, gate_manifest=GateManifest(
        page=PAGE, admitted=True, period=100.0, ref_w=90.0, column_widths=[90.0], median_width=90.0, columns=[]))
    write_product(ctx, "cell_shrink", PAGE, char_index=PageChars(page=PAGE, columns=[
        ColumnChars(col=COL, ok=True, n_instances=len(boxes), chars=boxes)]))


def _cells(page):
    return {r.id: r.model_dump() for cc in page.columns for r in cc.chars}


@pytest.mark.usefixtures("seed_admit_switches_off")
@pytest.mark.parametrize("params", [
    dict(ink_marks=True),
    dict(ink_marks=True, seg_box_check=("tall", "frame_line", "speck", "split_pair")),
    dict(seg_box_check=("tall", "frame_line", "speck", "split_pair")),
    dict(),
])
def test_finale_same_with_and_without_cell_state(tmp_path, monkeypatch, params):
    params = SeedAdmitParams(**params)       # 要在 seed_admit_switches_off 生效后再造
    boxes = [_box(1), _box(2, ["ink_seal"]), _dot(3), _dot(4), _box(5, h=200)]
    ctx = _ctx(tmp_path / "a", monkeypatch, params)
    _fill(ctx, boxes, [1, 4, 5])
    inline = STEPS["char_decide"].run_page(ctx, PAGE)["char_decide"]

    params = params.model_copy(update={"cell_state_read": True})
    ctx2 = _ctx(tmp_path / "b", monkeypatch, params, cs.CellStateParams(enabled=True))
    _fill(ctx2, boxes, [1, 4, 5])
    st = STEPS["cell_state"].run_page(ctx2, PAGE)["cell_state"]
    write_product(ctx2, "cell_state", PAGE, cell_state=st)
    assert STEPS["cell_state"].spec.produces == ("cell_state",)
    via = STEPS["char_decide"].run_page(ctx2, PAGE)["char_decide"]
    assert _cells(via) == _cells(inline)
    assert (via.n_auto, via.n_review) == (inline.n_auto, inline.n_review)
    by = st.by_id()
    if params.ink_marks:
        assert by[f"{BOOK}:{PAGE}:{COL}:2"].state == "seal"
        # 对位无字的孤立墨点：只开墨迹记号是 non_char；字框几何闸也开着时它同时是 `speck` 判据，seg_bad 排在前
        assert by[f"{BOOK}:{PAGE}:{COL}:3"].state == ("seg_bad" if params.seg_box_check else "non_char")
        assert by[f"{BOOK}:{PAGE}:{COL}:4"].state == "seg_bad"         # 对位有字的墨点
        assert "ink" in st.ran
    if params.seg_box_check:
        assert by[f"{BOOK}:{PAGE}:{COL}:5"].state == "seg_bad" and "seg_box" in st.ran
    assert by[f"{BOOK}:{PAGE}:{COL}:1"].state == "char"


@pytest.mark.usefixtures("seed_admit_switches_off")
def test_detectors_follow_switches(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, SeedAdmitParams(occluded_gate=False, seal_blank_page=False, lane_seal=False),
               cs.CellStateParams(enabled=True))
    _fill(ctx, [_box(1), _box(2)], [1])
    st = STEPS["cell_state"].run_page(ctx, PAGE)["cell_state"]
    assert st.ran == ["jiazhu_uneven"]           # 开关全关：只有无开关的列旗探测器
    assert all(c.state == "char" for c in st.cells)


def test_book_params_fills_seed_digest(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, SeedAdmitParams(seg_box_check=("tall",)), cs.CellStateParams(enabled=True))
    p = STEPS["cell_state"].book_params(cs.CellStateParams(enabled=True), ctx)
    assert p.seed["seg_box_check"] == ("tall",) or list(p.seed["seg_box_check"]) == ["tall"]
    assert set(p.seed) <= set(cs.SEED_FIELDS)
    off = STEPS["cell_state"].book_params(cs.CellStateParams(), ctx)
    assert off.seed == {}


def test_run_page_does_not_shadow_cstate():
    """bench 抓到过：run_page 里夹注分支用 `cs` 当临时集合，曾把读 cell_state 产物的变量盖掉（史記 03 夹注页整页失败）。"""
    import textwrap
    from open_guji_cv.steps.seed_admit import SeedAdmitStep
    tree = ast.parse(textwrap.dedent(inspect.getsource(SeedAdmitStep._run_page)))
    stores = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "cstate" and isinstance(n.ctx, ast.Store)]
    assert len(stores) == 1


@pytest.mark.usefixtures("seed_admit_switches_off")
def test_cell_state_read_switch_semantics(tmp_path, monkeypatch):
    """`cell_state_read` 关：产物在也不读（一律现算）；开：读产物，产物里没有的探测器现算并计数。"""
    base = SeedAdmitParams(seg_box_check=("tall", "frame_line", "speck", "split_pair"))
    boxes = [_box(1), _box(2), _box(3)]
    ctx = _ctx(tmp_path, monkeypatch, base, cs.CellStateParams(enabled=True))
    _fill(ctx, boxes, [1, 2, 3])
    st = STEPS["cell_state"].run_page(ctx, PAGE)["cell_state"]
    assert st.seg_box == {}
    # 往产物里塞一条假判据：第 2 格「tall」
    st = st.model_copy(update={"seg_box": {f"{BOOK}:{PAGE}:{COL}:2": ["tall"]}})
    write_product(ctx, "cell_state", PAGE, cell_state=st)
    logs: list[str] = []
    ctx.log = logs.append
    off = {r.slot: r for cc in STEPS["char_decide"].run_page(ctx, PAGE)["char_decide"].columns for r in cc.chars}
    assert all(r.admit for r in off.values()) and not any("cell_state" in x for x in logs)      # 关：忽略产物，无日志
    on_p = base.model_copy(update={"cell_state_read": True})
    ctx2 = _ctx(tmp_path, monkeypatch, on_p, cs.CellStateParams(enabled=True))
    ctx2.log = logs.append
    on = {r.slot: r for cc in STEPS["char_decide"].run_page(ctx2, PAGE)["char_decide"].columns for r in cc.chars}
    assert not on[2].admit and on[1].admit and on[3].admit        # 开：用了产物里的判据
    assert any("cell_state 读产物" in x and "本地现算" in x for x in logs)


def test_cell_state_read_default_off_and_not_in_dump():
    assert SeedAdmitParams().cell_state_read is False
    assert "cell_state_read" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(cell_state_read=True).model_dump()["cell_state_read"] is True
