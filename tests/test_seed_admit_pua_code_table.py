# -*- coding: utf-8 -*-
"""seed_admit `pua_code_table`：按私用码表改放字（通道 `code_table`）、一码多字族豁免、人裁不动、每页统计。直接测 `_pua_code_pass`，数据自造。"""
from __future__ import annotations

import json

from open_guji_cv.feedback.rulings import RulingStore
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, PageAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _pua_code_pass
from open_guji_cv.utils.pua_v2_codes import load_table, norm_code

B = "tbook:1"
TABLE = ({"F100A": "眩", "F1016": "炫", "F1001": "埀", "F1091": "○"}, {"F1001": frozenset("乖垂埀")})


def _st(tmp_path, **cell_code):
    st = RulingStore(tmp_path)
    for slot, (code, ref) in cell_code.items():
        st.put_cell_code(f"{B}:1:{slot}", code, ref=ref, anch=4, page_match=0.97)
    return st


def _run(cells, amap, st):
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=s, admit=c.get("admit", True), char=c.get("char"), doubts=list(c.get("doubts", [])),
                     channel=c.get("channel", "pua_rule"), provenance=c.get("provenance", "match"), evidence={})
            for s, c in cells.items()]
    amap = {f"{B}:1:{s}": (c, None) for s, c in amap.items()}
    out = _pua_code_pass([ColumnAdmit(col=1, chars=recs)], amap, st, TABLE)
    return out, {r.slot: r for r in recs}


def test_wrong_char_fixed_not_demoted(tmp_path):
    (fix, mism, dem), r = _run({1: {"char": "炫"}}, {1: "炫"}, _st(tmp_path, **{"1": ("F100A", "炫")}))
    assert (fix, mism, dem) == (1, 0, 0)
    assert (r[1].char, r[1].admit, r[1].channel, r[1].provenance) == ("眩", True, "code_table", "match")
    assert r[1].evidence["code_table"] == {"code": "F100A", "char": "眩", "was": "炫", "was_channel": "pua_rule"}


def test_same_char_and_no_code_untouched(tmp_path):
    (fix, mism, dem), r = _run({1: {"char": "眩"}, 2: {"char": "炫"}}, {1: "眩", 2: "炫"}, _st(tmp_path, **{"1": ("F100A", "眩")}))
    assert (fix, mism, dem) == (0, 0, 0) and r[2].char == "炫" and r[1].channel == "pua_rule"


def test_ref_changed_not_trusted(tmp_path):
    """整理本对位字变了（重切后格号可能挪了）：不认这条格→码记录。"""
    assert _run({1: {"char": "炫"}}, {1: "弦"}, _st(tmp_path, **{"1": ("F100A", "炫")}))[0] == (0, 0, 0)


def test_human_cell_untouched_but_counted(tmp_path):
    (fix, mism, dem), r = _run({1: {"char": "炫", "provenance": "human", "channel": "human"}}, {1: "炫"}, _st(tmp_path, **{"1": ("F100A", "炫")}))
    assert (fix, mism, dem) == (0, 1, 0) and r[1].char == "炫" and r[1].channel == "human"


def test_pending_cell_untouched(tmp_path):
    assert _run({1: {"char": "炫", "admit": False, "channel": None}}, {1: "炫"}, _st(tmp_path, **{"1": ("F100A", "炫")}))[0] == (0, 0, 0)


def test_family_in_family_ok_outside_demoted(tmp_path):
    """F1001 一码多字：放行乖（族内）不动、不降审；放行成族外字 → 降审，不按码改字。"""
    st = _st(tmp_path, **{"1": ("F1001", "乖"), "2": ("F1001", "乖")})
    (fix, mism, dem), r = _run({1: {"char": "乖"}, 2: {"char": "乘"}}, {1: "乖", 2: "乖"}, st)
    assert (fix, mism, dem) == (0, 0, 1)
    assert r[1].admit and r[1].char == "乖" and r[1].channel == "pua_rule"
    assert not r[2].admit and "src_code_conflict" in r[2].doubts and r[2].char == "乘" and r[2].evidence["demoted_from"]["channel"] == "pua_rule"


