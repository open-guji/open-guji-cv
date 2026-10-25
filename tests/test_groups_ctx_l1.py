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


@pytest.mark.parametrize("g", ["jys", "ry", "rr", "ly", "dt", "wj", "zh", "yh", "xz", "wyu", "yt", "rm",
                               "mz", "yr", "zy", "sb", "js", "em", "fc", "mb", "yz", "guan", "hou", "liang"])
def test_shipped_rules_load_and_stay_in_group(g):
    from open_guji_cv.groups.registry import FLOW_GROUPS
    spec = FLOW_GROUPS[g]
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


# 第三批形近组（论諭／大太／問間／曾會／遺還）：每条各取一个有代表性的词，防规则被改坏；也要有「两可词必须弃权」的反例。
@pytest.mark.parametrize("g,left,right,want", [
    ("ly", "孔子", "語二十篇", "論"), ("ly", "欽奉", "旨", "諭"), ("ly", "曉", "天下", "諭"),
    ("ly", "傳", "知之欽此", None), ("ly", "通", "知之欽此", None),                 # 通諭／傳諭：不给字
    ("dt", "易", "極圖說", "太"), ("dt", "主持", "過", None), ("dt", "官至", "常博士", None),   # 太過、太常／大常：不给字
    ("dt", "經", "學衍義", "大"), ("dt", "宋", "祖皇帝", "太"),
    ("wj", "中", "有訛字", "間"), ("wj", "學", "答", "問"), ("wj", "後去其", "而存其答", None),
    ("zh", "穿鑿附", "", "會"), ("zh", "", "鞏南豐人", "曾"), ("zh", "陳", "同撰", None),
    ("yh", "補", "", "遺"), ("yh", "召", "朝", "還"), ("yh", "以", "其舊", None),
    # 第四批：象彖／王玉／圓圖。彖傳象傳、玉篇／帝王篇、方圓等两可词必须弃权。
    ("xz", "易", "數論", "象"), ("xz", "取", "於天", "象"), ("xz", "孔子", "傳", None), ("xz", "諸卦", "言利涉", None),
    ("wyu", "魏", "弼", "王"), ("wyu", "浙江吳", "墀家藏本", "玉"), ("wyu", "應帝", "篇", "王"), ("wyu", "", "篇", None),
    ("yt", "於河", "洛書", "圖"), ("yt", "", "轉", "圓"), ("yt", "渾", "", "圓"), ("yt", "六十四卦", "圖分配", None),
    # 第五批：蔡傳／王宗傳／太傳／草本等两可词必须不给傅或本以外的字；傅寅、草木蟲魚、兩面等才给。
    ("fc", "宋", "寅撰", "傅"), ("fc", "書", "會選", None), ("fc", "", "", None),
    ("mb", "毛詩草", "蟲魚疏", "木"), ("mb", "毛詩草", "考", None),
    ("em", "南", "設主于戸内", "面"), ("em", "六十四", "加之", None),
])
def test_batch3_groups_rules(g, left, right, want):
    spec = GROUPS[g]
    be = CtxL1Backend(ROOT / spec.config_dir / "rules.yaml", spec.members)
    assert be.decide(left, right)[0] == want


def test_real_symbol_in_window_is_not_target(tmp_path):
    """特殊符号设计 4.4：规则里的 ◎ 是目标位；邻格放行的字真是符号 ◎ 时不许被当成目标位。"""
    be = _backend(tmp_path, "rules:\n  - {id: a, char: 日, re: '月十◎'}\n")
    assert be.decide("月十", "")[0] == "日"
    assert be.decide("月十◎之", "")[0] is None        # 左窗里的真 ◎ 不是目标位
