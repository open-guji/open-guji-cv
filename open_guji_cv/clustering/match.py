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

import dataclasses
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from .features import get_feature
from .near_shape import NearShapeConfig, decide_pair, trigger_pair
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


# ## 按形区分四对：局部部件比对（2026-09-27，任务书 R-形近四对）
#
# 用户裁定（字形库 11 §〇）：强/強、却/卻、回/囘、并/幷 两形都能区分，不按书
# 统一、算法要学会分。整字相似度分不开是已知负结果（g3g4_error_analysis §核心
# 负结果）——`_PARTNER` 护栏只能把它们一起降成 unsure、两个字都进候选，
# 决胜靠下游 OCR/上下文。这里加一条**只在这四对命中时生效**的局部信号：
# 命中对里差异部件所在的固定分区（不是全局阈值，只影响这 8 个字自己的候选
# 排序），拿查询图与库里两个候选字各自的刻例在这个窗口内的墨迹重合度
# （Dice）决胜。区域按语义定死（不是拟合出来的）：
#
# - 强/強、却/卻：⿰ 结构，共享部件在左（弓 / 谷-类），差异部件在右
#   （强/強 doc 8 的"弓/虽旁"、却/卻 doc 8 的"卩/⼙"都在字的右半）；
# - 回/囘：⿴ 结构，外框共享，差异是框内内容（doc 8"口中口/已"）；
# - 并/幷：doc 8"并/幷上部"——差异是上半到中段那条横笔连不连
#   （幷比并多一笔贯通的"一"，见 scratchpad 实测 v2:bxgb:17:7:12 vs 26:5:3）。
#
# 负结果：想用字体渲染两两对齐后自动求 diff bbox（不用手定分区），结果两个
# 字哪怕结构近乎一样，弹性对齐后残差仍铺满几乎整个 64×64 画布（笔画粗细/
# 微小错位到处都留痕），求不出一个紧凑的差异框——放弃，改用上面这种按
# 语义写死的固定分区（任务书原话允许"IDS 框或固定分区"二选一）。
_SHAPE_DECIDE_PAIRS: tuple[tuple[str, str], ...] = (
    ("强", "強"), ("却", "卻"), ("回", "囘"), ("并", "幷"),
)
_SHAPE_PAIR_OF: dict[str, tuple[str, str]] = {}
for _a, _b in _SHAPE_DECIDE_PAIRS:
    _SHAPE_PAIR_OF[_a] = (_a, _b)
    _SHAPE_PAIR_OF[_b] = (_a, _b)

#: 每对的差异窗口，(y0, y1, x0, x1)，坐标是 `normalize.NORM_SIZE`（64）归一
#: 图块的像素坐标。窗口故意留宽——宁可多包一点共享部件，不要切太紧漏掉
#: 差异笔画的边缘（归一有量化抖动）。
_SHAPE_BOX: dict[frozenset, tuple[int, int, int, int]] = {
    frozenset(("强", "強")): (0, 64, 28, 64),
    frozenset(("却", "卻")): (0, 64, 28, 64),
    frozenset(("回", "囘")): (10, 54, 14, 50),
    frozenset(("并", "幷")): (6, 36, 0, 64),
}

_FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts" / "jigmo"


@lru_cache(maxsize=16)
def _shape_font_template(char: str) -> np.ndarray | None:
    """形近对里没有真刻例时的兜底：拿字体渲染当唯一代表（懒加载、按字缓存）。

    只在 `_local_shape_score` 库里一条对应字的刻例都找不到时才用——比如
    bxgb 库目前 `囘` 一例真刻例都没有（回/囘 3 例全标 `回`，用户 09-27 裁 2
    例该改判），没有它就没法跟候选决胜。字体渲染走跟刻本同一条归一管线
    （`to_canonical` → `normalize_patch`），几何上可比。"""
    paths = sorted(_FONTS_DIR.glob("Jigmo*.ttf"))
    if not paths:
        return None
    from .font_glyphs import FontRenderer
    from .normalize import normalize_patch
    renderer = FontRenderer(paths)
    canon = renderer.render(char)
    if canon is None:
        return None
    return normalize_patch(canon)


