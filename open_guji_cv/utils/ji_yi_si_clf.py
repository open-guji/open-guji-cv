# -*- coding: utf-8 -*-
"""己/已/巳 分类器（overview#443，Z-jys）：不靠字形、不靠整理本，靠前后的词定字。

- **规则路** `classify(left, right)`：纯函数，只放「语言上站得住、几乎无例外」的搭配（干支前天干/后地支、
  而已、已經类、己意/以己見/自己类）；拿不准一律 None。强真值 0/129 错、新留出 0/36 错（见 overview#443）。
  管线里经字组统一流程用：`config/groups/jys/rules.yaml` 的 `legacy` 收编了它（`seed_admit.group_flow` 的 jys 组，
  文意解法 L1；原开关 `seed_admit.ji_yi_si_clf` 已于 2026-10-18 删除）。
- 答案表路 `Table`/`suggest`（离线大模型两遍＋语料分类器）已于 2026-10-18 删除，管线早不读它，文意 L2 答案表走 `groups/ctx_l2`。

用户 2026-10-09 四条原则：①不靠字形区分；②自动通过的必须准；③靠前后词定字；④第一候选明显优于第二才放行。
研究脚本与评测见 `research/char_groups/jys/`；本模块是它的管线内定型版，两处规则以本模块为准
（`tests/test_ji_yi_si_clf.py` 钉死一致）。
"""
from __future__ import annotations

import hashlib

FAMILY = frozenset("己已巳")
GAN = frozenset("甲乙丙丁戊己庚辛壬癸")
ZHI = frozenset("子丑寅卯辰巳午未申酉戌亥")
ZHI_SAFE = frozenset("丑卯酉亥")                 # 后接这几个几乎只能是「己X」干支
ZHI_NEED_DATE = frozenset("寅辰午申子戌未")      # 「已申」「已未」「已子」另有读法，需日期语境
YEAR_AFTER = frozenset("年歲歳科")
DATE_PREV = frozenset("日月年歲歳朔旬熙治厯曆歷隆正德啓禎慶光豐元")   # 年号末字 / 日期字
JI_PREV = frozenset("自克捨推恕責屈恭")                                    # 自己、克己、捨己、推己、恕己、責己、屈己、恭己
# 10-24 再收窄（A24，vol11–20 册外回测）：剔除 律、由——「古律【已】亡」「相生之律【已】屬乖舛」「艱苦之由【已】得」都被判成己
#（vol19:6:9:14、vol19:135:3:18、vol14:36:2:3），而 vol01–20 没有一格是「律己」「由己」。加 恭：「恭己無爲」（論語「恭己正南面」，
# vol06:32:9:13 被「已＋無」判成已）。
# 10-11 收窄：原表还有 知利舍修反在損厲勵異，语料里这些字后接「己」只占 40–60%，且会在人名／书名／固定词尾误中——
# 「歐陽修【已】稱」「說異【已】著錄」「現在【已】有」都被判成己（vol09:158:5:10、vol07:118:4:13 等），所以剔除。
JI_NEXT_SURE = frozenset("意私欲")                                      # 己意、己私、己欲（几乎无「已意」）
JI_NEXT_GATED = frozenset("見說論")                                     # 己見/己說/己論：要前字是「以參斷…」
JI_GATE_PREV = frozenset("以參斷附申從就徇逞矜騁各據發出持執伸抒肆縱隨存自爲主")
ER_YI_END = frozenset("矣也乎哉耳焉")                         # 「而已矣」「而已也」…：句末才判而已
YI_PREV = frozenset("業既久早無勿弗")                                   # 業已、既已、久已
YI_NEXT = frozenset("經矣佚亡失著足甚多備極盡無非成刻具來上下後前去歿卒故沒")   # 已經、已矣、已佚…
# 「已＋動詞／時間詞」「X＋已」（overview#443，10-10）：语料（daizhige）里「己已巳字位＋后/前一字」，已＋巳（巳多是已的讹写）占比
# ≥0.97、样本 ≥30，再逐条读「己」的例子（多是「已久」「已經」被误写成己）人工筛过；己的真搭配（己見/己說/克己…）不进来。
YI_NEXT2 = frozenset("久定降墾逾滿乆詳畢入嘗")     # 已久、已定、已降、已墾、已逾、已滿、已詳、已畢、已入、已嘗
YI_PREV2 = frozenset("既前現早久所品")   # 既已、前已、現已、早已、久已、所已(言)、品已(上)。
# 「書／中／民／氣／國」语料纯度也高，但名词＋已不稳：vol04:40:4:6「中書【己】未召試」被「書＋已」判错，剔除。


