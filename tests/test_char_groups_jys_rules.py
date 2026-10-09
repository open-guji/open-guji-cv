# -*- coding: utf-8 -*-
"""己已巳词组规则（research/char_groups/jys/rules.py，overview#443）。自造上下文，不读真书数据。"""
import importlib.util
from pathlib import Path

_p = Path(__file__).resolve().parents[1] / "research/char_groups/jys/rules.py"
_spec = importlib.util.spec_from_file_location("jys_rules", _p)
rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rules)


def test_ganzhi():
    assert rules.classify("康熙癸", "年")[0] == "巳"
    assert rules.classify("順治", "丑")[0] == "己"


def test_er_yi_and_exception():
    assert rules.classify("不過如此而", "矣")[0] == "已"
    # 书名《己易》被「而已」规则误伤（vol05:36:6:15）：改为弃权
    assert rules.classify("名徒生轇轕而", "易芥八卷浙江")[0] is None


def test_self():
    assert rules.classify("斷以", "意")[0] == "己"
    assert rules.classify("參以", "見")[0] == "己"
    assert rules.classify("克", "復禮")[0] == "己"


def test_abstain():
    assert rules.classify("又", "易一卷")[0] is None


# ── 逐条规则分支的边界（Haiku 试验 5，overview#498）──────────────────────
# 每条分支：≥2 个正例（返回该字与该规则名）+ ≥2 个反例（不该触发：返回 None、无规则或别的规则）。
# 例子字取自 rules.py 的常量集合；拿不准的，不写（见 PR 描述「不确定项」）。


def test_branch_ganzhi_pre_tiangan():                 # 干支:前天干 → 巳
    assert rules.classify("康熙癸", "年") == ("巳", "干支:前天干")
    assert rules.classify("元年丙", "寅") == ("巳", "干支:前天干")
    assert rules.classify("八卷", "年") == (None, "无规则")
    assert rules.classify("文", "之") == (None, "无规则")


def test_branch_ganzhi_chen_si_jian():                # 干支:辰巳間 → 巳
    assert rules.classify("辰", "間") == ("巳", "干支:辰巳間")
    assert rules.classify("時辰", "間") == ("巳", "干支:辰巳間")
    assert rules.classify("辰", "書") == (None, "无规则")
    assert rules.classify("辰", "之") == (None, "无规则")


def test_branch_ganzhi_post_zhi_safe():               # 干支:后地支 → 己（丑卯酉亥）
    assert rules.classify("乾隆", "卯") == ("己", "干支:后地支")
    assert rules.classify("萬曆", "亥") == ("己", "干支:后地支")
    assert rules.classify("萬曆", "書") == (None, "无规则")
    assert rules.classify("一卷", "文") == (None, "无规则")


def test_branch_ganzhi_post_zhi_date_context():       # 干支:后地支(日期语境) → 己
    assert rules.classify("康熙", "寅") == ("己", "干支:后地支(日期语境)")   # 熙 ∈ DATE_PREV
    assert rules.classify("時", "午歲") == ("己", "干支:后地支(日期语境)")   # 后第二字 歲 ∈ YEAR_AFTER
    assert rules.classify("時", "午") == (None, "无规则")
    assert rules.classify("時", "寅書") == (None, "无规则")


def test_branch_self_ji_prev():                       # 搭配:自己类 → 己
    assert rules.classify("克", "復禮") == ("己", "搭配:自己类")
    assert rules.classify("知", "人") == ("己", "搭配:自己类")
    assert rules.classify("文", "人") == (None, "无规则")
    assert rules.classify("而", "之") == ("已", "搭配:而已")      # 而 ∉ JI_PREV，不走自己类


def test_branch_self_ji_yi():                         # 搭配:己意类 → 己（意私欲）
    assert rules.classify("斷以", "欲") == ("己", "搭配:己意类")
    assert rules.classify("輕", "私") == ("己", "搭配:己意类")
    assert rules.classify("而", "意") == ("已", "搭配:而已")      # p=='而' 不走己意类
    assert rules.classify("斷以", "書") == (None, "无规则")


def test_branch_self_yi_ji_jian():                    # 搭配:以己見类 → 己（見說論，前字须在 JI_GATE_PREV）
    assert rules.classify("參以", "論") == ("己", "搭配:以己見类")
    assert rules.classify("以", "說") == ("己", "搭配:以己見类")
    assert rules.classify("書", "說") == (None, "无规则")
    assert rules.classify("書", "論") == (None, "无规则")


def test_branch_wei_ji_you():                         # 搭配:爲己有 → 己
    assert rules.classify("以爲", "有") == ("己", "搭配:爲己有")
    assert rules.classify("所爲", "有") == ("己", "搭配:爲己有")
    assert rules.classify("爲", "書") == (None, "无规则")
    assert rules.classify("爲", "無") == ("已", "搭配:已經类")     # 無 ∈ YI_NEXT，不是爲己有


def test_branch_er_yi():                              # 搭配:而已 → 已
    assert rules.classify("而", "之") == ("已", "搭配:而已")
    assert rules.classify("不過如此而", "矣") == ("已", "搭配:而已")
    assert rules.classify("而", "易") == (None, "例外:而_易")      # 进例外，不进而已
    assert rules.classify("書", "之") == (None, "无规则")


def test_branch_er_yi_exception():                    # 例外:而_易 → 弃权
    assert rules.classify("而", "易") == (None, "例外:而_易")
    assert rules.classify("名徒生轇轕而", "易芥八卷浙江") == (None, "例外:而_易")
    assert rules.classify("書", "易") == (None, "无规则")
    assert rules.classify("而", "文") == ("已", "搭配:而已")       # 不是例外


def test_branch_ye_yi_class():                        # 搭配:業已类 → 已（業既久早無勿弗）
    assert rules.classify("業", "文") == ("已", "搭配:業已类")
    assert rules.classify("既", "書") == ("已", "搭配:業已类")
    assert rules.classify("克", "書") == ("己", "搭配:自己类")      # 克 ∈ JI_PREV 先走自己类
    assert rules.classify("文", "書") == (None, "无规则")


def test_branch_bu_de_yi():                           # 搭配:不得已 → 已
    assert rules.classify("不得", "文") == ("已", "搭配:不得已")
    assert rules.classify("而不得", "書") == ("已", "搭配:不得已")
    assert rules.classify("得", "文") == (None, "无规则")
    assert rules.classify("未得", "文") == (None, "无规则")


def test_branch_yi_jing_class():                      # 搭配:已經类 → 已（經矣佚亡…）
    assert rules.classify("文", "經") == ("已", "搭配:已經类")
    assert rules.classify("人", "矣") == ("已", "搭配:已經类")
    assert rules.classify("克", "經") == ("己", "搭配:自己类")      # 己类先走
    assert rules.classify("文", "書") == (None, "无规则")