def _crop_dice(a: np.ndarray, b: np.ndarray) -> float:
    """窗口内墨迹重合度（Dice）。两边窗口都是空白当满分——共享部件本就该在
    窗口外，窗口内两边都没墨不代表谁更像谁，不该罚。"""
    na, nb = int(a.sum()), int(b.sum())
    if na == 0 and nb == 0:
        return 1.0
    if na == 0 or nb == 0:
        return 0.0
    inter = int(np.logical_and(a, b).sum())
    return 2.0 * inter / (na + nb)


class MatchTimeout(Exception):
    """单格匹配超过时间预算（`match(deadline=)`）。"""


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
    near_shape: dict | None = None  # 近形决胜证据（`near_shape.NearShapeDecision.to_dict`）；没开/没触发为 None

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "char": self.char,
                "matched_id": self.matched_id,
                "cov": round(self.cov, 4), "wmax": self.wmax,
                "candidates": [[c, round(v, 4)] for c, v in self.candidates],
                "guard": self.guard, "n_verified": self.n_verified,
                **({"near_shape": self.near_shape} if self.near_shape is not None else {})}


def _cell_parts(iid: str):
    """实例 / 字位 id → (册, 页, 列, 格号, 格号是否精确)。

    `v2:`（人裁）与裸 `<册>:页:列:格号`（现管线播种/机器准入）都是重键后的
    **格号坐标**，精确（`exact=True`）。`v1:` 前缀（四庫旧管线约 250 例没对上
    现格的旧刻例）是 **idx 坐标**，按 idx+1 换算成格号，但没经形状确认，
    `exact=False`（2026-09-27，字形库 12 §六）。a/b 子格都认。认不出返回 None。
    """
    p = iid.split(":")
    exact = True
    if p and p[0] == "v2":
        p = p[1:]
    elif p and p[0] == "v1":
        p = p[1:]
        exact = False
    if len(p) != 4:
        return None
    b, pg, col, sl = p
    sl = sl.rstrip("ab")
    if not (pg.isdigit() and col.isdigit() and sl.isdigit()):
        return None
    slot = int(sl) if exact else int(sl) + 1
    return b, int(pg), int(col), slot, exact