def _g(s: str, i: int) -> str:
    """s[i]（负数从尾取），越界或 □ 返回 ''。"""
    try:
        c = s[i]
    except IndexError:
        return ""
    return "" if c == "□" else c


def classify(left: str, right: str) -> tuple[str | None, str]:
    """→ (字 | None, 规则名)。left/right：刻本读序紧邻的前/后文（□＝未知字）。"""
    p, p2 = _g(left, -1), _g(left, -2)
    n, n2 = _g(right, 0), _g(right, 1)
    # 1 干支：前为天干 → 巳
    if p in GAN and p != "己" and not (p2 in GAN and n in GAN):
        # 前后都是天干（「卜乙丁【己】辛癸等柔日」，vol13:73:9:16）是天干列举，本字是天干「己」，不是地支；不判
      # 前字是「己」时不判：它可能刚被放行成「自己」的己（自己＋已經），不能当干支
        return "巳", "干支:前天干"
    if p == "辰" and n == "間":     # 只认「辰巳間」；其他地支后接「間」不是巳
        return "巳", "干支:辰巳間"
    # 2 干支：后为地支 → 己
    if n in ZHI_SAFE:
        return "己", "干支:后地支"
    if n in ZHI_NEED_DATE and (p in DATE_PREV or n2 in YEAR_AFTER):
        return "己", "干支:后地支(日期语境)"
    # 3 己（反身）
    if p in JI_PREV:
        return "己", "搭配:自己类"
    if n in JI_NEXT_SURE and p != "而":
        return "己", "搭配:己意类"
    if n in JI_NEXT_GATED and p in JI_GATE_PREV:
        return "己", "搭配:以己見类"
    if p == "爲" and n == "有":
        return "己", "搭配:爲己有"
    # 4 已（虚词）
    if p == "而":
        if n == "易":            # 例外：「而【己】易」是书名《己易》；「而已易」也常是「而已。易」，都不在此判
            return None, "例外:而_易"
        if n == "" or n in ER_YI_END:
            return "已", "搭配:而已"
        # 10-24 收窄（A24）：「而◎」后面接谓语时，◎ 常是主语「己」——「同乎人而【己】不以富爲累」「厚於治己而【己】無不修者」
        #「爲十翼而【己】又翼孔子」「不杖衰而【己】與之無服」（vol02:86:7:20、vol03:46:8:8、vol04:219:9:8、vol13:72:7:19）。
        # 只在句末（后字是语气词、□或窗口尽头）判「而已」，其余交文意表；也不让下面的「已＋動詞」规则接手。
        return None, "例外:而◎接谓语"
    if p in YI_PREV:
        return "已", "搭配:業已类"
    if p == "得" and p2 == "不":
        return "已", "搭配:不得已"
    if n and n in "上下" and n2 and n2 in "脫衍闕缺":
        # 校勘语「某字下脫」：本字是被引的字，不是「已下」（「女爲悅己者容【己】下脫者字」，vol09:42:5:6）；不判
        return None, "例外:X下脫"
    if n and n in "前後" and p and (p in ZHI or p in "至自迄"):
        # 「自子至【巳】前六辰」（vol19:143:2:7）：地支或「至」后接前／後是时辰，不是「已前」；不判
        return None, "例外:至巳前"
    if n in YI_NEXT and p not in JI_PREV:
        return "已", "搭配:已經类"
    if n in YI_NEXT2 and p not in JI_PREV:
        return "已", "搭配:已＋動詞/時間词"
    if n == "然" and n2 != "後" and p not in JI_PREV:      # 已然；「己|然後」是句读被吞（無諸己然後非諸人）
        return "已", "搭配:已然"
    if p in YI_PREV2 and n not in JI_NEXT_SURE and n not in ZHI:      # 后字是地支时留给干支规则
        return "已", "搭配:时间词/主语＋已"
    return None, "无规则"


def ctx_key(left: str, right: str, width: int = 30) -> str:
    """答案表的上下文哈希：左文取到最近的 □ 之后、右文取到第一个 □ 之前，各至多 width 字。"""
    l = left.rsplit("□", 1)[-1][-width:]
    r = right.split("□", 1)[0][:width]
    return hashlib.sha1(f"{l}|{r}".encode("utf-8")).hexdigest()[:12]
