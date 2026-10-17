"""M7 块 E：L2 的纯函数部分（建批、解析、两遍合并、查表）。不调任何模型。"""
from pathlib import Path

from open_guji_cv.groups.ctx_l2 import CtxL2Backend, build_batch, load_prompt, merge_runs, parse_output
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
    assert t["cells"]["c"]["char"] == "日" and t["ctx_ver"] == 2 and t["schema"] == "group_clf/1"
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
