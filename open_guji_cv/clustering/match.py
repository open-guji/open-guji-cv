"""字形库优先匹配器（glyph_db_first_design.md §2 的主干件）。

每个新实例先与已验证字形库做匹配，`verify_pair_elastic` 三档判决直接沿用：

- same（完美匹配）→ 继承库条目的 surface char，识别完成；
- unsure → 命中条目的字进候选集（带 cov 当先验），交 OCR+上下文裁决；
- diff → 纯 OCR+上下文分支（可能是库中没有的新字）。

两道库级护栏（设计 §3，簇级传播错标的教训）：

1. **never-match 表**：形近漏网家族（諭/論、大/太…）的条目互相永不
   判 same——只要库里存在对家的字，命中即降档 unsure，强制走候选+
   上下文。几何判据打不过的敌人交给语义层。
2. **同档冲突降档**：same 档同时命中两个不同的字（库内不自洽，或查询
   本身骑在两字之间）→ 降档 unsure，两个字都进候选。

证据纪律：每次匹配返回完整 `MatchResult`（匹配了哪个条目、cov/wmax、
候选先验、触发了哪条护栏），调用方**必须**随标注结果一起落盘——
库条目改判时靠它重放受影响实例，纠错才能局部化。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

from .features import get_feature
from .verify import (COV_HIGH, ELASTIC_COV_HIGH, MISS_WMAX,
                     verify_pair_cov, verify_pair_elastic)

# 形近家族表搬到 confusable.py 了（三张表：手工核过的 / 人裁确认的 / 字体
# 自动跑的，各自门槛不同的理由写在那边的模块注释里）。这里保留
# `NEVER_MATCH_FAMILIES` 的再导出：seeding.NEAR_FORM_CHARS 与
# build_clustering_dataset.py 的难例对生成都引它，**只认手工那张**——
# 那边命中要拦掉采信通道，代价高，不能拿自动表去喂。
from .confusable import NEVER_MATCH_FAMILIES, partners as _partners  # noqa: F401

# 匹配侧的降档护栏用**并起来的那张**：命中只是 same → unsure，还有候选 +
# 上下文兜底，代价低，宁可多拦。留出实测（eval_guard_ceiling.py）：
# 闸 0.9933 / recall 0.196 → 闸 0.9809 / recall 0.544，precision 仍 0.999。
_PARTNER: dict[str, frozenset[str]] = _partners()


@dataclass
class MatchResult:
    """一次库匹配的完整证据（设计 §3 纪律 1：逐实例证据，不做盲传播）。"""
    verdict: str                    # "same" | "unsure" | "diff"
    char: str | None                # same 档：继承的 surface char
    matched_id: str | None          # same 档：命中的库条目实例 id
    cov: float                      # same 档命中的覆盖率（或最好一次验证）
    wmax: float                     # 同上的窗口残差
    candidates: list[tuple[str, float]] = field(default_factory=list)
    #                               # unsure 档：字 → cov 先验，降序
    guard: str | None = None        # 触发的护栏："never_match" | "conflict"
    n_verified: int = 0             # 本次做了几对 verify

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "char": self.char,
                "matched_id": self.matched_id,
                "cov": round(self.cov, 4), "wmax": self.wmax,
                "candidates": [[c, round(v, 4)] for c, v in self.candidates],
                "guard": self.guard, "n_verified": self.n_verified}


class GlyphMatcher:
    """内存字形索引：kNN(特征) 粗排 → verify_pair_elastic 精验 → 三档判决。

    与 GlyphDB（SQLite，跨书持久层）解耦：本类只管「一批已验证
    (id, char, 归一图) → 匹配判决」，基准协议与册内增量识别都用它；
    持久层在外面负责准入（provenance）与落盘。
    """

    def __init__(self, feature_backend: str = "hog", k: int = 10,
                 cov_high: float | None = None,
                 miss_wmax: float = MISS_WMAX,
                 verify_method: str = "elastic"):
        self._feature = get_feature(feature_backend)
        self._verify = (verify_pair_elastic if verify_method == "elastic"
                        else verify_pair_cov)
        if cov_high is None:      # 两个判据各标各的闸，别互相借用
            cov_high = (ELASTIC_COV_HIGH if verify_method == "elastic"
                        else COV_HIGH)
        self.verify_method = verify_method
        self.k = k
        self.cov_high = cov_high
        self.miss_wmax = miss_wmax
        self._ids: list[str] = []
        self._chars: list[str] = []
        self._patches: list[np.ndarray] = []
        self._feats: list[np.ndarray] = []
        self._char_set: set[str] = set()
        # 护栏 1 要不要求「对家的字已经在库里」。
        #
        # 曾经要求过，是个**盲区**：库里有 千、没有 干 时，第一个 干 进来，
        # 匹配判 same→千，而护栏去查「千 的对手 干 在不在库里」——不在，
        # 于是不拦。可这正是会出错的那一刻：一个字**第一次出现**时，库里
        # 只有它的形近对家，没有它自己。闸放到 0.97 实测，两条错配
        # （vol01:43:1:4 干←千、vol02:145:6:17 長←畏）**全是这个形态**，
        # 而 干/千、長/畏 两对在形近表里都在（0.999 / 0.9915），表没漏，
        # 是这个 `& self._char_set` 把护栏关掉了。
        # 默认改成不要求；GUJI_GUARD_IN_DB=1 可切回老行为做对照。
        self.guard_needs_partner_in_db = os.environ.get("GUJI_GUARD_IN_DB") == "1"

    def __len__(self) -> int:
        return len(self._ids)

    def add(self, instance_id: str, char: str, norm: np.ndarray,
            feat: np.ndarray | None = None) -> None:
        """入库一个已验证实例。feat 可传预计算特征（批量场景省重复提取）。"""
        if feat is None:
            feat = self._feature.extract(norm[None, ...])[0]
        self._ids.append(instance_id)
        self._chars.append(char)
        self._patches.append(norm)
        self._feats.append(np.asarray(feat, dtype=np.float32))
        self._char_set.add(char)

    def extract(self, patches: np.ndarray) -> np.ndarray:
        """暴露特征提取，供调用方批量预计算后喂给 add()。"""
        return self._feature.extract(patches)

    def match(self, norm: np.ndarray,
              feat: np.ndarray | None = None,
              exclude_id: str | None = None) -> MatchResult:
        """``exclude_id`` 把该实例自己从库里摘掉再比（2026-08-25 加）。

        字位一旦进过库，重跑 seed / 复裁时它自己就在 matcher 里，于是
        「库匹配」这一路拿到的是**自证**：cov 1.00、matched_id 就是它
        自己。用户在审查页看到「最近刻例 vol01:22:5:4 cov 1.00」——刻例
        编号和被审的字位是同一个，一眼就露馅。自证不是证据：进库通道
        的整套设计前提是「文本 × 形状两路同源性为零」，自比把形状那一路
        变成了「上次进库时定的字」，独立性归零；``match_solo``（无整理本、
        库 cov≥0.99 单独放行）更是会被自证直接喂饱。
        实测 vol01 队列：1333 行的 matched_id 指向自己，1136 条 cov=1.0。
        """
        if not self._ids:
            return MatchResult("diff", None, None, 0.0, 0.0)
        if feat is None:
            feat = self._feature.extract(norm[None, ...])[0]
        F = np.asarray(self._feats)
        sims = F @ np.asarray(feat, dtype=np.float32)
        if exclude_id is not None:
            # 摘自身：把相似度压到最低，排序自然把它甩到末尾。
            sims = sims.copy()
            for j, iid in enumerate(self._ids):
                if iid == exclude_id:
                    sims[j] = -np.inf
        top = np.argsort(-sims)[: self.k]
        if exclude_id is not None:
            top = [j for j in top if self._ids[int(j)] != exclude_id]
            if not top:
                return MatchResult("diff", None, None, 0.0, 0.0)

        same_hits: list[tuple[float, float, str, str]] = []   # cov,wmax,char,id
        unsure_best: dict[str, float] = {}                    # char -> max cov
        best_cov, best_wmax = 0.0, 0.0
        n_verified = 0
        for j in top:
            j = int(j)
            v = self._verify(norm, self._patches[j],
                             cov_high=self.cov_high,
                             miss_wmax=self.miss_wmax)
            n_verified += 1
            if v.f1 > best_cov:
                best_cov, best_wmax = v.f1, v.diff_blob_ratio
            if v.verdict == "same":
                same_hits.append((v.f1, v.diff_blob_ratio,
                                  self._chars[j], self._ids[j]))
            elif v.verdict == "unsure":
                c = self._chars[j]
                unsure_best[c] = max(unsure_best.get(c, 0.0), v.f1)

        if same_hits:
            same_hits.sort(key=lambda t: -t[0])
            cov, wmax, char, iid = same_hits[0]
            same_chars = {c for _, _, c, _ in same_hits}
            cands = dict(unsure_best)
            for c2, w2, ch2, _ in same_hits:
                cands[ch2] = max(cands.get(ch2, 0.0), c2)
            if len(same_chars) > 1:                            # 护栏 2
                return MatchResult(
                    "unsure", None, None, cov, wmax,
                    sorted(cands.items(), key=lambda t: -t[1]),
                    guard="conflict", n_verified=n_verified)
            partners = _PARTNER.get(char, frozenset())
            if self.guard_needs_partner_in_db:
                partners = partners & self._char_set
            if partners:                                       # 护栏 1
                for p in partners:
                    cands.setdefault(p, 0.0)
                return MatchResult(
                    "unsure", None, None, cov, wmax,
                    sorted(cands.items(), key=lambda t: -t[1]),
                    guard="never_match", n_verified=n_verified)
            return MatchResult("same", char, iid, cov, wmax,
                               sorted(cands.items(), key=lambda t: -t[1]),
                               n_verified=n_verified)
        if unsure_best:
            return MatchResult(
                "unsure", None, None, best_cov, best_wmax,
                sorted(unsure_best.items(), key=lambda t: -t[1]),
                n_verified=n_verified)
        return MatchResult("diff", None, None, best_cov, best_wmax,
                           n_verified=n_verified)
