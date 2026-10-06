# -*- coding: utf-8 -*-
"""己已巳 词组/搭配规则（overview#443）。纯函数，输入刻本读序前后文，输出 (字 | None, 规则名)。

只放「语言上站得住、几乎无例外」的搭配（用户 10-06：干支匹配；「而已」「已经…」→已；「己」用于干支或「自己」，
后面常跟 意/見/說；以己意、參以己見）。不看字形、不看整理本、不拟合 val：规则在 dev（vol01–03）上看过，
定型后 val（vol04）、vol05 一次性报。拿不准一律 None，交给语料分类器 / 大模型。

约定：prev = 紧邻前字（读序），next_ = 紧邻后字；n2 = 后第二字，p2 = 前第二字。□ 视作未知。
"""
from __future__ import annotations

GAN = frozenset("甲乙丙丁戊己庚辛壬癸")
ZHI = frozenset("子丑寅卯辰巳午未申酉戌亥")
ZHI_SAFE = frozenset("丑卯酉亥")                 # 后接这几个几乎只能是「己X」干支
ZHI_NEED_DATE = frozenset("寅辰午申子戌未")      # 「已申」「已未」「已子」另有读法，需日期语境
YEAR_AFTER = frozenset("年歲歳科")
DATE_PREV = frozenset("日月年歲歳朔旬熙治厯曆歷隆正德啓禎慶光豐元")   # 年号末字 / 日期字
JI_PREV = frozenset("自克知利舍捨修反推律責由在屈損恕勵厲異")             # 自己、克己、知己…
JI_NEXT_SURE = frozenset("意私欲")                                      # 己意、己私、己欲（几乎无「已意」）
JI_NEXT_GATED = frozenset("見說論")                                     # 己見/己說/己論：要前字是「以參斷…」
JI_GATE_PREV = frozenset("以參斷附申從就徇逞矜騁各據發出持執伸抒肆縱隨存自爲主")
YI_PREV = frozenset("業既久早無勿弗")                                   # 業已、既已、久已
YI_NEXT = frozenset("經矣佚亡失著足甚多備極盡無非成刻具來上下後前去歿卒故沒")   # 已經、已矣、已佚…
FAM = frozenset("己已巳")


def _g(s: str, i: int) -> str:
    """s[i]（负数从尾取），越界或 □ 返回 ''。"""
    try:
        c = s[i]
    except IndexError:
        return ""
    return "" if c == "□" else c


def classify(left: str, right: str) -> tuple[str | None, str]:
    p, p2 = _g(left, -1), _g(left, -2)
    n, n2 = _g(right, 0), _g(right, 1)
    # 1 干支：前为天干 → 巳
    if p in GAN:
        return "巳", "干支:前天干"
    if p in ZHI and n == "間":
        return "巳", "干支:辰巳間"
    # 2 干支：后为地支 → 己
    if n in ZHI_SAFE:
        return "己", "干支:后地支"
    if n in ZHI_NEED_DATE and (p in DATE_PREV or n2 in YEAR_AFTER):
        return "己", "干支:后地支(日期语境)"
    # 3 己（反身）
    if p in JI_PREV and p not in "":
        return "己", "搭配:自己类"
    if n in JI_NEXT_SURE and p != "而":
        return "己", "搭配:己意类"
    if n in JI_NEXT_GATED and p in JI_GATE_PREV:
        return "己", "搭配:以己見类"
    if p == "爲" and n == "有":
        return "己", "搭配:爲己有"
    # 4 已（虚词）
    if p == "而":
        return "已", "搭配:而已"
    if p in YI_PREV:
        return "已", "搭配:業已类"
    if p == "得" and p2 == "不":
        return "已", "搭配:不得已"
    if n in YI_NEXT and p not in JI_PREV:
        return "已", "搭配:已經类"
    return None, "无规则"
