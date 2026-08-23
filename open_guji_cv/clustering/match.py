"""字形库优先匹配器（glyph_db_first_design.md §2 的主干件）。

每个新实例先与已验证字形库做匹配，`verify_pair_cov` 三档判决直接沿用：

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

from dataclasses import dataclass, field

import numpy as np

from .features import get_feature
from .verify import COV_HIGH, MISS_WMAX, verify_pair_cov

# 聚类实测漏网的形近家族（g3g4_error_analysis.md §2/§7：在 coverage 判据
# 下真实发生过错并、或对级实测能穿透完美档的字对）。库级 never-match：
# 这两族字互相永不做 same 判定。build_clustering_dataset.py 的难例对
# 生成也引用本表——单一事实源。
NEVER_MATCH_FAMILIES: list[tuple[str, str]] = [
    ("諭", "論"), ("遺", "還"), ("圓", "圖"), ("大", "太"), ("廣", "贋"),
    ("候", "侯"), ("間", "問"), ("已", "巳"), ("曾", "會"), ("選", "過"),
    ("人", "入"), ("未", "末"), ("面", "而"), ("夬", "夫"), ("彖", "象"),
    # 匕/七：margin 标定唯一阈上错例（vol02:37:6:12，diff 分支 OCR 认错）。
    # 本表只防库匹配侧；OCR-only 路径（diff 档）管不到，属残余风险，
    # 出路是 char-ocr 集给 OCR 分支单独立门。
    ("匕", "七"),
    # 日/曰：vol01:10:9:10 实审发现（裘曰修之「曰」，库内「日」对它
    # cov 0.96 已进 unsure 带；OCR 也认成日）。同形程度全表最高。
    ("日", "曰"),
]

_PARTNER: dict[str, set[str]] = {}
for _a, _b in NEVER_MATCH_FAMILIES:
    _PARTNER.setdefault(_a, set()).add(_b)
    _PARTNER.setdefault(_b, set()).add(_a)


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
    """内存字形索引：kNN(特征) 粗排 → verify_pair_cov 精验 → 三档判决。

    与 GlyphDB（SQLite，跨书持久层）解耦：本类只管「一批已验证
    (id, char, 归一图) → 匹配判决」，基准协议与册内增量识别都用它；
    持久层在外面负责准入（provenance）与落盘。
    """

    def __init__(self, feature_backend: str = "hog", k: int = 10,
                 cov_high: float = COV_HIGH, miss_wmax: float = MISS_WMAX):
        self._feature = get_feature(feature_backend)
        self.k = k
        self.cov_high = cov_high
        self.miss_wmax = miss_wmax
        self._ids: list[str] = []
        self._chars: list[str] = []
        self._patches: list[np.ndarray] = []
        self._feats: list[np.ndarray] = []
        self._char_set: set[str] = set()

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
              feat: np.ndarray | None = None) -> MatchResult:
        if not self._ids:
            return MatchResult("diff", None, None, 0.0, 0.0)
        if feat is None:
            feat = self._feature.extract(norm[None, ...])[0]
        F = np.asarray(self._feats)
        sims = F @ np.asarray(feat, dtype=np.float32)
        top = np.argsort(-sims)[: self.k]

        same_hits: list[tuple[float, float, str, str]] = []   # cov,wmax,char,id
        unsure_best: dict[str, float] = {}                    # char -> max cov
        best_cov, best_wmax = 0.0, 0.0
        n_verified = 0
        for j in top:
            j = int(j)
            v = verify_pair_cov(norm, self._patches[j],
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
            partners = _PARTNER.get(char, set()) & self._char_set
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
