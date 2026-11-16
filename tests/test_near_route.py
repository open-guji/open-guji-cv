# -*- coding: utf-8 -*-
"""形近字组分流（clustering/near_route.py）与建表脚本的纯逻辑：自己造表、造向量，不碰真书数据。"""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from open_guji_cv.clustering import near_route as R

ROOT = Path(__file__).resolve().parents[1]


def _table(tmp_path, pairs):
    p = tmp_path / "near_groups.json"
    p.write_text(json.dumps({"pairs": pairs}, ensure_ascii=False), encoding="utf-8")
    return str(p)


@pytest.fixture
def table(tmp_path):
    return _table(tmp_path, {
        "天夭": {"src": ["lib:qtw"], "near": {"qtw": 0.994}, "core": True},
        "喬僑": {"src": ["lib:qtw"], "near": {"qtw": 0.977}, "core": False},
        "未末": {"src": ["font", "hand"], "core": True},
        "侯𠋫": {"src": ["variant"], "near": {"sj": 0.96}, "core": True},
        "目自": {"src": ["font"], "core": False},
        "大太": {"src": ["lib:sj", "lib:qtw"], "near": {"sj": 0.99, "qtw": 0.978}, "core": True},
    })


def test_partners_levels(table):
    core = R.partners("core", None, table)
    assert core["天"] == {"夭"} and core["侯"] == {"𠋫"} and core["末"] == {"未"} and core["大"] == {"太"}
    assert "喬" not in core and "目" not in core
    full = R.partners("all", None, table)
    assert full["喬"] == {"僑"} and full["目"] == {"自"}
    with pytest.raises(ValueError):
        R.partners("wide", None, table)


def test_partners_by_book(table):
    """指定书：库里挖的对只认这本书的；手工、字体、同形异码不分书。大/太 在全唐文只够全表，不够核心。"""
    sj = R.partners("core", "sj", table)
    assert "天" not in sj and sj["大"] == {"太"} and sj["未"] == {"末"} and sj["侯"] == {"𠋫"}
    qtw = R.partners("core", "qtw", table)
    assert qtw["天"] == {"夭"} and "大" not in qtw
    assert R.partners("all", "qtw", table)["大"] == {"太"}
    assert "喬" not in R.partners("all", "sk", table)


def test_missing_table_is_empty(tmp_path):
    assert R.partners("core", None, str(tmp_path / "none.json")) == {}
    assert R.route("天", 0.5, 1.0, R.RouteConfig(table=str(tmp_path / "none.json"))).reason is None


def test_groups_connected(tmp_path):
    t = _table(tmp_path, {k: {"src": ["hand"], "core": True} for k in ("己已", "已巳", "日曰")})
    assert R.groups("core", None, t) == [("己", "已", "巳"), ("日", "曰")]


def test_knn_agreement():
    chars = np.array(list("天天天夭夭大大大大大"))
    sims = np.array([.9, .8, .7, .95, .1, .6, .5, .4, .3, .2], dtype=np.float32)
    assert R.knn_agreement(sims, chars, "天", k=4) == pytest.approx(3 / 3)      # 前 4 名：夭天天天，天只有 3 例
    assert R.knn_agreement(sims, chars, "夭", k=4) == pytest.approx(1 / 2)
    assert R.knn_agreement(sims, chars, "大", k=4) == 0.0
    assert R.knn_agreement(sims, chars, "無", k=4) == 0.0
    s2 = sims.copy()
    s2[[0, 1, 2]] = -np.inf                                                     # 天 整类排除：既不算近邻也不算分母
    assert R.knn_agreement(s2, chars, "天", k=4) == 0.0
    assert R.knn_agreement(s2, chars, "大", k=4) == pytest.approx(3 / 4)


def test_evidence_lead_and_calib():
    chars = np.array(list("天天夭大"))
    sims = np.array([.9, .8, .7, .2], dtype=np.float32)
    top, s, lead, knn = R.evidence(sims, chars, k=2)
    assert (top, knn) == ("天", 1.0) and s == pytest.approx(.9) and lead == pytest.approx(.2)
    cal = (np.array([0., 1.]), np.array([.5, 1.]))                              # 校准：x → 0.5 + x/2
    _, s, lead, _ = R.evidence(sims, chars, k=2, calib=cal)
    assert s == pytest.approx(.95) and lead == pytest.approx(.1)
    only = np.array([.9, .8, -np.inf, -np.inf], dtype=np.float32)               # 只有一个字可比：领先量取字分
    assert R.evidence(only, chars, k=2)[2] == pytest.approx(.9)
    assert R.evidence(np.full(4, -np.inf, dtype=np.float32), chars)[0] is None


def test_route_rule(table):
    cfg = R.RouteConfig(table=table, lead_min=0.03, knn_min=0.9, weak="both")
    d = R.route("天", 0.2, 1.0, cfg, 0.99)
    assert d.reason == "near_group" and d.partners == ("夭",) and d.score == 0.99
    assert R.route("喬", 0.2, 1.0, cfg).reason is None                           # 只在全表里
    assert R.route("喬", 0.2, 1.0, R.RouteConfig(level="all", table=table)).reason == "near_group"
    assert R.route("書", 0.01, 0.5, cfg).reason == "weak"
    assert R.route("書", 0.01, 0.95, cfg).reason is None                         # both：要两条都成立
    assert R.route("書", 0.2, 0.5, cfg).reason is None
    either = R.RouteConfig(table=table, lead_min=0.03, knn_min=0.9, weak="either")
    assert R.route("書", 0.2, 0.5, either).reason == "weak" and R.route("書", 0.01, 0.95, either).reason == "weak"
    dflt = R.RouteConfig(table=table)                                           # 缺省：只看一致度，不满就送审
    assert R.route("書", 0.0, 0.9, dflt).reason == "weak" and R.route("書", 0.0, 1.0, dflt).reason is None
    assert R.route(None, 0, 0, cfg).reason == "empty"
    with pytest.raises(ValueError):
        R.RouteConfig(weak="any")


