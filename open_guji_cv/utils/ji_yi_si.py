# -*- coding: utf-8 -*-
"""己 / 已 / 巳：字形只定「是这一族」，具体是哪个字由文意定。

用户 2026-09-26：「这几个字在古文里都是乱写的，每次都只能根据上下文判断具体是哪一个。
先通过字形匹配确定是这三个字这一类，具体是什么要根据上下文。」刻本里三字的刻法常常不分
（bxgb 影子核对裁过 3 处「己丑/癸巳」，字形库给的都是另一个），所以本族**不按字形分**。

`resolve(prev, next_, ref)` 的次序（先命中先用）：
1. **干支**：前一字是天干 → 巳（地支，癸巳/乙巳；另认「辰巳間」）；后一字是地支 → 己（天干，己丑/己卯）。
   日记、年谱里干支极多，这条几乎不会错，且压过整理本（整理本也有录错的）。
2. **时辰**：后一字是 初 / 正 / 時 / 刻 → 巳（巳初、巳時）。
3. **整理本**给了本族的字 → 用它（整理本是现成的文意判断）。
4. 「己」的常见搭配（自己、克己、知己、己任、己見…）→ 己。
5. 整理本给「己」→ 己（缺省只信它给的「己」，见 `resolve` 注释）。
6. 其余 → 已（文中绝大多数是「已經、而已、不得已」）。

人裁永远优先于这里：人定的就是文意判断（见 `seed_admit`）。
"""
from __future__ import annotations

FAMILY = frozenset("己已巳")
_GAN = frozenset("甲乙丙丁戊己庚辛壬癸")
_ZHI = frozenset("子丑寅卯辰巳午未申酉戌亥")
_SHI_AFTER = frozenset("初正時刻")
_DATE_PREV = frozenset("日月年歲一二三四五六七八九十廿卅朔旬")
_YEAR_AFTER = frozenset("年歲歳")
# 「己」（自身）的常见搭配：前字 / 后字。其余情形文中几乎都是「已」（已經、而已、不得已、已而）。
_JI_PREV = frozenset("自克知異利舍捨修反推律責由在屈損恕勵厲")   # 「正」不收：實測「正已」誤判
_JI_NEXT = frozenset("任身意私欲")   # 「見」不收：「已見」比「己見」常見（實測兩處誤判）


def resolve(prev: str | None, next_: str | None, ref: str | None,
            use_ref: str = "ji_only", next2: str | None = None) -> tuple[str | None, str]:
    """→ (定下的字 | None, 依据)。只对本族字位调用。

    `use_ref`：整理本怎么用。四庫實測整理本本身也把「已」寫成「巳」（「而巳」「不巳」），
    所以缺省只在它給「己」且上面規則都沒命中時參考（`ji_only`）；`all` = 整理本給什麼用什麼；`none` = 不用。
    """
    if prev and prev in _GAN:
        return "巳", "干支:前为天干"
    if prev and prev in _ZHI and next_ == "間":
        return "巳", "干支:辰巳之間"      # 只认「X巳間」；「未已」「巳已」这类前字是地支却是「已」
    if next_ and next_ in _ZHI and (next_ != "未" or (prev and prev in _DATE_PREV)
                                    or (next2 and next2 in _YEAR_AFTER)):
        # 「未」多是否定词（而已未嘗、已未），只有日期语境（X日己未）或后接年/歲（稱己未歲）才当干支
        return "己", "干支:后为地支"
    if next_ and next_ in _SHI_AFTER:
        return "巳", "时辰"
    if (prev and prev in _JI_PREV) or (next_ and next_ in _JI_NEXT):
        return "己", "搭配:自己一类"
    if ref and ref in FAMILY and (use_ref == "all" or (use_ref == "ji_only" and ref == "己")):
        return ref, "整理本"
    return "已", "默认:已"
