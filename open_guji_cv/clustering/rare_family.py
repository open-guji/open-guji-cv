# -*- coding: utf-8 -*-
"""5b 候选按异体族展开：前几名候选各自的异体族并进候选表（2026-11-16）。

依据（ai-team `domain/CV/字形领域/大字符集候选召回-2026-11-15/README.md` 2.2、2.3，三书人裁 5b 冻结集，
emb 单路、全 Unicode 字表）：类外字首位不等于金标的格里，最大一块是首位给了金标的同族异体
（内→內、歩→步、𠉀→候；殿本 28 个点、史記 19 个点、全唐文 33 个点）。前 10 名并上**首位**那个字的族，
平均 15 个字，召回 91.5→96.0／92.4→95.0／97.1→99.2，除史記差 0.3 个点外都高于直接给前 30 名。

只出候选，不放行、不投票。**不在任何 Step 的 `code_deps` 里**：给审字卡、评测、面板这些读 5b 产物的地方
在读的时候展开，不改 5b 产物，各书不过期。
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

DEFAULT_TOP_M = 1
"""展开前几名的族。实测只展开首位就拿到大部分增益（前 3 名再多 0.2–1.2 个点，候选多 9 个）。"""
DEFAULT_CAP = 12
"""最多追加几个字。常用字的族可以有二三十个成员，卡片放不下。"""


def _family_of(ch: str) -> list[str]:
    from ..hanzi import shared
    try:
        return sorted(shared().family(ch))
    except Exception:
        return []


def expand_family(chars: Iterable[str], top_m: int = DEFAULT_TOP_M, cap: int = DEFAULT_CAP,
                  keep: Callable[[str], bool] | None = None,
                  family_of: Callable[[str], Iterable[str]] | None = None) -> list[tuple[str, str]]:
    """候选字序列 → 要追加的 `[(族成员, 由哪个候选带进来)]`，不含已在候选里的字。

    - 顺序：先按带它进来的候选的名次，同一候选内基本区在前、扩展区在后，再按码位——卡片上先看到通行写法；
    - `keep`：过滤器（比如简体否决 `not is_simplified(c)`），返回假的不追加；
    - `family_of`：换关系来源用（测试、书级异体表），缺省是关系库 `HanziDB.family`
      （不含通假、钓鱼形近、简繁、人审定的 distinct 负边）。
    """
    chars = [c for c in chars if c]
    fam = family_of or _family_of
    seen = set(chars)
    out: list[tuple[str, str]] = []
    for src in chars[:max(0, top_m)]:
        members = [m for m in fam(src) if m and m not in seen and (keep is None or keep(m))]
        members.sort(key=lambda c: (not ("一" <= c[0] <= "鿿"), c))
        for m in members:
            if len(out) >= cap:
                return out
            seen.add(m)
            out.append((m, src))
    return out


def family_hit(cand: Iterable[str], gold: str,
               family_of: Callable[[str], Iterable[str]] | None = None) -> bool:
    """候选首位是不是金标或金标的同族（评测的「族首位」）。两个方向都查：关系库的边不保证对称落盘。"""
    cand = [c for c in cand if c]
    if not cand:
        return False
    top = cand[0]
    if top == gold:
        return True
    fam = family_of or _family_of
    return gold in set(fam(top)) or top in set(fam(gold))