class GlyphMatcher:
    """内存字形索引：kNN(特征) 粗排 → verify_pair_elastic 精验 → 三档判决。

    与 GlyphDB（SQLite，跨书持久层）解耦：本类只管「一批已验证
    (id, char, 归一图) → 匹配判决」，基准协议与册内增量识别都用它；
    持久层在外面负责准入（provenance）与落盘。
    """

    def __init__(self, feature_backend: str = "hog", k: int = 10,
                 cov_high: float | None = None,
                 miss_wmax: float = MISS_WMAX,
                 verify_method: str = "elastic",
                 local_shape_rerank: bool = False,
                 near_shape: NearShapeConfig | None = None,
                 trusted_ids: set[str] | None = None):
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
        self._F: np.ndarray | None = None      # _feats 堆成的矩阵缓存（add 时失效）
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
        # 按形区分四对的局部部件决胜（模块头「按形区分四对」）。缺省关——
        # 任务书要求「别动全局阈值」，这条只在显式开启时改候选排序，且只
        # 影响候选首位落在这 8 个字上的那些查询，别的字一格都不碰。
        self.local_shape_rerank = local_shape_rerank
        # 近形决胜（clustering/near_shape.py）。None = 关，行为逐位不变。
        # `trusted_ids`：哪些库条目算「人裁刻例」可拿来建原型；None = 全算（评测集全是金标时用）。
        self.near_shape = near_shape
        self.trusted_ids = trusted_ids

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
        self._F = None
        self._char_set.add(char)
        self._rows_of = None

    def _same_cell_rows(self, cell_id: str) -> set[int]:
        """库里与 ``cell_id`` 是**同一个物理格**的所有行（2026-09-26，字形库 08；
        2026-09-27 v1 重键后收紧，字形库 12 §六）。

        同一格在库里不止一种 id：人裁 ``v2:<格>``、播种/机器准入 ``<格>``、四庫 v1 旧管线
        ``<册>:页:列:idx``（``v1:`` 前缀，idx 从 0，按 idx+1 换算格号）。v1 重键之后
        ``v2:``／裸格号前缀都已经是**精确的格号坐标**——两边都精确时格号差要求 ``=0``，
        不然「同列相邻两格恰是同一字」这条真证据会被平白摘掉（08 卡记的代价，v1 重键前
        格号坐标不可信、只能靠 ±2 兜底防自证；重键后前缀是 ``v1:`` 的约 250 例仍是
        idx 换算来的、没经形状确认，**这些仍按 ±2 兜底**）。所以：只要 ``cell_id`` 与某一行
        两边都是精确坐标，格号差必须 ``=0``；只要有一边是未确认的 ``v1:``，保留 ±2 容差。
        """
        q = _cell_parts(cell_id)
        if q is None:
            return {j for j, iid in enumerate(self._ids) if iid == cell_id}
        keys = getattr(self, "_cell_keys", None)
        if keys is None or len(keys) != len(self._ids):
            keys = [_cell_parts(i) for i in self._ids]
            self._cell_keys = keys
        b, pg, col, sl, q_exact = q
        rows = set()
        for j, k in enumerate(keys):
            if k is None or k[:3] != (b, pg, col):
                continue
            diff = abs(k[3] - sl)
            if q_exact and k[4]:
                if diff == 0:
                    rows.add(j)
            elif diff <= 2:
                rows.add(j)
        return rows

    def extract(self, patches: np.ndarray) -> np.ndarray:
        """暴露特征提取，供调用方批量预计算后喂给 add()。"""
        return self._feature.extract(patches)

    def _local_shape_score(self, norm: np.ndarray, char: str,
                           excl: set[int], box: tuple[int, int, int, int]
                           ) -> float | None:
        """`char` 在库里的刻例（排除 `excl`）与查询图在 `box` 窗口内的最佳
        Dice。库里一条这个字的刻例都没有（排除后）就退到字体渲染模板；
        两边都没有返回 None（这个字没法比，交给调用方决定怎么处理）。"""
        y0, y1, x0, x1 = box
        q = norm[y0:y1, x0:x1]
        best: float | None = None
        for j, c in enumerate(self._chars):
            if c != char or j in excl:
                continue
            s = _crop_dice(q, self._patches[j][y0:y1, x0:x1])
            if best is None or s > best:
                best = s
        if best is None:
            tmpl = _shape_font_template(char)
            if tmpl is not None:
                best = _crop_dice(q, tmpl[y0:y1, x0:x1])
        return best

    def _apply_shape_rerank(self, result: "MatchResult", norm: np.ndarray,
                            exclude_id: str | None) -> "MatchResult":
        """按形区分四对：候选首位落在这四对某个字上时，拿差异窗口的局部
        Dice 在它和对手之间决胜（模块头「按形区分四对」）。只可能改
        `candidates` 的顺序/内容，`verdict`/`char`/`guard`/`cov`/`wmax`
        原样不动——不是新判决，只是给下游"首选是哪个字"多一条证据。"""
        if not getattr(self, "local_shape_rerank", False) or not result.candidates:
            return result
        top_char = result.candidates[0][0]
        pair = _SHAPE_PAIR_OF.get(top_char)
        if pair is None:
            return result
        other = pair[1] if top_char == pair[0] else pair[0]
        box = _SHAPE_BOX[frozenset(pair)]
        excl = self._same_cell_rows(exclude_id) if exclude_id is not None else set()
        s_top = self._local_shape_score(norm, top_char, excl, box)
        s_other = self._local_shape_score(norm, other, excl, box)
        if s_other is None or (s_top is not None and s_other <= s_top):
            return result
        new_cands = [(other, s_other)] + [(c, v) for c, v in result.candidates
                                          if c != other]
        return dataclasses.replace(result, candidates=new_cands)

    def _rows_for(self, char: str) -> list[int]:
        rows_of = getattr(self, "_rows_of", None)
        if rows_of is None:
            rows_of = {}
            for j, c in enumerate(self._chars):
                rows_of.setdefault(c, []).append(j)
            self._rows_of = rows_of
        return rows_of.get(char, [])

    def _apply_near_shape(self, result: "MatchResult", norm: np.ndarray,
                          feat: np.ndarray, excl: set[int]) -> "MatchResult":
        """近形决胜（`near_shape.py`）：首选与次优异字 cov 差不足时，用两字的人裁刻例
        求差异区域局部决胜。决出 → 胜者挪到候选首位、证据记进 `near_shape`；
        弃权 → 候选不动、只记弃权理由。`verdict`/`char`/`guard` 一律不动——升档是
        调用方（Step5-a）的事，跟 `consensus_same` 同层。"""
        cfg = getattr(self, "near_shape", None)
        if cfg is None or result.verdict == "same":
            return result
        pair, why = trigger_pair(result.candidates, cfg)
        if pair is None:
            return result
        if why is not None:
            return dataclasses.replace(result, near_shape={"pair": list(pair), "winner": None,
                                                           "reason": why})
        trusted = getattr(self, "trusted_ids", None)
        F = getattr(self, "_F", None)
        if F is None or F.shape[0] != len(self._feats):
            F = np.asarray(self._feats)
        q = np.asarray(feat, dtype=np.float32)
        groups = []
        for c in pair:
            rows = [j for j in self._rows_for(c) if j not in excl
                    and (trusted is None or self._ids[j] in trusted)]
            rows.sort(key=lambda j: (-float(F[j] @ q), j))
            groups.append([self._patches[j] for j in rows[:cfg.max_exemplars]])
        d = decide_pair(norm, groups[0], groups[1], cfg, pair)
        cands = result.candidates
        if d.winner is not None and d.winner != pair[0]:
            # 推翻整字 cov 排序要更硬的条件：只有整字几乎打平时才让局部证据翻盘
            # （char-clustering 回归里 世←但 就是 cov 差 0.027 被局部翻错的）
            gap = cands[0][1] - next(v for c, v in cands if c == pair[1])
            if gap >= cfg.flip_margin:
                d = dataclasses.replace(d, winner=None, reason="flip_blocked")
        if d.winner is not None and d.winner != cands[0][0]:
            w = next(t for t in cands if t[0] == d.winner)
            cands = [w] + [t for t in cands if t[0] != d.winner]
        return dataclasses.replace(result, candidates=cands, near_shape=d.to_dict())

    def match(self, norm: np.ndarray,
              feat: np.ndarray | None = None,
              exclude_id: str | None = None,
              deadline: float | None = None) -> MatchResult:
        """见 `_match`；开了近形决胜（`near_shape`）时在其结果上再走一道 `_apply_near_shape`。

        ``deadline``：`time.monotonic()` 的绝对时刻，None = 不设限。逐个库刻例验证之间检查，
        到点抛 `MatchTimeout`（由 Step5-a 的每格预算接住，记 timeout 转人审）。"""
        if getattr(self, "near_shape", None) is None or not self._ids:
            return self._match(norm, feat, exclude_id, deadline)
        if feat is None:
            feat = self._feature.extract(norm[None, ...])[0]
        r = self._match(norm, feat, exclude_id, deadline)
        excl = self._same_cell_rows(exclude_id) if exclude_id is not None else set()
        return self._apply_near_shape(r, norm, feat, excl)

    def _match(self, norm: np.ndarray,
               feat: np.ndarray | None = None,
               exclude_id: str | None = None,
               deadline: float | None = None) -> MatchResult:
        """``exclude_id`` 把该实例自己从库里摘掉再比（2026-08-25 加）。

        字位一旦进过库，重跑 seed / 复裁时它自己就在 matcher 里，于是
        「库匹配」这一路拿到的是**自证**：cov 1.00、matched_id 就是它
        自己。用户在审查页看到「最近刻例 vol01:22:5:4 cov 1.00」——刻例
        编号和被审的字位是同一个，一眼就露馅。自证不是证据：进库通道
        的整套设计前提是「文本 × 形状两路同源性为零」，自比把形状那一路
        变成了「上次进库时定的字」，独立性归零；``match_solo``（无整理本、
        库 cov≥0.99 单独放行）更是会被自证直接喂饱。
        实测 vol01 队列：1333 行的 matched_id 指向自己，1136 条 cov=1.0。

        2026-09-26 起按**同一物理格**摘（见 `_same_cell_rows`），不再只摘字面相同的那一个 id。
        """
        if not self._ids:
            return MatchResult("diff", None, None, 0.0, 0.0)
        if feat is None:
            feat = self._feature.extract(norm[None, ...])[0]
        # 性能（2026-09-14）：库有几万条时 `np.asarray(self._feats)` 每次要把整张特征表重新堆一遍
        # （一页 179 字位 6.3s，占 Step5-a 43%）。堆一次缓存起来，`add()` 时失效；矩阵内容逐位相同。
        F = getattr(self, "_F", None)          # getattr：测试里有绕过 __init__ 构造的 matcher
        if F is None or F.shape[0] != len(self._feats):
            F = np.asarray(self._feats)
            self._F = F
        sims = F @ np.asarray(feat, dtype=np.float32)
        excl: set[int] = set()
        if exclude_id is not None:
            # 摘自身：把相似度压到最低，排序自然把它甩到末尾。
            excl = self._same_cell_rows(exclude_id)
            if excl:
                sims = sims.copy()
                sims[list(excl)] = -np.inf
        top = np.argsort(-sims)[: self.k]
        if excl:
            top = [j for j in top if int(j) not in excl]
            if not top:
                return MatchResult("diff", None, None, 0.0, 0.0)

        same_hits: list[tuple[float, float, str, str]] = []   # cov,wmax,char,id
        unsure_best: dict[str, float] = {}                    # char -> max cov
        best_cov, best_wmax = 0.0, 0.0
        best_char: str | None = None       # 最好那次验证对应的库字，diff 档拿它当唯一候选
        n_verified = 0
        for j in top:
            j = int(j)
            if deadline is not None and time.monotonic() > deadline:
                raise MatchTimeout(f"已验证 {n_verified}/{len(top)} 个刻例")
            v = self._verify(norm, self._patches[j],
                             cov_high=self.cov_high,
                             miss_wmax=self.miss_wmax)
            n_verified += 1
            if v.f1 > best_cov:
                best_cov, best_wmax = v.f1, v.diff_blob_ratio
                best_char = self._chars[j]
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
                return self._apply_shape_rerank(MatchResult(
                    "unsure", None, None, cov, wmax,
                    sorted(cands.items(), key=lambda t: -t[1]),
                    guard="conflict", n_verified=n_verified), norm, exclude_id)
            partners = _PARTNER.get(char, frozenset())
            if self.guard_needs_partner_in_db:
                partners = partners & self._char_set
            if partners:                                       # 护栏 1
                # sorted：frozenset 的迭代顺序随进程哈希种子变，同分（0.0）候选的先后
                # 原来每次跑都不一样，产物逐字节不可复现（2026-09-14 对比时发现）。
                for p in sorted(partners):
                    cands.setdefault(p, 0.0)
                return self._apply_shape_rerank(MatchResult(
                    "unsure", None, None, cov, wmax,
                    sorted(cands.items(), key=lambda t: -t[1]),
                    guard="never_match", n_verified=n_verified), norm, exclude_id)
            return MatchResult("same", char, iid, cov, wmax,
                               sorted(cands.items(), key=lambda t: -t[1]),
                               n_verified=n_verified)
        if unsure_best:
            return self._apply_shape_rerank(MatchResult(
                "unsure", None, None, best_cov, best_wmax,
                sorted(unsure_best.items(), key=lambda t: -t[1]),
                n_verified=n_verified), norm, exclude_id)
        # diff 档也要把「最像的那个字」带出来。逐对 verify 全判 diff 时
        # `unsure_best` 是空的，这里原先返回空 candidates——于是界面上只剩
        # 一个「? 99%」：cov 明明 0.99，却连它像哪个字都不说。
        #
        # 2026-09-12 实测（vol02 顺序闸那 1078 条待裁切线）：空候选池的 2702
        # 个候选变体里 p50 cov=0.984、810 个 ≥0.99——都是 `verify.py` 那条
        # 「cov≥0.996 **且** wmax≤12」里 cov 够而 wmax 超标（形近护栏）掉下来的。
        # 人要拿这个信息裁切法，只给问号等于没给。
        #
        # ⚠️ 只补证据，不动判决：verdict 仍是 diff、char 仍是 None，下游
        # （seed_admit/context_decide）该弃权还是弃权。候选带 cov 供人和
        # 自动判据参考，不是"库认了这个字"。
        best_cand: list[tuple[str, float]] = []
        if best_char is not None:
            best_cand = [(best_char, best_cov)]
        return self._apply_shape_rerank(MatchResult(
            "diff", None, None, best_cov, best_wmax,
            best_cand, n_verified=n_verified), norm, exclude_id)