def test_non_han_table_char_skipped(tmp_path):
    assert _run({1: {"char": "甲"}}, {1: "甲"}, _st(tmp_path, **{"1": ("F1091", "甲")}))[0] == (0, 0, 0)


def test_no_cell_codes_is_noop(tmp_path):
    assert _run({1: {"char": "炫"}}, {1: "炫"}, RulingStore(tmp_path))[0] == (0, 0, 0)


def test_cell_codes_roundtrip_persist(tmp_path):
    _st(tmp_path, **{"1": ("F100A", "炫")})
    cc = RulingStore(tmp_path).cell_codes()
    assert cc[f"{B}:1:1"]["code"] == "F100A" and cc[f"{B}:1:1"]["ref"] == "炫"
    # 窗口键裁定读口不受影响（src-2 条目没有窗口）
    assert RulingStore(tmp_path).get("O", "vis-o1", "甲", "乙") is None


def test_params_dump_and_page_stats_clean():
    d = SeedAdmitParams(db_path="x").model_dump()
    assert "pua_code_table" not in d
    assert SeedAdmitParams(db_path="x", pua_code_table=True).model_dump()["pua_code_table"] is True
    assert "n_code_fix" not in PageAdmit(page=1).model_dump() and "n_code_mismatch" not in PageAdmit(page=1).model_dump()
    assert PageAdmit(page=1, n_code_fix=2, n_code_mismatch=1).model_dump()["n_code_fix"] == 2


def test_load_table_repo_and_data_override(tmp_path):
    codes, fams = load_table(None)
    assert codes["F1001"] == "埀" and fams["F1001"] == frozenset("乖垂埀") and codes["F100A"] == "眩"
    (tmp_path / "pua").mkdir()
    rows = [{"code": "siku-qiefen-v2:U+F100A", "verdict": "char", "char": "炫"},
            {"code": "siku-qiefen-v2:U+F1099", "verdict": "pending", "char": None},
            {"code": "daizhige:U+EA96", "verdict": "char", "char": "乙"}]
    (tmp_path / "pua" / "pua_table.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    codes, _ = load_table(tmp_path)
    assert codes["F100A"] == "炫" and "F1099" not in codes and "EA96" not in codes
    assert norm_code("siku-qiefen-v2:U+f100a") == "F100A"


def test_load_table_derived_from_daizhige_rows_and_multi(tmp_path):
    """审核页按殆知阁码审：daizhige 行 verdict=char → 它 same_as 的 v2 码取这个字；verdict=multi（一码多字）→ 族，不再按码改字。"""
    (tmp_path / "pua").mkdir()
    rows = [{"code": "daizhige:U+EA96", "verdict": "char", "char": "直", "same_as": ["siku-qiefen-v2:U+F1099"]},
            {"code": "daizhige:U+EB09", "verdict": "multi", "char": None, "chars": ["瓠", "𤬄"], "same_as": ["siku-qiefen-v2:U+F1007"]},
            {"code": "daizhige:U+EA7B", "verdict": "pending", "char": None, "same_as": ["siku-qiefen-v2:U+F10A0"]}]
    (tmp_path / "pua" / "pua_table.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    codes, fams = load_table(tmp_path)
    assert codes["F1099"] == "直" and "F10A0" not in codes
    assert fams["F1007"] == frozenset("瓠𤬄")


def test_keep_channels_not_overwritten(tmp_path):
    """书级旋钮 pua_code_keep_channels：保留的通道不按码改，计入仍不一致。"""
    st = _st(tmp_path, **{"1": ("F100A", "炫"), "2": ("F100A", "炫")})
    cells = {1: {"char": "炫", "channel": "group_flow"}, 2: {"char": "炫", "channel": "pua_rule"}}
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=s, admit=True, char=c["char"], doubts=[], channel=c["channel"], provenance="match", evidence={}) for s, c in cells.items()]
    amap = {f"{B}:1:{s}": ("炫", None) for s in cells}
    out = _pua_code_pass([ColumnAdmit(col=1, chars=recs)], amap, st, TABLE, p=SeedAdmitParams(pua_code_keep_channels="group_flow"))
    assert out == (1, 1, 0) and recs[0].char == "炫" and recs[1].char == "眩"


