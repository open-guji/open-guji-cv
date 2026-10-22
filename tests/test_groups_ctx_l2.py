"""M7 块 E：L2 的纯函数部分（建批、解析、两遍合并、查表）。不调任何模型。"""
from pathlib import Path

from open_guji_cv.groups.context import CTX_VER
from open_guji_cv.groups.ctx_l2 import CtxL2Backend, build_batch, ctx_drift, load_prompt, merge_runs, parse_output
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
    be = CtxL2Backend(merge_runs("ry", "日曰", "ry-l2-1", _runs(("日", "high"), ("日", "high")), ctx))
    ok = be.judge(RY, JudgeInput("c", None, window_from_text("二月十一", "奉")))
    assert (ok.char, ok.via) == ("日", "ctx_l2")
    assert be.judge(RY, JudgeInput("c", None, window_from_text("二月十二", "奉"))).why == "ctx_mismatch"
    assert be.judge(RY, JudgeInput("zz", None, window_from_text("", ""))).why == "cache_miss"
    assert be.judge(GROUPS["jys"], JudgeInput("c", None, window_from_text("", ""))).why == "ver_mismatch"


def test_drift_only_far_positions():
    """窗口漂移：目标字两侧各 3 字内必须相同，远处至多差 drift 位才用表里的答案。"""
    left, right = "經義考作一一□二卷註", "未見此本惟一百卷殆"
    ctx = {"c": (left, right)}
    be = CtxL2Backend(merge_runs("ry", "日曰", "ry-l2-1", _runs(("曰", "high"), ("曰", "high")), ctx))
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


def test_other_carries_confidence():
    """「其他」的把握记在 `other_conf`：各遍都 high 才是 high（共字组联合判只认它）。"""
    ctx = {"a": ("一", "二"), "b": ("一", "二")}
    runs = {"m": {"a": {"char": "其他", "conf": "high"}, "b": {"char": "其他", "conf": "mid"}}}
    be = CtxL2Backend(merge_runs("ry", "日曰", "ry-l2-1", runs, ctx))
    a = be.judge(RY, JudgeInput("a", None, window_from_text("一", "二")))
    b = be.judge(RY, JudgeInput("b", None, window_from_text("一", "二")))
    assert (a.char, a.why, a.extra["other_conf"]) == (None, "abstain:other", "high")
    assert b.extra["other_conf"] == "low"


def test_jys_llm_skips_second_of_family_pair():
    """己已巳：前一字也是族字（干支「己巳」的第二字）时不查 L2 表。"""
    from types import SimpleNamespace
    from open_guji_cv.groups.methods import JYS_CTX, MethodInput
    jys = GROUPS["jys"]
    ctx = {"c": ("至嘉定巳", "書成")}
    t = merge_runs("jys", "己已巳", "jys-l2-1", _runs(("已", "high"), ("已", "high")), ctx)
    cfg = SimpleNamespace(l2_tables={"jys": t}, canon=None, l2_drift=0)
    inp = MethodInput(group="jys", members=jys.members, cell_id="c", cands=[], ref=None, cfg=cfg,
                      left="至嘉定巳", right="書成")
    v = JYS_CTX.run(inp)
    assert (v.char, v.why) == (None, "abstain:pair")
