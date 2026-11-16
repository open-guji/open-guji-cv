"""半文半表页按列标表（GUJI-772，2026-11-16）：page_kinds.table_cols → column_gate.table_cols，点名列拒收、其余照常。"""
from __future__ import annotations

import pytest

from helpers import column_xs, make_book, make_ctx, make_gate1, run_steps, synth_page
from open_guji_cv.core import page_kinds as PK
from open_guji_cv.core.step import STEPS
from open_guji_cv.gates.column_gate import TABLE_COLUMN_REJECT, ColumnGateParams

PAGE = 3


def _gate(tmp_path, xs=None, **params):
    gray, borders = synth_page(xs=xs or column_xs(n_cols=9))
    book = make_book(expected_cols=borders.expected_cols)
    ctx = make_ctx(tmp_path, book, raw={PAGE: gray})
    if params:
        ctx.params["column_gate"] = ColumnGateParams(**params)
    ctx.store.write(book.id, "border_detect", f"p{PAGE:04d}", {"borders": borders})
    ctx.store.write(book.id, "border_detect_gate", f"p{PAGE:04d}", {"border_detect_gate_manifest": make_gate1(
        PAGE, n_cols=borders.expected_cols, expected_cols=book.expected_cols)})
    return run_steps(ctx, PAGE, ["column_warp", "column_gate", "row_segment", "row_segment_gate"])


def test_page_kinds_table_cols_loads_and_maps():
    pk = PK.load_page_kinds({"table_cols": {112: ["3-5", 1], "98": 7}, "table": [12]})
    assert pk == {"table_cols": {98: [7], 112: [1, 3, 4, 5]}, "table": [12]}      # 展开成升序整数、页键排序
    assert PK.to_params(pk)["column_gate"] == {"table_cols": {98: [7], 112: [1, 3, 4, 5]}}
    b = make_book(page_kinds={"table_cols": {112: ["1-5"]}})
    assert b.params["column_gate"]["table_cols"] == {112: [1, 2, 3, 4, 5]}
    assert b.params == make_book(page_kinds={"table_cols": {112: [5, 4, 3, 2, 1]}}).params    # 写法不同、参数相同
    assert PK.table_cols_from_params(b.params) == {112: [1, 2, 3, 4, 5]}
    assert PK.kinds_from_params(b.params) == {}          # 页型表（{页型: [页号]}）里不出现 table_cols


def test_page_kinds_table_cols_validates():
    with pytest.raises(ValueError, match="二者选一"):
        PK.load_page_kinds({"table": ["8-20"], "table_cols": {9: [1]}})
    with pytest.raises(ValueError, match="二者选一"):
        PK.load_page_kinds({"cover": [1], "table_cols": {1: [1]}})
    with pytest.raises(ValueError, match="列号写错"):
        PK.load_page_kinds({"table_cols": {9: ["5-1"]}})
    with pytest.raises(ValueError, match="从 1 起"):
        PK.load_page_kinds({"table_cols": {9: [0]}})
    with pytest.raises(ValueError, match="页号"):
        PK.load_page_kinds({"table_cols": {"9-10": [1]}})
    with pytest.raises(ValueError, match=r"\{页: \[列号"):
        PK.load_page_kinds({"table_cols": [9]})
    with pytest.raises(ValueError, match="两处都写了"):
        make_book(page_kinds={"table_cols": {9: [1]}}, params={"column_gate": {"table_cols": {9: [2]}}})
    make_book(page_kinds={"table_cols": {9: [1]}}, params={"column_gate": {"table_cols": {"9": [1]}}})   # 值一样不算冲突


def test_params_table_cols_direct_in_book_yaml_rejected(tmp_path, monkeypatch):
    import yaml
    from open_guji_cv.core import book_config as bc
    monkeypatch.delenv(bc.OVERRIDE_ENV, raising=False)
    monkeypatch.delenv("GUJI_ALLOW_OLD_PAGE_SYNTAX", raising=False)
    (tmp_path / "books").mkdir()
    doc = {"id": "v1", "title": "t", "raw_dir": "raw", "expected_cols": 9}
    p = tmp_path / "books" / "v1.yaml"
    p.write_text(yaml.safe_dump({**doc, "params": {"column_gate": {"table_cols": {9: [1]}}}}), encoding="utf-8")
    with pytest.raises(bc.BookConfigError, match="page_kinds.table_cols"):
        bc.effective_book_dict(p)
    p.write_text(yaml.safe_dump({**doc, "page_kinds": {"table_cols": {9: ["1-2"]}}}), encoding="utf-8")
    assert bc.effective_book_dict(p)["params"]["column_gate"]["table_cols"] == {9: [1, 2]}
    assert bc.params_provenance(p, {})["column_gate.table_cols"] == ({9: [1, 2]}, "册 yaml（page_kinds）")


