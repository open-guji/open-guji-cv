"""M7 块 D：L1 规则引擎。自造数据；真书数据上的质量归 research/m7/ctx/lab.py 与 eval，不进测试。"""
import random
from pathlib import Path

import pytest

from open_guji_cv.groups.ctx_l1 import CtxL1Backend
from open_guji_cv.groups.protocol import JudgeInput, window_from_text
from open_guji_cv.groups.registry import GROUPS
from open_guji_cv.utils.ji_yi_si_clf import classify

ROOT = Path(__file__).resolve().parents[1]


def _backend(tmp_path, body: str, members=None):
    p = tmp_path / "rules.yaml"
    p.write_text("schema: ctx_l1/1\ngroup: t\n" + body, encoding="utf-8")
    return CtxL1Backend(p, members)


def test_abstain_when_no_rule(tmp_path):
    be = _backend(tmp_path, "rules:\n  - {id: a, char: 日, re: '月十◎'}\n")
    assert be.decide("乾隆", "之後")[:2] == (None, "abstain:ctx_l1")


def test_hit_and_conflict_and_veto(tmp_path):
    be = _backend(tmp_path, """rules:
  - {id: d, char: 日, re: '月[十一]{1,2}◎'}
  - {id: q, char: 曰, re: '月十◎'}
  - {id: v, char: null, re: '禁◎'}
""")
    assert be.decide("二月十一", "奉") == ("日", "agree", ["d"])        # q 要求「月十◎」，这里月十一◎不命中
    ch, why, ids = be.decide("二月十", "奉")                              # d、q 同时命中且给不同字
    assert ch is None and why == "disagree:ctx_l1" and set(ids) == {"d", "q"}
    assert be.decide("禁", "x")[:2] == (None, "abstain:veto:v")


def test_unknown_cell_not_matched_across(tmp_path):
    be = _backend(tmp_path, "rules:\n  - {id: a, char: 日, re: '月十◎'}\n")
    assert be.decide("月□", "")[0] is None            # □（未知字）不能被当成「十」


def test_rejects_bad_files(tmp_path):
    with pytest.raises(ValueError):
        _backend(tmp_path, "rules:\n  - {id: a, char: 日, re: '月十'}\n")                          # 缺 ◎
    with pytest.raises(ValueError):
        _backend(tmp_path, "rules:\n  - {id: a, char: 日, re: '◎'}\n  - {id: a, char: 曰, re: '◎'}\n")   # id 重复
    with pytest.raises(ValueError):
        _backend(tmp_path, "rules:\n  - {id: a, char: 己, re: '◎'}\n", members=frozenset("日曰"))      # 字不在组内


def test_judge_uses_window_and_members(tmp_path):
    be = _backend(tmp_path, "rules:\n  - {id: a, char: 日, re: '月十◎'}\n")
    cell = JudgeInput(id="c", ref=None, window=window_from_text("二月十", "奉"))
    v = be.judge(GROUPS["ry"], cell)
    assert (v.char, v.via, v.why) == ("日", "ctx_l1", "agree")


@pytest.mark.parametrize("g", ["jys", "ry", "rr"])
def test_shipped_rules_load_and_stay_in_group(g):
    spec = GROUPS[g]
    be = CtxL1Backend(ROOT / spec.config_dir / "rules.yaml", spec.members)
    assert be.group == g and be.fingerprint


def test_jys_legacy_is_unchanged_when_no_extra_rule(tmp_path):
    """收编 `classify` 后行为逐格不变：只挂 legacy、不挂新规则时，与 classify 对拍（随机拼出的上下文）。"""
    be = _backend(tmp_path, "legacy: open_guji_cv.utils.ji_yi_si_clf:classify\nrules: []\n")
    rnd = random.Random(7)
    pool = list("甲乙丙丁戊庚辛壬癸子丑寅卯辰午未申酉戌亥而業既不得經矣佚亡自克以見說意爲有日月年熙治歷隆然後□") + list("一二三四五六七")
    for _ in range(3000):
        left = "".join(rnd.choice(pool) for _ in range(rnd.randint(0, 6)))
        right = "".join(rnd.choice(pool) for _ in range(rnd.randint(0, 6)))
        ch, rule = classify(left, right)
        got = be.decide(left, right)
        assert got[0] == ch and (got[1] == "agree") == bool(ch)


def test_jys_shipped_rules_are_superset_of_legacy():
    """上线的 jys 规则只在 legacy 弃权时才新给字；legacy 给了字的格，要么一致要么因冲突弃权（不得改成另一个字）。"""
    spec = GROUPS["jys"]
    be = CtxL1Backend(ROOT / spec.config_dir / "rules.yaml", spec.members)
    rnd = random.Random(11)
    pool = list("甲乙丙丁戊庚辛壬癸子丑寅卯辰午未申酉戌亥而業既不得經矣佚亡自克以見說意爲有稱先屬在言引別編全入改日月年熙治歷隆然後□")
    for _ in range(3000):
        left = "".join(rnd.choice(pool) for _ in range(rnd.randint(0, 5)))
        right = "".join(rnd.choice(pool) for _ in range(rnd.randint(0, 5)))
        old, _r = classify(left, right)
        new = be.decide(left, right)[0]
        if old:
            assert new in (old, None)
