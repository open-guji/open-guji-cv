# -*- coding: utf-8 -*-
"""己/已/巳 分类器（overview#443，Z-jys）：不靠字形、不靠整理本，靠前后的词定字。

两路：
- **规则路** `classify(left, right)`：纯函数，只放「语言上站得住、几乎无例外」的搭配（干支前天干/后地支、
  而已、已經类、己意/以己見/自己类）；拿不准一律 None。强真值 0/129 错、新留出 0/36 错（见 overview#443）。
  管线里命中即可放行（`seed_admit.ji_yi_si_clf`）。
- **答案表路** `Table`：离线批量判出的「大模型两遍 + 语料分类器」答案，按 cell id + 上下文哈希为键，管线只查表
  （不在线调模型，保持确定性）。只在两遍一致且与分类器同字时给出建议；历史上有语义错
  （「是己出自入者」被判已），所以缺省**只写建议、不放行**（`ji_yi_si_clf_llm` 另开）。

用户 2026-10-09 四条原则：①不靠字形区分；②自动通过的必须准；③靠前后词定字；④第一候选明显优于第二才放行。
研究脚本与评测见 `research/char_groups/jys/`；本模块是它的管线内定型版，两处规则以本模块为准
（`tests/test_ji_yi_si_clf.py` 钉死一致）。
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

FAMILY = frozenset("己已巳")
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
# 「已＋動詞／時間詞」「X＋已」（overview#443，10-10）：语料（daizhige）里「己已巳字位＋后/前一字」，已＋巳（巳多是已的讹写）占比
# ≥0.97、样本 ≥30，再逐条读「己」的例子（多是「已久」「已經」被误写成己）人工筛过；己的真搭配（己見/己說/克己…）不进来。
YI_NEXT2 = frozenset("久定降墾逾滿乆詳畢入嘗")     # 已久、已定、已降、已墾、已逾、已滿、已詳、已畢、已入、已嘗
YI_PREV2 = frozenset("既前現早久所品")   # 既已、前已、現已、早已、久已、所已(言)、品已(上)。
# 「書／中／民／氣／國」语料纯度也高，但名词＋已不稳：vol04:40:4:6「中書【己】未召試」被「書＋已」判错，剔除。

#: 管线里算「强通道」的放行通道：规则字与它们冲突时不放行，送人审（见 `seed_admit._resolve_ji_yi_si`）
STRONG_CHANNELS = frozenset({"match_ref", "match_solo", "match_margin", "iron", "lane_witness3"})


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
    if p in GAN and p != "己":      # 前字是「己」时不判：它可能刚被放行成「自己」的己（自己＋已經），不能当干支
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
        return "已", "搭配:而已"
    if p in YI_PREV:
        return "已", "搭配:業已类"
    if p == "得" and p2 == "不":
        return "已", "搭配:不得已"
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


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))["cells"]


def suggest(table_path: str, cell_id: str, left: str, right: str) -> dict | None:
    """查答案表 → 建议（字 + 依据）或 None。表项：{ctx, llm:[a,b], lr, lr_margin}。

    建议字 = 两遍大模型一致 ∧ 与语料分类器同字，否则 `char=None`（仍返回表项供看图页参考）。
    上下文哈希对不上（页上读序与离线不同）→ `{"char": None, "why": "ctx_mismatch"}`。"""
    if not table_path:
        return None
    e = _load(table_path).get(cell_id)
    if not e:
        return None
    if e.get("ctx") != ctx_key(left, right):
        return {"char": None, "why": "ctx_mismatch"}
    a, b = (e.get("llm") or [None, None])[:2]
    lr = e.get("lr")
    ch = a if a and a == b and a == lr and a in FAMILY else None
    return {"char": ch, "llm": [a, b], "lr": lr, "lr_margin": e.get("lr_margin"),
            "why": "大模型两遍一致∧语料分类器同字" if ch else "大模型与分类器不一致"}