def test_router_excludes_same_cell(table):
    """查询格自己的刻例在库里（同一物理格）：不排除就自己认自己。排除后首位变成形近字，落表送审。"""
    rng = np.random.default_rng(0)
    base = {c: rng.normal(size=16) for c in "天夭書"}

    def vec(c, eps):
        v = base[c] + eps * rng.normal(size=16)
        return v / np.linalg.norm(v)
    chars = list("天夭夭書書書")
    E = np.stack([vec(c, 0.05) for c in chars]).astype(np.float32)
    r = R.Router(E, chars, R.RouteConfig(table=table, k=2))
    assert r.decide(E[0]).top == "天"
    q = (0.7 * E[0] + 0.3 * E[1]) / np.linalg.norm(0.7 * E[0] + 0.3 * E[1])
    d = r.decide(q, exclude=[0])
    assert d.top == "夭" and d.reason == "near_group" and d.partners == ("天",)
    assert r.decide(E[3], exclude=[3]).reason is None                          # 書：不在表里、近邻全是書
    with pytest.raises(ValueError):
        R.Router(E, chars[:-1])


def _build_mod():
    spec = importlib.util.spec_from_file_location("build_near_groups", ROOT / "scripts" / "build_near_groups.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_near_from_scores_second_highest():
    B = _build_mod()
    rows = [("天", "夭", .99), ("天", "夭", .98), ("天", "夭", .90), ("夭", "天", .995), ("書", "畫", .97)]
    near = B.near_from_scores(rows)
    assert near[("夭", "天") if "夭" < "天" else ("天", "夭")] == (.995, 4)     # 夭→天 只出现一次用那一次，两个方向取大
    assert near[("書", "畫")] == (.97, 1)
    one_bad = B.near_from_scores([("之", "乏", .999), ("之", "乏", .5)])       # 单个错标刻例拖不进表：取第二高
    assert one_bad[("之", "乏")][0] == .5


def test_merge_sources_and_core(tmp_path):
    B = _build_mod()
    mined = tmp_path / "near_x.json"
    mined.write_text(json.dumps({"book": "x", "db": "glyph.db", "model": "m.pt", "lib_rows": 10,
                                 "pairs": {"天夭": [0.99, 5], "喬僑": [0.976, 3]},
                                 "variants": {"侯𠋫": [0.96, 4], "修脩": [0.90, 2]}}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "near_groups.json"
    assert B.main(["merge", str(mined), "--out", str(out)]) == 0
    P = json.loads(out.read_text(encoding="utf-8"))["pairs"]

    def key(pair):                                                             # 表的键按码位排
        return "".join(sorted(pair))
    assert P[key("天夭")]["core"] and P[key("天夭")]["src"] == ["lib:x"] and P[key("天夭")]["near"] == {"x": 0.99}
    assert not P[key("喬僑")]["core"]
    assert P[key("侯𠋫")]["core"] and "variant" in P[key("侯𠋫")]["src"]
    assert key("修脩") not in P                                                 # 库里量出来不够像的异体对不进表
    assert any("hand" in v["src"] for v in P.values())                         # 手工表并进来了
    core = R.partners("core", None, str(out))
    assert core["天"] >= {"夭"} and "喬" not in core


def test_merge_drop_list(tmp_path):
    """剔除名单去掉库里挖的假字对；人核过的（手工表）不受它管。"""
    B = _build_mod()
    from open_guji_cv.clustering import confusable as C
    hand = "".join(sorted(next(iter(C.NEVER_MATCH_FAMILIES))))
    mined = tmp_path / "near_x.json"
    mined.write_text(json.dumps({"book": "x", "db": "glyph.db", "model": "m/model.pt", "lib_rows": 10, "trusted_only": True,
                                 "pairs": {"事日": [1.0, 3], "天夭": [0.99, 5]}}, ensure_ascii=False), encoding="utf-8")
    drop = tmp_path / "drop.tsv"
    drop.write_text(f"# 注释\n日事\t字体余弦 0.05\n{hand}\t不该生效\n", encoding="utf-8")
    out = tmp_path / "near_groups.json"
    assert B.main(["merge", str(mined), "--drop", str(drop), "--out", str(out)]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert "".join(sorted("事日")) not in d["pairs"] and "".join(sorted("天夭")) in d["pairs"] and hand in d["pairs"]
    assert d["n_dropped"] == 1 and d["books"]["x"] == {"lib_rows": 10, "trusted_only": True, "model": "m", "pairs": 2}


def test_trusted_rows():
    """机器进库刻例：最像的人裁刻例（不同格）和它同字才可信。"""
    B = _build_mod()
    e = np.eye(3, dtype=np.float32)
    E = np.stack([e[0], e[1], e[0], e[1], e[2], e[0]])
    chars = np.array(list("天夭天天書天"))               # 第 3 行图像天/夭里像 夭 却标成 天；第 4 行没有可比的人裁刻例
    cells = np.array(["a", "b", "c", "d", "e", "a"])      # 第 5 行和第 0 行同一格：不能拿自己那格当证据
    human = np.array([True, True, False, False, False, False])
    got = B.trusted_rows(E, chars, cells, human, np.ones(6, bool))
    assert got.tolist() == [True, True, True, False, False, False]
