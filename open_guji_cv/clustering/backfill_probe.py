"""回库前核验：待回库的刻例在本书字形库里会撞上哪些形近常用字（2026-11-18，A22，A31 接 guji-manager `ops/lib_backfill.py`）。

## 为什么

史記 g26 回库 9,678 例（库 7,556→17,234）后，r80 多出 987 格待审，482 格是库首位被回库进来的少见字／异体抢走
（為→蒍、市→巿、榆→揄、悦→悅）。回库例的标签看图都对，问题是**形近少见字一进库，常用字格的近邻就落到它身上**。
A22 评估（ai-team `domain/CV/质检/SJ-r80-少见字抢首位-2026-11-18/A22结论.md`）：不在匹配侧加字频先验，
门槛放在回库入库那一步；本模块就是那一步要的探针。

## 做什么

对每个待回库例（字 `char`＋归一图块），用**和 5a 同一套匹配器**（`load_matcher_from_db`＋本书 kNN 限额）
拿它去查现库，取前 `topn` 名候选字（每字取最高 cov），算：

- `self_cov`：`char` 自己在候选里的 cov（库里没这个字、或没进前 k 名时为 None）；
- `rival`、`rival_cov`：前 `topn` 名里 cov 最高的**别的字**；
- `gap`：`self_cov − rival_cov`（`self_cov` 为 None 时按 0 算，即负数＝别的字比自己还像）；
- `flag`：前 `topn` 名里有别的字 `c` 满足 `cov(c) ≥ cov_min`、`self_cov` 为 None 或 `self_cov − cov(c) < gap_max`、
  且 `c` 在库里刻例数 ≥ `common_min` 并多于 `char` 的刻例数（「常用字」按本书库里刻例多寡算，不用语料字频）。
  `flag=True` 的例进库后最可能抢那个常用字的首位，建议不进或要第二路证据。

只读不写：不改库、不改产物，也不进任何 Step 的 `code_deps`，产物指纹不受影响。

## 两种查法，标定结论：要用第二种

1. `probe_one`／`run`：拿待回库例去查现库，看前几名有没有形近常用字。**分不开好坏**：回库的字多半库里 0 例
   （所以才回库），近邻全是别的字。史記 g26 回库 9,678 例对 g25 库回放，以 SJ 剔除单 959 例为负例：
   「常用字刻例 ≥3 倍且 ≥10 例、分差 <0.01」只拦下负例 11%（正例误拦 7%）；放宽到拦下 96% 时正例误拦 89%。
   只当证据记进报告，别拿来当闸。
2. `steal_check`：**回库模拟**。把一批待回库例加进库，拿本书**已放行格**（或现库刻例）去查，看谁的库首位被抢走
   （harm）、谁被救回（help）。这正是 r80 出事的机制，可以直接按「只害不帮」定不进。史記库上拿全部 7,556 个非回库
   刻例当格回放：害 245、帮 147，与逐格两次全量匹配的留一法逐格一致。只重匹配新例进得了 kNN 候选池的格。
   真格（放行格字块）只在跑批机缓存里有，按真格的拦截率要在那边回放。

## 接口

    probe = BackfillProbe(db_path, knn_k=15, per_char=3, per_char_top=10)   # 一次建匹配器，可多次调
    rows = probe.run([(key, char, norm), ...])                              # norm：64×64 归一图块（normalize_patch 之后）
    # 或 probe.run_canonical([(key, char, canonical_bin), ...])            # 二值化 canonical 图，内部 normalize_patch
    sim = probe.steal_check(new_items, cells)   # new_items/cells 同为 (key, 字, 归一图)；cells 用本书已放行格（放行字）
    # → {"harm": {新字: [格键…]}, "help": {字: [格键…]}, "checked": n, "cells": n}；harm 有而 help 没有的新字＝只害不帮

kNN 参数缺省＝cv 缺省（k10、不限额）；按书传入册 yaml 里 `glyph_match` 的 `knn_k／knn_per_char／knn_per_char_top`
（史記 15/3/10），口径才和 5a 一致。`exclude_ids` 可把若干库条目当不在库（比如同一批已入库的回库例，做留一法标定用）。
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np

TOPN = 3
GAP_MAX = 0.01
COV_MIN = 0.90
COMMON_MIN = 3


@dataclass
class ProbeRow:
    key: str
    char: str
    top: list            # [[字, cov], …] 前 topn 名（每字最高 cov）
    first: str | None    # 首位字
    self_cov: float | None
    rival: str | None
    rival_cov: float | None
    gap: float | None    # self_cov − rival_cov（self_cov 缺按 0）；没有别的字时 None
    n_self: int          # char 在库里的刻例数（扣掉 exclude_ids）
    n_rival: int
    flag: bool
    flag_chars: list     # 触发 flag 的别的字
    verdict: str

    def to_dict(self) -> dict:
        return asdict(self)


class BackfillProbe:
    def __init__(self, db_path: str, *, knn_k: int = 10, per_char: int = 0, per_char_top: int = 0,
                 exclude_ids: Iterable[str] = (), matcher=None):
        if matcher is None:
            from .glyph_db import GlyphDB
            from .seeding import load_matcher_from_db
            matcher, _ = load_matcher_from_db(GlyphDB(db_path), knn_k=knn_k)
        m = copy.copy(matcher)
        m.k = knn_k
        m.per_char, m.per_char_top = int(per_char), int(per_char_top)
        drop = set(exclude_ids or ())
        if drop:
            keep = [i for i, x in enumerate(m._ids) if x not in drop]
            m._ids = [m._ids[i] for i in keep]
            m._chars = [m._chars[i] for i in keep]
            m._patches = [m._patches[i] for i in keep]
            m._feats = [m._feats[i] for i in keep]
            m._F = None
            m._rows_of = None
            m._char_set = set(m._chars)
        self.matcher = m
        self.n_lib: dict[str, int] = {}
        for c in m._chars:
            self.n_lib[c] = self.n_lib.get(c, 0) + 1

    def probe_one(self, key: str, char: str, norm: np.ndarray, *, topn: int = TOPN, gap_max: float = GAP_MAX,
                  cov_min: float = COV_MIN, common_min: int = COMMON_MIN, exclude_self: bool = True) -> ProbeRow:
        r = self.matcher.match(norm, exclude_id=key if exclude_self else None)
        best: dict[str, float] = {}
        for c, v in (r.candidates or []):
            best[c] = max(best.get(c, 0.0), float(v))
        top = sorted(best.items(), key=lambda t: -t[1])[:topn]
        self_cov = best.get(char)
        others = [(c, v) for c, v in top if c != char]
        rival, rival_cov = (others[0] if others else (None, None))
        gap = None if rival_cov is None else round((self_cov or 0.0) - rival_cov, 4)
        n_self = self.n_lib.get(char, 0)
        flag_chars = [c for c, v in others
                      if v >= cov_min and (self_cov is None or self_cov - v < gap_max)
                      and self.n_lib.get(c, 0) >= common_min and self.n_lib.get(c, 0) > n_self]
        return ProbeRow(key=key, char=char, top=[[c, round(v, 4)] for c, v in top],
                        first=top[0][0] if top else None,
                        self_cov=None if self_cov is None else round(self_cov, 4),
                        rival=rival, rival_cov=None if rival_cov is None else round(rival_cov, 4), gap=gap,
                        n_self=n_self, n_rival=self.n_lib.get(rival, 0) if rival else 0,
                        flag=bool(flag_chars), flag_chars=flag_chars, verdict=r.verdict)

    def run(self, items: Iterable[tuple[str, str, np.ndarray]], **kw) -> list[ProbeRow]:
        """items：(key, 字, 归一图块)。key 是格号／库条目 id，同一物理格的库条目在查询时摘掉（同 5a 摘自身）。"""
        return [self.probe_one(k, c, n, **kw) for k, c, n in items]

    def steal_check(self, new_items: Iterable[tuple[str, str, np.ndarray]],
                    cells: Iterable[tuple[str, str, np.ndarray]]) -> dict:
        """回库模拟：把 `new_items`（待回库例，(key, 字, 归一图)）加进库，看本书**已放行格** `cells`（(格键, 放行字, 归一图)）
        的库首位会不会变。→ {"harm": {新字: [格键…]}, "help": {新字: [格键…]}, "checked": 重匹配的格数, "cells": 总格数}。

        - harm：加库前首位＝放行字、加库后首位变成别的字（记在加库后的首位字名下；它若不是这批新字，记在 `"<他字>"` 名下）；
        - help：加库前首位≠放行字、加库后＝放行字（记在放行字名下）。
        只重匹配「新例会进它 kNN 候选池」的格（新例 HOG 相似度 ≥ 加库前选进精验的最低一名），其余格首位不可能变，跳过。
        `self` 的库当加库前；同一批新例互相都在加库后的库里（整批回库就是这样）。"""
        new_items = list(new_items)
        base = self.matcher
        aug = copy.copy(base)
        aug._ids, aug._chars = list(base._ids), list(base._chars)
        aug._patches, aug._feats = list(base._patches), list(base._feats)
        aug._char_set = set(base._char_set)
        aug._F = None
        aug._rows_of = None
        for k, c, n in new_items:
            aug.add(k, c, n)
        new_chars = {c for _, c, _ in new_items}
        Fn = aug.library_matrix()[len(base._ids):]
        Fb = base.library_matrix()
        harm: dict[str, list] = {}
        help_: dict[str, list] = {}
        checked = total = 0
        for key, char, norm in cells:
            total += 1
            f = np.asarray(base._feature.extract(norm[None, ...])[0], dtype=np.float32)
            sb = Fb @ f
            excl = base._same_cell_rows(key)
            if excl:
                sb = sb.copy()
                sb[list(excl)] = -np.inf
            top = (base._diverse_top(sb, excl) if getattr(base, "per_char", 0) > 0
                   else [int(j) for j in np.argsort(-sb)[: base.k] if int(j) not in excl])
            floor = min((float(sb[j]) for j in top), default=-np.inf)
            if len(Fn) == 0 or float((Fn @ f).max()) < floor:
                continue
            checked += 1
            rb = base.match(norm, feat=f, exclude_id=key)
            ra = aug.match(norm, feat=f, exclude_id=key)
            b0 = (rb.candidates or [(None,)])[0][0]
            a0 = (ra.candidates or [(None,)])[0][0]
            if b0 == a0:
                continue
            if b0 == char and a0 != char:
                harm.setdefault(a0 if a0 in new_chars else f"<{a0}>", []).append(key)
            elif a0 == char:
                help_.setdefault(char, []).append(key)
        return {"harm": harm, "help": help_, "checked": checked, "cells": total}

    def run_canonical(self, items: Iterable[tuple[str, str, np.ndarray]], **kw) -> list[ProbeRow]:
        """items：(key, 字, canonical 二值图)；先 `normalize_patch`，与入库存的归一图同一把尺。"""
        from .normalize import normalize_patch
        return [self.probe_one(k, c, normalize_patch(b), **kw) for k, c, b in items]
