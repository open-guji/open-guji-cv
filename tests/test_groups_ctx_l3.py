"""M7 块 E：L2 的纯函数部分（建批、解析、两遍合并、查表）。不调任何模型。"""
from pathlib import Path

from open_guji_cv.groups.context import CTX_VER
from open_guji_cv.groups.ctx_l3 import CtxL3Backend, build_batch, ctx_drift, load_prompt, merge_runs, parse_output
from open_guji_cv.groups.protocol import JudgeInput, window_from_text
from open_guji_cv.groups.registry import GROUPS

ROOT = Path(__file__).resolve().parents[1]
RY = GROUPS["ry"]


def test_shipped_prompts_have_ver_and_members():
    for g in ("jys", "ry", "rr"):
        meta, body = load_prompt(ROOT / GROUPS[g].config_dir / "prompt.md")
        assert meta["group"] == g and meta["ver"].startswith(g + "-l2-")
        assert set(meta["members"]) == set(GROUPS[g].members) and body


def test_build_batch_marks_target_and_trims_window():
    msg = build_batch(ROOT / RY.config_dir / "prompt.md", [{"id": "c1", "left": "甲" * 30, "right": "乙" * 30}])
    line = [l for l in msg.splitlines() if l.startswith("c1\t")][0]
    assert line == "c1\t" + "甲" * 20 + "【?】" + "乙" * 20


def test_parse_output_tolerates_fences_and_junk():
    txt = '好的：\n```json\n[{"id":"a","char":"日","conf":"high","why":"X月X日"},{"id":"b","char":"曰","conf":"low"}]\n```'
    got = parse_output(txt)
    assert got["a"]["char"] == "日" and got["b"]["conf"] == "low"
    assert parse_output("没有数组") == {} and parse_output("[坏的") == {}


def _runs(a, b):
    return {"m1": {"c": {"char": a[0], "conf": a[1]}}, "m2": {"c": {"char": b[0], "conf": b[1]}}}


def test_merge_requires_all_runs_agree():
    ctx = {"c": ("二月十一", "奉")}
    t = merge_runs("ry", "日曰", "ry-l2-1", _runs(("日", "high"), ("日", "mid")), ctx)
    assert t["cells"]["c"]["char"] == "日" and t["ctx_ver"] == CTX_VER and t["schema"] == "group_clf/1"
    for a, b, why in ((("日", "high"), ("曰", "high"), "disagree"), (("日", "high"), ("日", "low"), "abstain:low_conf"),
                      (("日", "high"), ("其他", "high"), "abstain:other"), (("日", "high"), ("口", "high"), "abstain:non_member")):
        c = merge_runs("ry", "日曰", "ry-l2-1", _runs(a, b), ctx)["cells"]["c"]
        assert c["char"] is None and c["why"] == why
    c = merge_runs("ry", "日曰", "v", {"m1": {"c": {"char": "日", "conf": "high"}}, "m2": {}}, ctx)["cells"]["c"]
    assert c["why"] == "abstain:missing_run"


def test_backend_lookup_and_mismatch():
    ctx = {"c": ("二月十一", "奉")}
    be = CtxL3Backend(merge_runs("ry", "日曰", "ry-l2-1", _runs(("日", "high"), ("日", "high")), ctx))
    ok = be.judge(RY, JudgeInput("c", None, window_from_text("二月十一", "奉")))
    assert (ok.char, ok.via) == ("日", "ctx_l3")
    assert be.judge(RY, JudgeInput("c", None, window_from_text("二月十二", "奉"))).why == "ctx_mismatch"
    assert be.judge(RY, JudgeInput("zz", None, window_from_text("", ""))).why == "cache_miss"
    assert be.judge(GROUPS["jys"], JudgeInput("c", None, window_from_text("", ""))).why == "ver_mismatch"


def test_drift_only_far_positions():
    """窗口漂移：目标字两侧各 3 字内必须相同，远处至多差 drift 位才用表里的答案。"""
    left, right = "經義考作一一□二卷註", "未見此本惟一百卷殆"
    ctx = {"c": (left, right)}
    be = CtxL3Backend(merge_runs("ry", "日曰", "ry-l2-1", _runs(("曰", "high"), ("曰", "high")), ctx))
    far = JudgeInput("c", None, window_from_text("經義考作一百二卷註", right))       # 左文第 4 位起变了，且短一字
    assert be.judge(RY, far).why == "ctx_mismatch"                                  # 缺省逐字比
    v = be.judge(RY, JudgeInput("c", None, window_from_text("經義考作一百□二卷註", right)), drift=2)
    assert (v.char, v.extra["ctx_drift"]) == ("曰", 1)
    near = JudgeInput("c", None, window_from_text("經義考作一一□二卷注", right))     # 紧邻一字变了
    assert be.judge(RY, near, drift=2).why == "ctx_mismatch"
    many = JudgeInput("c", None, window_from_text("XYZW一一□二卷註", right))
    assert be.judge(RY, many, drift=2).why == "ctx_mismatch"                        # 差 4 位


