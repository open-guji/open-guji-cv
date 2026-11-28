# -*- coding: utf-8 -*-
"""字组数据搬进 `config/near_groups/registry.json`（结构拆分 A5，2026-11-28）的守卫。

- 组的次序有行为意义（入口取第一个装得下的组），`FLOW_GROUPS` 的 id 序列冻结成搬出前那一份；有意改次序、增删组时照实更新快照。
- `_*_FLOWS` 与 registry.json 的 id 一一对上，对不上载入就报错，不给缺省 flow。
- 改了组数据不改 `DATA_SHA` 载入报错（组数据靠这一行进代码指纹）。
"""
from __future__ import annotations

import hashlib
import json

import pytest

from open_guji_cv.groups import registry as R

#: 搬出前（origin/dev，2026-11-28）`",".join(FLOW_GROUPS)` 的 sha256 前 16 位与各表组数。
ORDER_SHA = "ae5db619ca6cb627"
COUNTS = {"GROUPS": 55, "CODEPOINT_GROUPS": 79, "SHAPE_GROUPS": 49, "OPT_IN_GROUPS": 2}


def _doc():
    return json.loads(R.DATA_PATH.read_text(encoding="utf-8"))


def test_flow_groups_order_frozen():
    assert hashlib.sha256(",".join(R.FLOW_GROUPS).encode()).hexdigest()[:16] == ORDER_SHA
    assert {t: len(getattr(R, t)) for t in COUNTS} == COUNTS


def test_tables_are_ordered_subsets_of_flow_groups():
    ids = list(R.FLOW_GROUPS)
    seen = []
    for t in COUNTS:
        tab = getattr(R, t)
        assert [g for g in ids if g in tab] == list(tab), t
        assert all(tab[g] is R.FLOW_GROUPS[g] and tab[g].id == g for g in tab)
        seen += list(tab)
    assert sorted(seen) == sorted(ids)


def test_data_sha_matches_file():
    assert R.data_sha(_doc()) == R.DATA_SHA


def test_data_sha_ignores_line_endings(tmp_path):
    p = tmp_path / "registry.json"
    p.write_bytes(R.DATA_PATH.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    tables, allg = R.load_groups(p)
    assert list(allg) == list(R.FLOW_GROUPS)


def test_order_field_decides_order(tmp_path):
    doc = _doc()
    doc["groups"] = list(reversed(doc["groups"]))     # 文件里倒着写，载入照 order 排
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    _, allg = R.load_groups(p, sha=None)
    assert list(allg) == list(R.FLOW_GROUPS)


def _write(tmp_path, doc):
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def test_changed_data_without_sha_raises(tmp_path):
    doc = _doc()
    doc["groups"][0]["note"] += "改"
    with pytest.raises(ValueError, match="DATA_SHA"):
        R.load_groups(_write(tmp_path, doc))


def test_json_group_without_flow_raises(tmp_path):
    doc = _doc()
    row = dict(doc["groups"][0], id="zz_new", order=max(r["order"] for r in doc["groups"]) + 1)
    doc["groups"].append(row)
    with pytest.raises(ValueError, match="zz_new"):
        R.load_groups(_write(tmp_path, doc), sha=None)


def test_flow_without_json_group_raises(tmp_path):
    doc = _doc()
    gone = doc["groups"].pop()
    with pytest.raises(ValueError, match=gone["id"]):
        R.load_groups(_write(tmp_path, doc), sha=None)


@pytest.mark.parametrize("bad", ["dup_order", "dup_id", "bad_table", "extra_key", "missing_key"])
def test_malformed_rows_raise(tmp_path, bad):
    doc = _doc()
    g = doc["groups"]
    if bad == "dup_order":
        g[1]["order"] = g[0]["order"]
    elif bad == "dup_id":
        g[1]["id"] = g[0]["id"]
    elif bad == "bad_table":
        g[0]["table"] = "NOPE"
    elif bad == "extra_key":
        g[0]["flow"] = "x"
    else:
        del g[0]["members"]
    with pytest.raises(ValueError):
        R.load_groups(_write(tmp_path, doc), sha=None)


# —— 成员派生常量守卫（A5 条件 c，CV4 2026-11-28 定：常量都不改，只守住 ⊆ 成员） ——

#: FlowSpec 及其方法里「必须是本组成员」的字段（`tolerate`、`ref_top_extra` 是组外陪衬，不在内）。
MEMBER_FIELDS = {("Only", "chars"), ("Only", "give"), ("FlowSpec", "families"), ("FlowSpec", "pair"),
                 ("FlowSpec", "ref_margin_forms"), ("Llm", "after_pair"), ("CtxModel", "after_pair"),
                 ("CtxOnline", "after_pair"), ("RefRare", "rare")}
#: 唯一的例外：`flow._EXTRA_SAME_WRITING`（「同一个字的写法」，跨组的语义表，不按某一组成员算）。
EXEMPT = {"open_guji_cv.groups.flow._EXTRA_SAME_WRITING"}


def _chars(v) -> set:
    if isinstance(v, str):
        return set(v)
    return {c for x in v for c in _chars(x)} if isinstance(v, (tuple, list, frozenset, set)) else set()


def _member_fields(o, out):
    import dataclasses
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        for f in dataclasses.fields(o):
            v = getattr(o, f.name)
            if (type(o).__name__, f.name) in MEMBER_FIELDS:
                out.append((f"{type(o).__name__}.{f.name}", _chars(v)))
            _member_fields(v, out)
    elif isinstance(o, (tuple, list)):
        for x in o:
            _member_fields(x, out)
    return out


def test_flow_char_constants_are_members():
    bad = []
    for g in R.FLOW_GROUPS.values():
        for where, chars in _member_fields(g.flow, []):
            if chars - g.members:
                bad.append((g.id, where, "".join(sorted(chars - g.members))))
    assert not bad, f"FlowSpec 里出现了非本组成员的字（成员改了常量没跟上？）：{bad}"


def test_known_member_fields_still_exist():
    """守卫要真在守：这几类字段在现有组里都还出现（改名了会漏守）。"""
    found = {w for g in R.FLOW_GROUPS.values() for w, _ in _member_fields(g.flow, [])}
    assert found == {f"{a}.{b}" for a, b in MEMBER_FIELDS}


def test_ry_shape_output_chars_are_members():
    """`methods.ry_shape` 出字映射是 日／曰：挂了它的组成员必须含这两个字。"""
    from open_guji_cv.groups.methods import RY_SHAPE
    users = [g for g in R.FLOW_GROUPS.values() if RY_SHAPE in g.flow.methods]
    assert users and all({"日", "曰"} <= g.members for g in users), [g.id for g in users]


def test_extra_same_writing_is_the_listed_exemption():
    """例外显式列出：`_EXTRA_SAME_WRITING` 还是那两组；它变了就要回来确认是否仍算例外。"""
    from open_guji_cv.groups import flow
    assert EXEMPT == {"open_guji_cv.groups.flow._EXTRA_SAME_WRITING"}
    assert flow._EXTRA_SAME_WRITING == (frozenset("宫宮"), frozenset("賓賔"))