def test_empty_table_cols_not_in_params_dump():
    assert "table_cols" not in ColumnGateParams().model_dump()
    assert ColumnGateParams(table_cols={3: [1]}).model_dump()["table_cols"] == {3: [1]}


def test_table_cols_rejected_rest_admitted_and_cut(tmp_path):
    base = _gate(tmp_path / "a")
    out = _gate(tmp_path / "b", table_cols={PAGE: ["1-3"], PAGE + 1: [5]})
    gm = out["gate_manifest"]
    assert gm.admitted
    for c in gm.columns:
        tab = any(r.startswith(TABLE_COLUMN_REJECT) for r in c.reject)
        assert tab == (c.col in (1, 2, 3)), (c.col, c.reject)
        if c.col > 3:
            assert c.admitted
    assert all(not c.flags for c in gm.columns if c.col <= 3)          # 表格列只留拒因，不叠 flag
    assert gm.column_widths == base["gate_manifest"].column_widths     # column_widths 仍记全部列
    b_cells = {c.col: c for c in base["cells"].columns}
    for cc in out["cells"].columns:
        if cc.col <= 3:
            assert not cc.ok and TABLE_COLUMN_REJECT in cc.error
        else:                                   # 正文列照常切（合成页列宽一样，切出来与不标时相同）
            assert cc.model_dump() == b_cells[cc.col].model_dump()
    rg = {c.col: c for c in out["row_segment_gate_manifest"].columns}
    assert rg[1].reject and rg[1].reject[0].startswith("table_column")
    assert not any(r.startswith("dp_no_solution") for c in (rg[1], rg[2], rg[3]) for r in c.reject)


def test_other_pages_unchanged(tmp_path):
    a = _gate(tmp_path / "a")["gate_manifest"]
    b = _gate(tmp_path / "b", table_cols={PAGE + 1: [1]})["gate_manifest"]
    assert a.model_dump() == b.model_dump()


def test_mostly_table_page_still_gets_period(tmp_path):
    """表占大半页（9 列里 7 列是表）：正文只剩两列，页级周期门槛按正文列数算，不整页拒。"""
    gm = _gate(tmp_path, table_cols={PAGE: ["1-7"]})["gate_manifest"]
    assert gm.admitted and gm.period
    assert [c.col for c in gm.columns if c.admitted] == [8, 9]


def test_median_width_excludes_table_cols(tmp_path):
    """表格列窄（右起 5 列 60px、正文 4 列 100px）：median_width 只按正文列算，正文列不因表格列误报 column_width。"""
    import statistics
    xs = [60.0]
    for w in [100] * 4 + [60] * 5:            # 4 列宽、5 列窄（哪头是 col 1 不要紧，下面按量出的宽挑）
        xs.append(xs[-1] + w)
    gm0 = _gate(tmp_path / "a", xs=xs)["gate_manifest"]
    narrow = sorted(c.col for c, w in zip(gm0.columns, gm0.column_widths) if w < 70)
    gm = _gate(tmp_path / "b", xs=xs, table_cols={PAGE: narrow})["gate_manifest"]
    body = [w for c, w in zip(gm.columns, gm.column_widths) if c.col not in narrow]
    assert len(narrow) == 5 and gm.median_width == statistics.median(body) > gm0.median_width
    assert gm0.median_width == statistics.median(gm0.column_widths)
    wide = {c.col for c, w in zip(gm0.columns, gm0.column_widths) if w >= 90}     # 正常宽的正文列
    assert any(f.startswith("column_width：") for c in gm0.columns if c.col in wide for f in c.flags)
    assert not any(f.startswith("column_width：") for c in gm.columns if c.col in wide for f in c.flags)
