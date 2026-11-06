"""Step5-a 共识升档（2026-09-19）：unsure 档里 top 字 cov 够、比次优异字高够、且已有足够
人裁例时升成 same。标定与理由见 steps/glyph_match.py 模块头。"""

from __future__ import annotations

from open_guji_cv.steps.glyph_match import consensus_same

LIB = {"𠊓": 18, "宐": 7, "空": 1, "宣": 0}


def _n(ch):
    return LIB.get(ch, 0)


def test_upgrades_when_all_three_hold():
    # bxgb:34:3:19 实测：𠊓 0.9903 / 僃 0.9499 / 佛 0.9408，库里 𠊓 18 例——现役判 unsure
    cands = [("𠊓", 0.9903), ("僃", 0.9499), ("佛", 0.9408)]
    assert consensus_same(cands, _n, 0.99, 0.03, 3) == ("𠊓", 18)


def test_cov_below_threshold_stays_unsure():
    assert consensus_same([("𠊓", 0.985), ("僃", 0.90)], _n, 0.99, 0.03, 3) is None


def test_riding_between_two_chars_stays_unsure():
    """次优**异字**只差 0.01：骑在两字之间，不升。"""
    assert consensus_same([("𠊓", 0.995), ("僃", 0.986)], _n, 0.99, 0.03, 3) is None


def test_same_char_runner_up_does_not_count_as_margin():
    """次优是同一个字的另一刻例：不算竞争者，看再往下的异字。"""
    cands = [("𠊓", 0.995), ("𠊓", 0.994), ("僃", 0.95)]
    assert consensus_same(cands, _n, 0.99, 0.03, 3) == ("𠊓", 18)


def test_thin_library_stays_unsure():
    """库里只有一两例人裁：kNN 邻域太薄，不升。"""
    assert consensus_same([("空", 0.995), ("宣", 0.90)], _n, 0.99, 0.03, 3) is None


def test_no_rival_uses_unsure_floor_as_margin():
    assert consensus_same([("宐", 0.995)], _n, 0.99, 0.03, 3) == ("宐", 7)
    assert consensus_same([("宐", 0.87)], _n, 0.99, 0.03, 3) is None


def test_disabled_by_min_confirmed_zero():
    assert consensus_same([("𠊓", 0.999), ("僃", 0.5)], _n, 0.99, 0.03, 0) is None


# ── 2026-11-06：口径、护栏、same 门槛做成参数 ─────────────────────────

def test_family_guard_blocks_near_form_rival():
    """全唐文 006:9:4:10「干戈」：首位 千 0.9989，候选里有 干（zy 组）——开护栏不升。"""
    from open_guji_cv.steps.glyph_match import family_blocked
    lib = {"千": 50, "干": 20}.get
    cands = [("千", 0.9989), ("子", 0.0), ("干", 0.0)]
    assert consensus_same(cands, lib, 0.99, 0.03, 3) == ("千", 50)
    assert consensus_same(cands, lib, 0.99, 0.03, 3, blocked=family_blocked) is None
    # 与首位字不形近的异字不挡
    assert consensus_same([("𠊓", 0.995), ("僃", 0.95)], _n, 0.99, 0.03, 3, blocked=family_blocked) == ("𠊓", 18)


def test_defaults_not_in_param_dump():
    """新参数取缺省时不进参数 dump（参数指纹与此前相同）；改了才进。"""
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    base = GlyphMatchParams(db_path="/nonexistent.db", db_fingerprint="x", borrow_fingerprint="")
    d = base.model_dump()
    for k in ("consensus_count", "consensus_family_guard", "same_cov", "same_wmax"):
        assert k not in d
    on = GlyphMatchParams(db_path="/nonexistent.db", db_fingerprint="x", consensus_count="human+auto",
                          consensus_family_guard=True, same_cov=0.995, same_wmax=12)
    d = on.model_dump()
    assert d["consensus_count"] == "human+auto" and d["consensus_family_guard"] is True
    assert d["same_cov"] == 0.995 and d["same_wmax"] == 12


def test_count_scopes(tmp_path):
    import json
    import sqlite3
    from open_guji_cv.steps.glyph_match import human_confirmed_counts
    db = tmp_path / "g.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE instances (instance_id TEXT, label TEXT)")
        c.execute("CREATE TABLE admissions (instance_id TEXT, provenance TEXT, evidence TEXT)")
        rows = [("a1", "甲", "human", "{}"),
                ("a2", "甲", "auto", json.dumps({"confirmed": "claude_vision"})),
                ("a3", "甲", "auto", json.dumps({"channel": "align"})),
                ("a4", "乙", "auto", json.dumps({"confirmed": "claude_vision"})),
                ("a5", "乙", None, None)]
        for iid, lab, prov, ev in rows:
            c.execute("INSERT INTO instances VALUES (?,?)", (iid, lab))
            c.execute("INSERT INTO admissions VALUES (?,?,?)", (iid, prov, ev))
    assert human_confirmed_counts(str(db)) == {"甲": 1}
    assert human_confirmed_counts(str(db), "human+auto") == {"甲": 2, "乙": 1}
    assert human_confirmed_counts(str(db), "all") == {"甲": 3, "乙": 2}


def test_same_gate_copy_does_not_touch_cached():
    from open_guji_cv.steps.glyph_match import _with_same_gate

    class M:
        cov_high = 0.996
        miss_wmax = 12.0
    m = M()
    g = _with_same_gate(m, 0.995, None)
    assert g is not m and g.cov_high == 0.995 and g.miss_wmax == 12.0
    assert m.cov_high == 0.996
    assert _with_same_gate(m, 0.995, None) is g