def test_family_demote_off_only_counts(tmp_path):
    st = _st(tmp_path, **{"1": ("F1001", "乖")})
    rec = AdmitRec(id=f"{B}:1:1", slot=1, admit=True, char="乘", doubts=[], channel="context", provenance="match", evidence={})
    out = _pua_code_pass([ColumnAdmit(col=1, chars=[rec])], {f"{B}:1:1": ("乖", None)}, st, TABLE, p=SeedAdmitParams(pua_code_family_demote=False))
    assert out == (0, 1, 0) and rec.admit and rec.char == "乘"


def test_new_knobs_not_in_default_dump():
    d = SeedAdmitParams().model_dump()
    assert "pua_code_keep_channels" not in d and "pua_code_family_demote" not in d


def test_multi_code_family_only(tmp_path):
    """纯多字码（只登族、无单字）：族内字认，族外降审，不改字。"""
    tab = ({}, {"F1111": frozenset("甲乙")})
    st = _st(tmp_path, **{"1": ("F1111", "甲"), "2": ("F1111", "甲")})
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=s, admit=True, char=c, doubts=[], channel="context", provenance="match", evidence={}) for s, c in ((1, "乙"), (2, "丙"))]
    out = _pua_code_pass([ColumnAdmit(col=1, chars=recs)], {f"{B}:1:{s}": ("甲", None) for s in (1, 2)}, st, tab)
    assert out == (0, 0, 1) and recs[0].admit and not recs[1].admit and recs[1].char == "丙"


def test_load_table_multi_verdict(tmp_path):
    (tmp_path / "pua").mkdir()
    rows = [{"code": "daizhige:U+EA7A", "verdict": "multi", "family": "最撮", "same_as": ["siku-qiefen-v2:U+F1028"]},
            {"code": "siku-qiefen-v2:U+F2000", "verdict": "char", "char": "甲"}]
    (tmp_path / "pua" / "pua_table.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    codes, fams = load_table(tmp_path)
    assert fams["F1028"] == frozenset("最撮") and "F1028" not in codes and codes["F2000"] == "甲"


# ── pua_code_admit：未放行格按码表＋库首位互证放行（A24 R01 11-07） ──

def _admit_run(tmp_path, cells, codes, mm, p=None):
    from types import SimpleNamespace as NS
    from open_guji_cv.steps.seed_admit import _pua_code_admit_pass
    st = _st(tmp_path, **codes)
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=s, admit=c.get("admit", False), char=c.get("char"), doubts=list(c.get("doubts", [])),
                     channel=c.get("channel"), provenance=c.get("provenance", ""), evidence={})
            for s, c in cells.items()]
    mmap = {f"{B}:1:{s}": NS(candidates=v[0], verdict=v[1] if len(v) > 1 else "unsure", guard=v[2] if len(v) > 2 else None)
            for s, v in mm.items()}
    amap = {f"{B}:1:{s}": (None, None) for s in cells}
    n = _pua_code_admit_pass([ColumnAdmit(col=1, chars=recs)], amap, mmap, st, TABLE, p=p or SeedAdmitParams(pua_code_admit=True))
    return n, {r.slot: r for r in recs}


def test_admit_when_lib_top_equals_table(tmp_path):
    n, r = _admit_run(tmp_path, {1: {"char": "眩"}, 2: {"char": "賅"}},
                      {"1": ("F100A", ""), "2": ("F100A", "")},
                      {1: ([("眩", 0.94)],), 2: ([("賅", 0.95), ("眩", 0.94)],)})
    assert n == 1
    assert (r[1].admit, r[1].char, r[1].channel, r[1].doubts) == (True, "眩", "code_table", ["code_table_admit"])
    assert r[1].evidence["code_table"]["admit"] is True
    assert r[2].admit is False                      # 库首位不是表字：不放