def test_ctx_drift_counts_and_canon():
    assert ctx_drift("v3:甲乙丙丁戊|己庚辛", "v3:甲乙丙丁戊|己庚辛") == 0
    assert ctx_drift("v3:X乙丙丁戊|己庚辛", "v3:甲乙丙丁戊|己庚辛") == 1
    assert ctx_drift("v3:乙丙丁戊|己庚辛", "v3:甲乙丙丁戊|己庚辛") == 1             # 长度不同，多出的位算差
    assert ctx_drift("v3:甲乙丙丁戊|己庚X", "v3:甲乙丙丁戊|己庚辛") is None          # 右文第 3 位在核心内
    assert ctx_drift("v3:徵乙丙丁戊|己", "v3:徴乙丙丁戊|己", canon=lambda c: {"徴": "徵"}.get(c, c)) == 0
    assert ctx_drift("bad", "v3:a|b") is None


def test_ctx_drift_unknown_now_is_not_a_difference():
    """本格窗口是 □（组流时邻格还没放行）、表键有字：不算差，核心内也一样；反过来表键 □、窗口有字仍算差。"""
    assert ctx_drift("v3:甲乙丙丁戊|祭日礿夏", "v3:甲乙丙丁戊|□□□夏") == 0
    assert ctx_drift("v3:甲乙丙丁戊|□□□夏", "v3:甲乙丙丁戊|祭日礿夏") is None
    assert ctx_drift("v3:甲乙丙丁戊|祭日礿夏", "v3:甲乙丙丁戊|□□□冬") == 1


def test_other_carries_confidence():
    """「其他」的把握记在 `other_conf`：各遍都 high 才是 high（共字组联合判只认它）。"""
    ctx = {"a": ("一", "二"), "b": ("一", "二")}
    runs = {"m": {"a": {"char": "其他", "conf": "high"}, "b": {"char": "其他", "conf": "mid"}}}
    be = CtxL3Backend(merge_runs("ry", "日曰", "ry-l2-1", runs, ctx))
    a = be.judge(RY, JudgeInput("a", None, window_from_text("一", "二")))
    b = be.judge(RY, JudgeInput("b", None, window_from_text("一", "二")))
    assert (a.char, a.why, a.extra["other_conf"]) == (None, "abstain:other", "high")
    assert b.extra["other_conf"] == "low"


def test_jys_llm_skips_second_of_family_pair():
    """己已巳：前一字也是族字（干支「己巳」的第二字）时不查 L2 表。"""
    from types import SimpleNamespace
    from open_guji_cv.groups.methods import JYS_CTX, MethodInput
    jys = GROUPS["jys"]
    ctx = {"c": ("冊末云巳", "手補")}      # 年號在前（嘉定己巳）由 L1 规则 jys-年號己巳 先接，这里用没有年號的「云己巳」
    t = merge_runs("jys", "己已巳", "jys-l2-1", _runs(("已", "high"), ("已", "high")), ctx)
    cfg = SimpleNamespace(l2_tables={"jys": t}, canon=None, l2_drift=0)
    inp = MethodInput(group="jys", members=jys.members, cell_id="c", cands=[], ref=None, cfg=cfg,
                      left="冊末云巳", right="手補")
    v = JYS_CTX.run(inp)
    assert (v.char, v.why) == (None, "abstain:pair")


def test_add_review_takes_reviewer_high_unless_main_was_high():
    """复核模型 high 的组内字就收（主模型 low/mid/「其他」都行）；主模型有一遍以 high 给了别的字、或复核不 high 都不收。"""
    from open_guji_cv.groups.ctx_l3 import add_review
    ctx = {k: ("左", "右") for k in "abcde"}
    t = merge_runs("jys", "己已巳", "jys-l2-1", {"haiku": {
        "a": {"char": "已", "conf": "mid"}, "b": {"char": "已", "conf": "mid"},
        "c": {"char": "其他", "conf": "mid"}, "d": {"char": "己", "conf": "low"}, "e": {"char": "已", "conf": "high"}}},
        ctx, min_conf=("high",))
    t["cells"]["e"].update(char=None, why="abstain:low_conf")       # 假装另一遍不 high，看 high 那一遍挡不挡
    n = add_review(t, "sonnet", {"a": {"char": "已", "conf": "high"}, "b": {"char": "己", "conf": "high"},
                                 "c": {"char": "已", "conf": "high"}, "d": {"char": "己", "conf": "mid"},
                                 "e": {"char": "己", "conf": "high"}}, "己已巳")
    assert n == 3
    assert [t["cells"][k]["char"] for k in "abcde"] == ["已", "己", "已", None, None]
    assert t["cells"]["a"]["why"] == "agree:review" and t["cells"]["b"]["votes"]["sonnet"] == ["己", "high"]
    assert t["models"] == ["haiku", "sonnet"]


def test_add_confirm_marks_strong_and_backend_reports_it():
    from open_guji_cv.groups.ctx_l3 import add_confirm
    ctx = {"a": ("二月十一", "奉"), "b": ("二月十一", "奉")}
    t = merge_runs("ry", "日曰", "ry-l2-1", {"haiku": {"a": {"char": "日", "conf": "high"},
                                                       "b": {"char": "日", "conf": "high"}}}, ctx)
    n = add_confirm(t, {"haiku#2": {"a": {"char": "日", "conf": "high"}, "b": {"char": "日", "conf": "high"}},
                        "sonnet": {"a": {"char": "日", "conf": "high"}, "b": {"char": "日", "conf": "mid"}}})
    assert n == 1 and t["cells"]["a"]["strong"] and "strong" not in t["cells"]["b"]
    be = CtxL3Backend(t)
    assert be.judge(RY, JudgeInput("a", None, window_from_text("二月十一", "奉"))).extra["strong"] is True
    assert "strong" not in be.judge(RY, JudgeInput("b", None, window_from_text("二月十一", "奉"))).extra