def test_admit_family_takes_lib_top(tmp_path):
    n, r = _admit_run(tmp_path, {1: {"char": "垂"}}, {"1": ("F1001", "")}, {1: ([("垂", 0.97)],)})
    assert n == 1 and r[1].char == "垂"             # 一码多字：族内字按库首位放，不改成表字


def test_admit_guards(tmp_path):
    n, r = _admit_run(tmp_path,
                      {1: {"char": "眩"}, 2: {"char": "眩"}, 3: {"char": "眩", "provenance": "human"}, 4: {"char": "眩", "doubts": ["occluded"]},
                       5: {"char": "眩"}, 6: {"char": "○"}},
                      {str(s): ("F100A", "") for s in (1, 2, 3, 4, 5)} | {"6": ("F1091", "")},
                      {1: ([("眩", 0.80)],), 2: ([("眩", 0.95)], "diff"), 3: ([("眩", 0.95)],), 4: ([("眩", 0.95)],),
                       5: ([("眩", 0.95)], "unsure", "never_match"), 6: ([("○", 0.99)],)})
    assert n == 0                                   # cov 不够、库判 diff、人裁、遮挡、有护栏、表字非汉字：都不放


def test_admit_off_not_in_dump():
    d = SeedAdmitParams().model_dump()
    assert "pua_code_admit" not in d and "pua_code_admit_cov" not in d
    assert SeedAdmitParams(pua_code_admit=True).model_dump()["pua_code_admit_cov"] == 0.85


def test_load_table_registers_daizhige_code(tmp_path):
    """殆知阁行本身的码也登记（A24 R01 第 7 轮）：没有 same_as v2 码的殆知阁码也能按码取字。"""
    import json as _json
    from open_guji_cv.utils.pua_v2_codes import load_table, norm_code
    (tmp_path / "pua").mkdir()
    rows = [{"code": "daizhige:U+EAA0", "verdict": "char", "char": "卿", "same_as": []},
            {"code": "daizhige:U+EB09", "verdict": "multi", "chars": "瓠𤬄", "same_as": ["siku-qiefen-v2:U+F1007"]}]
    (tmp_path / "pua" / "pua_table.jsonl").write_text("\n".join(_json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    codes, fams = load_table(tmp_path)
    assert codes[norm_code("daizhige:U+EAA0")] == "卿"
    assert fams[norm_code("daizhige:U+EB09")] == frozenset("瓠𤬄") and fams["F1007"] == frozenset("瓠𤬄")


def test_admit_family_skips_other_codes_char(tmp_path):
    """族里是别的码表字的字（F1001 乖垂埀 里的乖＝另一码的表字）不算互证（A24 11-08，第 7 轮 3 格垂放成乖）。"""
    from types import SimpleNamespace as NS
    from open_guji_cv.steps.seed_admit import _pua_code_admit_pass
    table = ({"F1001": "埀", "DAIZHIGE:U+EA36": "乖"}, {"F1001": frozenset("乖垂埀")})
    st = _st(tmp_path, **{"1": ("F1001", ""), "2": ("F1001", "")})
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=s, admit=False, char=c, doubts=[], channel=None, provenance="", evidence={})
            for s, c in ((1, "乖"), (2, "垂"))]
    mmap = {f"{B}:1:1": NS(candidates=[("乖", 0.97)], verdict="unsure", guard=None),
            f"{B}:1:2": NS(candidates=[("垂", 0.97)], verdict="unsure", guard=None)}
    amap = {r.id: (None, None) for r in recs}
    n = _pua_code_admit_pass([ColumnAdmit(col=1, chars=recs)], amap, mmap, st, table, p=SeedAdmitParams(pua_code_admit=True))
    assert n == 1 and recs[0].admit is False and recs[1].admit is True
