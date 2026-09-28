# -*- coding: utf-8 -*-
"""控制台 · 定字审查。

待审卡片 / 裁决回读 / 一列的上下文

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

import cv2
import json
from collections import Counter

import numpy as np

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .. import deps
from ..auth import require_reviewer
from ..errors import maps_http
from .review_cluster import CLUSTER_THR, cluster_tiles
from ...clustering import cnn_candidates
from ...clustering.confusables import load_pairs
from ...core.anchor import x_tr_to_tl
from ...core.book import load_book
from ...core.spec import cell_key, column_key, page_key
from ...core.step import RunContext
from ...errors import EncodeFailed, ImageMissing
from ...review.borrow_first import first_pick_mode
from ...review.cards import (_align_ref_maps, cached_cards, cards, parse_class_filter,
                              parse_doubt_filter)
from ...review.cell_shrink_rand import rand_sample
from ...review.verdict_view import review_verdicts, verdicts_by_question
from ...steps._warpmap import ColumnMapper
from ...utils.preclean import effective_raw_path
from ...utils.image_io import imread as cv_imread, imwrite as cv_imwrite

router = APIRouter(dependencies=[Depends(require_reviewer)])



# ── 定字审查（C2：审查搬进控制台，不再走外部 artifact）────────────────
#
# 用户 2026-09-04 定：「审查也放控制台。之前的审查页需要复用的话，也迁移到
# 控制台。」这一组 API 就是那件事的后端：待审卡片从 `seed_admit` 产物来，
# 裁决直接 POST /api/events（既有接口），再走既有的路由 → glyphdb_admit。
# **不新造协议**——事件信封、批次登记、路由表全部沿用。


@router.get("/api/review/cards")
def api_review_cards(response: Response, book: str, pages: str = "dev_set", limit: int = 400,
                     only: str = "review", gate_cut: bool = True,
                     skip_decided: bool = True, group: str = "",
                     sample_limit: int = 60, cluster: str = "auto",
                     cluster_thr: float | None = None, doubt: str = "", cls: str = "") -> dict:
    """待审卡片：一格一张，带图块 URL、库/OCR/上下文三路证据与疑问。

    装配在 `review/cards.py`（C2 搬出去的，云端道与 CLI 直接能调）。

    `gate_cut`：顺序闸——格位旁边那条切分线有**多种切法**且还没 review 时，
    这个字位先不出卡（用户 2026-09-10：先 review 切分线，再 review 字符）。
    被挡下的在返回值的 `blocked` 里，面板显示剩余条数。

    `skip_decided`：跳过全书所有批次已裁过的字位（用户 2026-09-16，默认开）——
    `limit` 于是数的是**净新卡**，载入 N 张就是 N 张真待裁的。

    `group="char"`：按字种批审（任务书-C-待审卡按字种批审，2026-09-27）——
    不再一格一张，改按「AI 首选字」把待审格摊成组，供前端「一个字种一屏，
    多格一起确认」用。这一模式下 `limit` 不生效（要的是**全量**待审格才能
    如实报每组 n 与页码分布），组内样例数由 `sample_limit` 单独控制。

    `group="shape"`：按形聚类分组（任务书-C-批审按形聚类分组，2026-09-27）——
    `group="char"` 的进阶版：AI 首选字系统性认错方向的形近对（今/令、玉/王、
    大/天……）会把两种真实形状混进同一个字种组，这里先按形近对表把互相混淆
    的字种池化，池内再用 CNN embedding 按形状聚类拆开。同样不受 `limit` 截断。

    `cluster`（overview #166，2026-09-28，只对 `group=char/shape` 生效）：组内再按
    r5 embedding 余弦聚成小簇，**每簇只给一张代表图**（`tiles` 换成各簇代表图，
    `clusters[i]` 与 `tiles[i]` 对齐，带「×N」与全部成员 id），一屏要加载的图从
    几十张降到几张。`auto`（缺省）= 书 yaml 设了 `params.review.first_pick` 才开
    （借库书，embedding 在算首选时已经算好，直接复用）；`on`/`off` 强制。关着时
    返回值与改前逐字节一样。`cluster_thr` 覆盖缺省门槛（`review_cluster.CLUSTER_THR`）。

    `doubt`（overview#215）：按 doubt 码筛（`occluded,channel_off`；`*` = 不筛只计数；
    `_none` = 一个码都没有的卡），给了就在响应里加 `doubt_counts`/`doubt_total`，前端据此画
    「按原因」筛选按钮。三种模式（逐格 / `group=char` / `group=shape`）都认。不传时与改前逐字节
    一致（缓存键也不变）。语法与计数口径见 `review/cards.py::parse_doubt_filter` / `cards()`。

    `cls`（overview#247）：按**类别**审——一张卡只归优先级最高的一类（`review/cards.py::
    REVIEW_CLASSES`）。`*` = 不筛只计数，类别键 = 只出这一类；给了就在响应里加
    `class_counts`/`class_total`/`classes`，每张卡带 `cls`。只对逐格模式生效。不传时与改前一致
    （缓存键也不变）。

    **结果缓存**（#166）：整个响应按（书，全部参数，产物 manifest，事件水位，库指纹）
    落 `cache_root()/review_cards/`，见 `review/cards.py::cached_cards`。人裁一写入
    水位就变、自动失效。命中与否看响应头 `X-Cards-Cache: mem|disk|miss`。
    """
    if cluster not in ("auto", "on", "off"):
        raise HTTPException(400, f"cluster 只认 auto/on/off，得到 {cluster!r}")
    st = deps.product_store()
    req = {"pages": pages, "limit": limit, "only": only, "gate_cut": gate_cut,
           "skip_decided": skip_decided, "group": group, "sample_limit": sample_limit}
    if group in ("char", "shape"):
        req.update(cluster=cluster, cluster_thr=cluster_thr)
    try:
        parse_doubt_filter(doubt)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if doubt.strip():
        # 只在给了时进键：不传 doubt 的请求键与改前相同，#166 已落盘的缓存照样命中
        req["doubt"] = doubt
    try:
        parse_class_filter(cls)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if cls.strip():
        req["cls"] = cls           # 同上：只在给了时进键

    def compute() -> dict:
        if group == "shape":
            return cards_by_shape(book, pages, only, st, gate_cut=gate_cut,
                                  skip_decided=skip_decided, sample_limit=sample_limit,
                                  cluster=cluster, cluster_thr=cluster_thr, doubt=doubt)
        if group == "char":
            return cards_by_char(book, pages, only, st, gate_cut=gate_cut,
                                 skip_decided=skip_decided, sample_limit=sample_limit,
                                 cluster=cluster, cluster_thr=cluster_thr, doubt=doubt)
        if not doubt.strip() and not cls.strip():
            return cards(book, pages, limit, only, st, gate_cut=gate_cut,
                         skip_decided=skip_decided)
        return cards(book, pages, limit, only, st, gate_cut=gate_cut,
                     skip_decided=skip_decided, doubt=doubt, cls=cls)

    res, how = cached_cards(book, req, compute, st)
    response.headers["X-Cards-Cache"] = how
    return res



@router.get("/api/review/verdicts")
def api_review_verdicts(batch: str) -> dict:
    """读回某批次已经裁过的字位——**刷新页面不该重审一遍**。装配在 `review/verdict_view.py`。"""
    return review_verdicts(batch, deps.event_log())


@router.get("/api/verdicts")
def api_verdicts(batch: str, question: str | None = None) -> dict:
    """**通用读回**：本批（可按 question 过滤）已裁条目的原始 payload。

    收敛此前的四份实现（本文件 + cutline / column_review / slot_count_review /
    border_review 各一份，返回形状四种）。新增裁决台直接用这条，不必再抄。
    去重按 `(question, key)` 而非 key——切线与定字的 key 形状完全一样，
    只按 key 去重会把没裁过的字位误当已裁。详见 `verdicts_by_question`。
    """
    return verdicts_by_question(batch, question, deps.event_log())



# ── 按字种批审（2026-09-27，任务书-C-待审卡按字种批审）───────────────
#
# 背景：`/api/review/cards` 一格一张，逐格裁很慢；Step8 对勘队列能按字
# 「N 处一起裁」，但只管对勘发现的疑点，管不到 `admit=False` 的待审格。
# 全唐文人审率偏高（v006 26.72%），要先积累本书字形——最高效的办法是
# 「一个字种一屏，多格一起确认」。这一段只**读**卡片、**分组**、**排序**，
# 不碰写入：提交仍旧走既有的 `POST /api/events`（前端逐格拼 confirm 事件），
# 不新造协议，也不改 `seed_admit`（任务书边界）。


def _top_pick(card: dict) -> str | None:
    """待审格的「AI 首选字」——分组的键。

    没接 Step6-AI 的书（`ai`/`groups` 恒为 `None`，四庫等）退到既有的定字
    兜底链，与 `_column_slots` 同一顺序（上下文 → 库候选 → OCR）：卡片本来
    就是照这个优先级给"这格大概是什么字"的，分组用同一把尺子，不另起一套。
    Step6-AI 首组有多个候选字（AI 也没拿定主意）时取候选里排第一的那个
    当组名——不影响谁进哪组要紧的是"型内一致"，组名只是标签，人翻开一屏
    一眼就看得出图对不对。
    """
    ai = card.get("ai")
    groups = card.get("groups")
    if ai and groups:
        rank = ai.get("rank") or []
        if rank:
            gid = rank[0].get("group")
            g = next((x for x in groups if x.get("id") == gid), None)
            if g and g.get("members"):
                return g["members"][0]
    # 借库书的 CNN 原型首选（`review/borrow_first.py`，书 yaml `params.review.first_pick`
    # 开了才有 `first`；四庫、北行恒无此键，走下面原来的链，分组逐字节不变）。
    # 排在上下文之前：借库书的上下文字也是从像素候选里挑的，像素排名本身就歪。
    first = card.get("first")
    if first and first.get("char"):
        return first["char"]
    ctx = card.get("ctx")
    if ctx and ctx.get("char"):
        return ctx["char"]
    db = card.get("db")
    if db and db.get("candidates"):
        return db["candidates"][0][0]
    ocr = card.get("ocr")
    if ocr:
        return ocr[0][0]
    return None


def _group_key(card: dict) -> tuple[str, str | None]:
    """分组键：`(首选字, mismatch_ref_char)`。

    首选字与整理本对齐字（`ref.char`）不同的格**单独成组**，不与「首选字
    ==对齐字，或本页压根没有对齐字」的格混在一起（任务书§做什么·1）——
    这批格恰恰是最该被人逐条盯着看的，混进大部队里"缺省全选"风险最高。
    取不到首选字（三路证据都没有）的格归进 `__unresolved__` 组，不丢弃——
    分组要对得上待审总数（验收标准），有格必须有组能装。
    """
    top = _top_pick(card)
    if top is None:
        return ("__unresolved__", None)
    ref = card.get("ref") or {}
    ref_char = ref.get("char")
    if ref_char and ref_char != top:
        return (top, ref_char)
    return (top, None)


def _tile_rank_score(card: dict) -> float:
    """组内排序键，越小排越靠前（"最不像的排最前"，任务书§做什么·1）。

    用 Step5 `glyph_match` 已经算好的 `db.cov`（与库内最近候选的覆盖度）
    当"像不像"的现成信号——没有库命中（`db` 缺失，即 `verdict=diff` 且
    连候选都没有）的格视为最可疑，排最前；有命中的按 `cov` 升序，覆盖度
    越低越可疑。这不是「组内两两图块比对」（那是另开一条图像特征管线的
    活，本轮任务书边界只许动 `console/routers/review.py`），是复用已有
    证据当代理——如果不够准，留给下一轮换成真正的图块聚类。
    """
    db = card.get("db")
    if not db:
        return -1.0
    return float(db.get("cov") or 0.0)


def _agree_rank(card: dict) -> int:
    """两路一致的卡排后（1），不一致／一路缺席／没有 `first` 的排前（0）。"""
    f = card.get("first")
    return 1 if (f is not None and f.get("agree") is True) else 0


def _build_char_groups(cs: list[dict], sample_limit: int, clusterer=None) -> list[dict]:
    """把一批待审卡片摊成按字种分的组：每组 `n`/页码分布/排好序的样例。

    `clusterer`（#166）：给了就把组内样例换成「每簇一张代表图」（见 `_make_clusterer`）。"""
    buckets: dict[tuple, list[dict]] = {}
    for c in cs:
        buckets.setdefault(_group_key(c), []).append(c)
    out = []
    for (top, ref_char), tiles in buckets.items():
        # 借库书：像素与 CNN 两路首位不一致的排组内最前（任务书-C-借库书人审首选改CNN原型 §3）；
        # 没有 `first` 的卡第一键恒为 0，排序与改前相同。
        tiles = sorted(tiles, key=lambda t: (_agree_rank(t), _tile_rank_score(t)))
        pages: dict[int, int] = {}
        for t in tiles:
            pages[t["page"]] = pages.get(t["page"], 0) + 1
        g = {
            "char": None if top == "__unresolved__" else top,
            "ref_char": ref_char,
            "n": len(tiles),
            "pages": [{"page": p, "n": n} for p, n in sorted(pages.items())],
            "tiles": tiles[:sample_limit],
            "truncated": len(tiles) > sample_limit,
        }
        if clusterer is not None:
            g.update(clusterer(tiles, sample_limit))
        out.append(g)
    # 待审格多的字种排前面（用户「高频字优先，自举最快」）；同 n 时按字/对齐字
    # 稳定排序，避免每次请求顺序乱跳（前端翻页体验）。
    out.sort(key=lambda g: (-g["n"], g["char"] or "", g["ref_char"] or ""))
    return out


def cards_by_char(book: str, pages: str, only: str, store,
                  gate_cut: bool, skip_decided: bool, sample_limit: int,
                  cluster: str = "off", cluster_thr: float | None = None,
                  doubt: str = "") -> dict:
    """按字种批审的装配：调既有 `cards()` 拿**全量**待审格（不受 `limit`
    截断——分组要的是真实的 n 与页码分布），再摊成组。`cluster` 见路由 docstring。
    """
    on = _cluster_on(book, cluster)
    emb: dict = {}
    d = cards(book, pages, 10**9, only, store, gate_cut=gate_cut,
             skip_decided=skip_decided, emb_out=emb if on else None, doubt=doubt)
    clusterer = _make_clusterer(book, store, d["cards"], emb, cluster_thr) if on else None
    groups = _build_char_groups(d["cards"], sample_limit, clusterer)
    res = {"book": book, "mode": "char", "n_total": len(d["cards"]),
           "n_decided": d.get("n_decided", 0), "blocked": d.get("blocked", []),
           "groups": groups}
    if on:
        res["cluster"] = _cluster_summary(groups, emb, cluster_thr)
    _copy_doubt_counts(d, res)
    return res


def _copy_doubt_counts(d: dict, res: dict) -> None:
    """`cards(doubt=…)` 给了计数就原样带到分组响应里（overview#215）；没给就什么都不加。"""
    for k in ("doubt_counts", "doubt_total"):
        if k in d:
            res[k] = d[k]



# ── 按形聚类分组（2026-09-27，任务书-C-批审按形聚类分组）───────────────
#
# 背景（Z15 ask 2135）：`group=char` 按「AI 首选字」分组时，形近对（今/令、
# 玉/王、大/天……）若 AI 首选系统性认错方向，两种真实形状会混进同一个字种
# 组，人一屏扫过去分不清该点掉哪些。这里先按形近对表（`clustering/confusables.py`）
# 把互相混淆的字种池化，池内再用 CNN embedding 按形状聚类拆开——同一个「今」
# 首选字池，聚类之后往往能分出「真今」「真令」两簇。
#
# ⚠️ 只读 `clustering/cnn_candidates.py`：不改它的索引格式，也不碰
# `_emb_index`（那是按字表建的字体模板索引，2.7–7 万字冷启动要 5–25 分钟，
# 见 R 冷启动内存那道）——这里只用它的 `embed()`，只对**已有的字块图**过一次
# 网络求 256 维向量，不牵扯字表模板，不会触发那个冷启动。CNN checkpoint 本身
# 不可用（缺 torch/权重）、单池格数太多、或图块算不出来时整池退化成「未聚类」
# 的一簇（`clustered=False`），不报错、不卡控制台（任务书§做什么·3）。

MAX_SHAPE_K = 4
"""一个池最多拆几簇。封顶防止极端链式合并把一个池拆得过碎。"""

MAX_SHAPE_EMBED = 1200
"""单池格数超过这个数就不聚类，整池当一簇（控制台响应时间闸）。按 CPU 上单张
64² 图过一次小网络前向的量级估的、未在生产大池上实测校准，见 done 单。"""

MAX_POOL_LABELS = 6
"""一个池最多含几个不同「首选字」，超了就地解散回各自单字池（见 `_pool_key_map`
「负结果」一节）——不是「拆得碎不碎」的取舍，是防真的语义错误：链式合并会
把毫不相干的字全部拖进同一个池。"""


def _pool_key_map(tops: set[str], pairs: dict | None = None
                 ) -> tuple[dict[str, str], dict[str, set[str]]]:
    """把一批「AI 首选字」按形近对表合并成池：并查集，`pairs` 里成对的字
    （不论隔几跳）先落进同一个池，池太大再就地解散。→ `(首选字 -> 池代表字,
    池代表字 -> 池内含的首选字集合)`。`pairs=None` 时读生产表
    （`confusables.load_pairs()`）。

    ## 负结果（2026-09-27，vol03 5 页真实数据实测）：不能直接用并查集的传递闭包

    最初实现是纯并查集、不设上限，理由是「形近对表理论上能链式合并出一长串
    字，但实测几乎都是两两成对」——**这个假设是错的**。真拿 vol03 p3/6/8/9/20
    过一遍控制台真请求，"之" 池被传递闭包拖进 **137 个不相干的字**（一+丈+下+
    不+中+……+馬），聚出来的"簇"纯度只有 4.3%~45.8%，比不聚类还误导人。

    根子在表本身：`confusable_pairs_v1.tsv` 19,732 条边、4,477 个字，平均出度
    ~8.8——不是「今/令 这种孤立的两两对」，是一张连通度很高的图，个别生僻变体
    字（如 𣕕）度数到 339（多半是同一堆近似字形的生僻扩展字互相全连）。今/令
    （cos=.9606）、玉/王（.9598）、大/天（.9609）三个真目标恰好都在表的判定
    阈值（.945/.955）附近，**没有一个更高的余弦阈值能只留住它们仨又不放行
    高连通度的生僻字网络**——两者的余弦区间是重叠的，卡阈值治不了根。

    真正起作用的是**事后限流**：允许并查集正常传递合并（今/令/大/天这类真实
    两三字小簇需要它），但一个池的标签数超过 `MAX_POOL_LABELS` 就判定为「链
    式合并失控」，就地解散回各自的单字池——退到 `group=char` 的粒度，不比它
    更差（与 `_cluster_pool_by_shape` 的退化哲学一致）。
    """
    if pairs is None:
        pairs = load_pairs()
    parent = {t: t for t in tops}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a in tops:
        for row in pairs.get(a, []):
            b = row[0]
            if b in parent:
                union(a, b)
    pool_of = {t: find(t) for t in tops}
    members: dict[str, set[str]] = {}
    for t, pool in pool_of.items():
        members.setdefault(pool, set()).add(t)

    oversized = [pool for pool, labs in members.items() if len(labs) > MAX_POOL_LABELS]
    for pool in oversized:
        for t in members.pop(pool):
            pool_of[t] = t
            members[t] = {t}
    return pool_of, members


def _majority(items: list) -> tuple:
    """众数与票数；`None` 不计票。空/全 None → `(None, 0)`。"""
    c = Counter(x for x in items if x is not None)
    if not c:
        return None, 0
    ch, n = c.most_common(1)[0]
    return ch, n


def _init_shape_centroids(tiles: list[dict], emb: np.ndarray, labels: set[str], k: int
                          ) -> tuple[np.ndarray, list[str]] | None:
    """给至多 `k` 个标签各选一个种子向量：优先选「AI 首选字＝整理本对齐字＝该
    标签」的格（最可信的锚点），选不到就退回随便一个首选字＝该标签的格。

    → `(种子矩阵, 种子对应的标签，按同一顺序)`——调用方要用这份对应关系把
    「算不出图但知道首选字」的格塞回它自己首选字所在的那一簇，而不是乱塞。
    种子不够 2 个（能提供种子的标签只有 0/1 个）时返回 `None`，调用方退化。
    """
    idx_by_id = {t["id"]: i for i, t in enumerate(tiles)}
    seeds, used = [], []
    for lab in sorted(labels):
        if len(seeds) >= k:
            break
        exemplar = next((t for t in tiles if _top_pick(t) == lab
                         and (t.get("ref") or {}).get("char") == lab), None)
        if exemplar is None:
            exemplar = next((t for t in tiles if _top_pick(t) == lab), None)
        if exemplar is not None:
            seeds.append(emb[idx_by_id[exemplar["id"]]])
            used.append(lab)
    if len(seeds) < 2:
        return None
    return np.stack(seeds), used


def _spherical_kmeans(emb: np.ndarray, centroids: np.ndarray, iters: int = 10) -> np.ndarray:
    """单位向量上的 k-means（用余弦相似度，即质心归一化后的内积）。质心分不到
    格时保留上一轮的值，不让它被拉成 NaN。确定性：种子固定、`argmax` 平手取
    第一个下标，同一批输入每次跑结果一样，方便测试。
    """
    c = centroids / np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-9)
    assign = None
    for _ in range(iters):
        sims = emb @ c.T
        new_assign = np.argmax(sims, axis=1)
        if assign is not None and np.array_equal(new_assign, assign):
            break
        assign = new_assign
        for j in range(c.shape[0]):
            members = emb[assign == j]
            if len(members) == 0:
                continue
            v = members.mean(axis=0)
            n = np.linalg.norm(v)
            if n > 1e-9:
                c[j] = v / n
    return assign


def _label_split(tiles: list[dict]) -> list[dict]:
    """兜底切法：单纯按「AI 首选字」拆——等同 `group=char` 那一刀，不牵扯
    embedding。聚类的任何一步失败都退到这里，而不是把整池糊成一组：形近对
    合并已经让 `group=char` 看不出来的问题露出来了（今/令混在一起），退化
    到「跟 `group=char` 一样烂」都比「比 `group=char` 更烂（多字合一组）」强。
    """
    buckets: dict[str, list[dict]] = {}
    for t in tiles:
        buckets.setdefault(_top_pick(t), []).append(t)
    return [{"tiles": buckets[lab], "clustered": False} for lab in sorted(buckets)]


def _cluster_pool_by_shape(tiles: list[dict], labels: set[str], *, get_patch, embed,
                           max_k: int = MAX_SHAPE_K, max_embed: int = MAX_SHAPE_EMBED
                           ) -> list[dict]:
    """一个池内按形状聚出至多 `max_k` 簇。

    `get_patch(tile) -> 归一化图 | None`、`embed(patches) -> (N,256) 单位向量`
    都是外部传入的可调用——生产由 `cards_by_shape` 拼真的（读字块图 + CNN
    checkpoint），单测传假的，聚类算法本身与 IO/模型解耦，纯函数可测。

    退化条件（→ `_label_split`，按首选字拆，`clustered=False`）：`embed` 为
    `None`（CNN 不可用）、池格数超过 `max_embed`、能算出图的格数不够 2 个标签
    的种子、或质心种不出来。**任何一种都不报错，也不会比 `group=char` 更差**
    ——之前一版实现在这几种情况下把整池糊成一组（今+令混在一起），比
    `group=char` 分开两组还倒退，这里改成退到「按首选字拆」而不是「整池一组」。
    没有形近对合并（`labels` 只有 1 个）时本来就不用拆，直接一组。
    """
    if len(labels) < 2:
        return [{"tiles": list(tiles), "clustered": False}]
    if embed is None or len(tiles) > max_embed:
        return _label_split(tiles)

    k = min(len(labels), max_k)
    ok_tiles, patches = [], []
    for t in tiles:
        img = get_patch(t)
        if img is None:
            continue
        ok_tiles.append(t)
        patches.append(img)
    if len(ok_tiles) < 2:
        return _label_split(tiles)

    emb = embed(patches)
    if emb is None or getattr(emb, "shape", (0,))[0] != len(ok_tiles):
        return _label_split(tiles)

    seeded = _init_shape_centroids(ok_tiles, emb, labels, k)
    if seeded is None:
        return _label_split(tiles)
    centroids, used_labels = seeded
    assign = _spherical_kmeans(emb, centroids)

    n_clusters = centroids.shape[0]
    buckets: list[list[dict]] = [[] for _ in range(n_clusters)]
    sims: list[list[float]] = [[] for _ in range(n_clusters)]
    c_unit = centroids / np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-9)
    for i, t in enumerate(ok_tiles):
        j = int(assign[i])
        buckets[j].append(t)
        sims[j].append(float(emb[i] @ c_unit[j]))

    ok_ids = {t["id"] for t in ok_tiles}
    missing = [t for t in tiles if t["id"] not in ok_ids]
    if missing:
        # 图算不出的格不丢（验收标准「组内格数之和＝待审总数」）：优先塞进它
        # 自己首选字对应的那一簇（种上了种子的话），不瞎塞——不然「令」的一个
        # 缺图格可能被扔进「今」簇，污染那一簇的多数票统计。种不上（这个标签
        # 压根没能当种子）才退回塞最大簇。
        label_to_cluster = {lab: j for j, lab in enumerate(used_labels)}
        for t in missing:
            j = label_to_cluster.get(_top_pick(t))
            if j is None:
                j = max(range(n_clusters), key=lambda x: len(buckets[x]))
            buckets[j].append(t)

    out = []
    for j in range(n_clusters):
        order = sorted(range(len(sims[j])), key=lambda i: sims[j][i])
        ranked = [buckets[j][i] for i in order]
        tail = buckets[j][len(order):]     # missing 塞进来的、没有相似度分数
        out.append({"tiles": ranked + tail, "clustered": True})
    return [cl for cl in out if cl["tiles"]]


def _shape_candidates(pool_tiles: list[dict], suggest_char: str | None, cap: int = 3
                      ) -> list[str]:
    """一个池「另外几个候选」：池内所有格的首选字＋整理本对齐字按票数排序，
    建议字（如果有）排第一，去重封顶 `cap` 个——前端据此给「一键改成别的字」
    的下拉。"""
    votes: Counter = Counter()
    for t in pool_tiles:
        for ch in (_top_pick(t), (t.get("ref") or {}).get("char")):
            if ch:
                votes[ch] += 1
    ordered = [ch for ch, _ in votes.most_common()]
    out: list[str] = []
    if suggest_char is not None:
        out.append(suggest_char)
    for ch in ordered:
        if ch not in out:
            out.append(ch)
    return out[:cap]


def _build_shape_groups(cs: list[dict], sample_limit: int, *, get_patch, embed,
                        clusterer=None) -> list[dict]:
    """把一批待审卡片先按形近对表池化、池内再按形状聚类拆成组——
    `cards_by_shape` 的核心装配，`get_patch`/`embed` 见 `_cluster_pool_by_shape`。
    `clusterer`（#166）同 `_build_char_groups`。
    """
    unresolved = [c for c in cs if _top_pick(c) is None]
    resolved = [c for c in cs if _top_pick(c) is not None]
    tops = {_top_pick(c) for c in resolved}
    pool_of, members = _pool_key_map(tops)
    pools: dict[str, list[dict]] = {}
    for c in resolved:
        pools.setdefault(pool_of[_top_pick(c)], []).append(c)

    out = []
    for pool_rep, tiles in pools.items():
        labels = members[pool_rep]
        pool_label = "+".join(sorted(labels))
        clusters = _cluster_pool_by_shape(tiles, labels, get_patch=get_patch, embed=embed)
        for cl in clusters:
            tiles_c = cl["tiles"]
            ai_char, ai_n = _majority([_top_pick(t) for t in tiles_c])
            ref_char, ref_n = _majority([(t.get("ref") or {}).get("char") for t in tiles_c])
            if ref_char is not None:
                char, n_maj = ref_char, ref_n
            else:
                char, n_maj = ai_char, ai_n
            n = len(tiles_c)
            pages: dict[int, int] = {}
            for t in tiles_c:
                pages[t["page"]] = pages.get(t["page"], 0) + 1
            g = {
                "pool": pool_label,
                "char": char,
                "candidates": _shape_candidates(tiles, char),
                "ai_majority": {"char": ai_char, "n": ai_n} if ai_char is not None else None,
                "ref_majority": {"char": ref_char, "n": ref_n} if ref_char is not None else None,
                "purity": round(n_maj / n, 4) if n else 0.0,
                "clustered": cl["clustered"],
                "n": n,
                "pages": [{"page": p, "n": v} for p, v in sorted(pages.items())],
                "tiles": tiles_c[:sample_limit],
                "truncated": len(tiles_c) > sample_limit,
            }
            if clusterer is not None:
                g.update(clusterer(tiles_c, sample_limit))
            out.append(g)
    if unresolved:
        pages = {}
        for t in unresolved:
            pages[t["page"]] = pages.get(t["page"], 0) + 1
        g = {
            "pool": "__unresolved__", "char": None, "candidates": [],
            "ai_majority": None, "ref_majority": None, "purity": 0.0,
            "clustered": False, "n": len(unresolved),
            "pages": [{"page": p, "n": v} for p, v in sorted(pages.items())],
            "tiles": unresolved[:sample_limit], "truncated": len(unresolved) > sample_limit,
        }
        if clusterer is not None:
            g.update(clusterer(unresolved, sample_limit))
        out.append(g)
    # 大池优先（用户「高频字优先」，同 `_build_char_groups`）；同 n 时按池/字稳定排序。
    out.sort(key=lambda g: (-g["n"], g["pool"], g["char"] or ""))
    return out


def _card_norm_patch(book: str, ctx: RunContext, card: dict):
    """卡片 → 归一化 64² 图（`embed()` 要的输入），算不出来时 `None`。

    `key` 与 `review/cards.py` 拼 `patch` URL 用的是同一个 `cell_key(...)+sub`
    （同一份坐标 → 同一张缓存图，不能各拼各的）；`ctx.materialize` 没有缓存时
    会从原图现算（子会话须知 §〇·1：云端能看字块图）。
    """
    from ...clustering.normalize import normalize_patch

    key = cell_key(card["page"], card["col"], card["slot"]) + (card.get("sub") or "")
    try:
        path = ctx.materialize("char_patch", key)
    except Exception:   # noqa: BLE001 — 算不出来当缺图，不炸整个批审请求
        return None
    img = cv_imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    return normalize_patch(img)


def cards_by_shape(book: str, pages: str, only: str, store,
                   gate_cut: bool, skip_decided: bool, sample_limit: int,
                   cluster: str = "off", cluster_thr: float | None = None,
                   doubt: str = "") -> dict:
    """按形聚类分组的装配：调既有 `cards()` 拿全量待审格，池化＋聚类后摊成组。

    `get_patch`/`embed` 在这里拼真的（`RunContext.materialize` 读字块图、CNN
    单例 `embed()` 求向量），聚类算法本身（`_build_shape_groups` 及其调用链）
    不碰 IO/模型，全靠参数传入，纯函数可单独测。

    `cluster` 开着时（#166）：池内 k-means 直接复用算首选时已有的 embedding（按卡片 id
    查表，不再读图过网络），拆好的每组里再按形聚小簇、每簇一张代表图。
    """
    on = _cluster_on(book, cluster)
    emb: dict = {}
    d = cards(book, pages, 10**9, only, store, gate_cut=gate_cut,
             skip_decided=skip_decided, emb_out=emb if on else None, doubt=doubt)
    cnn = cnn_candidates.shared()
    embed = None
    ctx = None
    clusterer = None
    if on:
        clusterer = _make_clusterer(book, store, d["cards"], emb, cluster_thr)
    if on and emb:
        def get_patch(card: dict):
            return card["id"] if card["id"] in emb else None

        def embed(ids):
            return np.stack([emb[i] for i in ids])
    else:
        if cnn.available:
            ctx = RunContext(load_book(book), store, deps.image_cache(), log=lambda s: None)
            embed = cnn.embed

        def get_patch(card: dict):
            return _card_norm_patch(book, ctx, card) if ctx is not None else None

    groups = _build_shape_groups(d["cards"], sample_limit, get_patch=get_patch, embed=embed,
                                 clusterer=clusterer)
    hint = (None if cnn.available else
           "CNN checkpoint 不可用（缺 torch 或 models/glyph_cnn_r5/best.pt），"
           "形近对没法按形状拆开——已按字种分组（等同 group=char），先把这个跑起来："
           "uv pip install torch --index-url https://download.pytorch.org/whl/cpu")
    res = {"book": book, "mode": "shape", "cluster_ready": cnn.available, "hint": hint,
           "n_total": len(d["cards"]), "n_decided": d.get("n_decided", 0),
           "blocked": d.get("blocked", []), "groups": groups}
    if on:
        res["cluster"] = _cluster_summary(groups, emb, cluster_thr)
    _copy_doubt_counts(d, res)
    return res


# ── 组内按形聚簇、每簇一张代表图（overview #166，2026-09-28）─────────────
#
# 算法与阈值标定在 `review_cluster.py`。这里只做装配：决定开不开、embedding 从哪来、
# 把一组的样例换成代表图。


def _cluster_on(book: str, cluster: str) -> bool:
    """`auto` = 书 yaml 设了 `params.review.first_pick` 才开（#166：聚类开关缺省只对
    借库书打开，四庫、北行等审卡数据与改前逐字节一致）。"""
    if cluster == "on":
        return True
    if cluster == "off":
        return False
    return first_pick_mode(load_book(book)) is not None


def _cluster_key(card: dict):
    """并簇必须一致的键：首选字 + 人裁字（卡片带 `human` 时）。键不同的两格永远不同簇
    ——#166「簇内有任意一格人裁或首选与代表图不一致的，不合进该簇」。"""
    return (_top_pick(card), card.get("human"))


def _make_clusterer(book: str, store, all_cards: list[dict], emb: dict,
                    thr: float | None):
    """→ `clusterer(tiles, sample_limit) -> dict`（并进组 dict 的几个键）。

    `emb` 是 `cards(emb_out=…)` 顺手填好的（借库书算首选时已有）；缺的卡（强制 `on`
    的非借库书、或首选那一路没跑出向量）在这里补算一次，补不出的格各自单成一簇。
    """
    missing = [c for c in all_cards if c["id"] not in emb]
    if missing:
        cnn = cnn_candidates.shared()
        if cnn.available:
            ctx = RunContext(load_book(book), store, deps.image_cache(), log=lambda s: None)
            pats = [(c["id"], _card_norm_patch(book, ctx, c)) for c in missing]
            pats = [(i, p) for i, p in pats if p is not None]
            for s in range(0, len(pats), 256):
                part = pats[s:s + 256]
                for (i, _), v in zip(part, cnn.embed([p for _, p in part])):
                    emb[i] = np.asarray(v, np.float32)
    t = CLUSTER_THR if thr is None else float(thr)

    def clusterer(tiles: list[dict], sample_limit: int) -> dict:
        cls = cluster_tiles(tiles, lambda c: emb.get(c["id"]), _cluster_key, t)
        shown = cls[:sample_limit]
        return {"tiles": [c["rep"] for c in shown],
                "clusters": [{"id": c["id"], "n": c["n"], "members": c["members"]}
                             for c in shown],
                "n_clusters": len(cls),
                "truncated": len(cls) > sample_limit}
    return clusterer


def _cluster_summary(groups: list[dict], emb: dict, thr: float | None) -> dict:
    """响应顶层的聚簇摘要：门槛、屏上要画几张图、覆盖多少格（只在聚簇开着时出现）。"""
    return {"thr": CLUSTER_THR if thr is None else float(thr),
            "n_groups": len(groups),
            "n_clusters": sum(g.get("n_clusters", 0) for g in groups),
            "n_cells": sum(g["n"] for g in groups),
            "n_with_emb": len(emb)}


def _page_maps(st, book: str, page: int, cache: dict):
    """一页四路产物 + 按 id 建好的查找表，供列/跨列上下文共用。

    `cache` 由调用方（单条或批量端点）持有生命周期——**批量请求里同一页会被
    相邻好几个待审位重复问到**，21 格一列，不缓存就是同一页读 21 次产物。
    """
    key = (book, page)
    if key not in cache:
        d = st.read(book, "context_decide", page_key(page), "context_decision")
        m = st.read(book, "glyph_match", page_key(page), "glyph_match")
        o = st.read(book, "ocr_candidates", page_key(page), "ocr_candidates")
        a = st.read(book, "seed_admit", page_key(page), "seed_admit")
        dm = {r.id: r for cc in (d.columns if d else []) for r in cc.chars}
        om = {r.id: r for cc in (o.columns if o else []) for r in cc.chars}
        am = {r.id: r for cc in (a.columns if a else []) for r in cc.chars}
        # 整理本对位（#247）：上下文默认显示整理本原文，对不上的格才退回定字链
        refm, coord = _align_ref_maps(st, book, page)
        cache[key] = (d, m, o, a, dm, om, am, refm, coord)
    return cache[key]


def _column_slots(st, book: str, page: int, col: int, cache: dict) -> list[dict] | None:
    """一列的定字串：见 `api_review_column` 说明——逐级兜底、标出待审位。

    每格两套字（#247）：`char`/`source` = 刻本这边的读法（定字 → 库 → OCR，改前就有）；
    `ref` = 整理本在这一格对位的字（`align_ref` 现役对位，没有再看坐标对位 `coord`），
    `text` = 显示用的字——**有整理本字就用它**，对不上的格才退回 `char`，`text_src`
    标出取自哪（`ref`/`coord`/原 `source`）。读序按 `sort_by_reading`（夹注 a/b 各成一行），
    无夹注的列与原来的 (slot, sub) 排序完全相同。
    """
    from ...utils.jiazhu_order import sort_by_reading
    d, m, o, a, dm, om, am, refm, coord = _page_maps(st, book, page, cache)
    if d is None and m is None:
        return None
    src_col = (m.column(col) if m else None) or (d.column(col) if d else None)
    if src_col is None:
        return None
    out = []
    for r in sort_by_reading(src_col.chars):
        dd, oo, aa = dm.get(r.id), om.get(r.id), am.get(r.id)
        ch, src = None, ""
        if dd is not None and dd.char:
            ch, src = dd.char, (dd.source or "context")
        elif getattr(r, "candidates", None):
            ch, src = r.candidates[0][0], "db"
        elif oo is not None and oo.topk:
            ch, src = oo.topk[0][0], "ocr"
        rf = refm.get(r.id)
        ref, rsrc = (rf[0], "ref") if rf else ((coord[r.id], "coord") if r.id in coord else (None, ""))
        out.append({"slot": r.slot, "sub": r.sub, "id": r.id, "page": page, "col": col,
                    "char": ch, "source": src,
                    "ref": ref, "text": ref or ch, "text_src": rsrc or src,
                    # 待审 = seed_admit 没放行；前端据此高亮
                    "review": bool(aa is not None and not aa.admit)})
    return out


def _max_col(st, book: str, page: int, cache: dict) -> int | None:
    """这一页最后一列的列号（右→左、从 1）——跨列取上下文要知道页边界在哪。"""
    d, m, *_ = _page_maps(st, book, page, cache)
    cols = [cc.col for src in (m, d) if src for cc in src.columns]
    return max(cols) if cols else None


def _around(st, book: str, page: int, col: int, slot: int,
           before: int, after: int, cache: dict, sub: str | None = None) -> dict:
    """跨列/跨页拼够前后各 N 个字——单条与批量端点共用这一份装配。

    本位所在列本身可能就有一大截「本位前」「本位后」的字（21 格一列，本位
    常常不挨着列边）——本列内够的部分先切出来，缺口才向邻列/邻页去补，
    不是「本列整段 + 邻列整段」地拼，否则本位前后各留 1 个能拼出 4 个字。
    """
    cur = _column_slots(st, book, page, col, cache)
    if cur is None:
        return {"text": "", "slots": [], "at": -1}
    # 带 sub（夹注 a/b）就按 (slot, sub) 精确找本位；不带时照旧取这一格的第一条
    idx = None
    if sub:
        idx = next((k for k, r in enumerate(cur) if r["slot"] == slot and (r["sub"] or "") == sub), None)
    if idx is None:
        idx = next((k for k, r in enumerate(cur) if r["slot"] == slot), None)
    if idx is None:
        return {"text": "", "slots": [], "at": -1}

    def _prev_col(pg: int, cl: int) -> tuple[int, int] | None:
        if cl > 1:
            return pg, cl - 1
        pg2 = pg - 1
        if pg2 < 1:
            return None
        mc = _max_col(st, book, pg2, cache)
        return (pg2, mc) if mc else None

    def _next_col(pg: int, cl: int) -> tuple[int, int]:
        mc = _max_col(st, book, pg, cache)
        if mc and cl < mc:
            return pg, cl + 1
        return pg + 1, 1

    before_slots: list[dict] = cur[:idx]
    pg, cl = page, col
    while len(before_slots) < before:
        nxt = _prev_col(pg, cl)
        if nxt is None:
            break
        pg, cl = nxt
        chunk = _column_slots(st, book, pg, cl, cache)
        if not chunk:
            break
        before_slots = chunk + before_slots

    after_slots: list[dict] = cur[idx + 1:]
    pg, cl = page, col
    while len(after_slots) < after:
        pg, cl = _next_col(pg, cl)
        chunk = _column_slots(st, book, pg, cl, cache)
        if not chunk:
            break
        after_slots += chunk

    slots = before_slots[-before:] + [cur[idx]] + after_slots[:after]
    at = len(before_slots[-before:])
    # `text` 是刻本读法串（改前的口径，别的调用方在用）；`ref_text` 是整理本优先的串（#247）
    return {"text": "".join(x["char"] or "□" for x in slots), "slots": slots, "at": at,
            "ref_text": "".join(x["text"] or "□" for x in slots)}


@router.get("/api/review/column/{book}/{page}/{col}")
def api_review_column(book: str, page: int, col: int) -> dict:
    """一列的上下文：定字串 + 每格的 slot，供审查页显示「这个字在哪句话里」。

    单看一个裁紧图块判不出形近字——`confusable-context` 154 题实测，字形层
    top-1 只有 64.3%，而 n-gram 95.5%、大模型 98.7%。人也一样需要上下文。

    ## 空位要用库/OCR 兜底填上（2026-09-04 改）

    原先只印 Step6 的定字，弃权位一律「□」。可**待审的位恰恰全是弃权位**
    ——人看到的就是一串「□□□」，等于没有上下文，读文定字也就无从谈起。
    现在逐级兜底：定字 → 库 top1 → OCR top1，并逐位标出它是不是待审、
    以及字从哪来，前端据此把待审位高亮、把兜底字标灰。

    ⚠️ 只看「这一列」——字在列头/列尾时前/后没东西可看。要跨列/跨页凑够前
    后各 N 个字，用 `/api/review/around` 或批量版 `/api/review/around/batch`。
    """
    out = _column_slots(deps.product_store(), book, page, col, {})
    if out is None:
        return {"text": "", "slots": []}
    return {"text": "".join(x["char"] or "□" for x in out), "slots": out}



@router.get("/api/review/around/{book}/{page}/{col}/{slot}")
def api_review_around(book: str, page: int, col: int, slot: int,
                      before: int = 10, after: int = 10) -> dict:
    """跨列/跨页拼够前后各 N 个字的上下文——不再局限于「这一列」。

    用户 2026-09-09：「显示文字上下文的时候，现在是显示这一列，那么文字在
    第一个或最后一个字时，就看不到上下文，应该动态地加载前十个字和后十个
    字，不论是否在一行。」列内不够时，往前一列/前一页最后一列补，往后一列
    /下一页第一列补——col **右→左递增**、页内 col 到头了才翻页（沿用
    `column_windows` 「col: 右→左，从 1」的既有约定）。

    单条查询留着给调试/CLI 用；审查页一页几十上百张卡都要上下文，走下面
    批量版——不然一页 21 格一列，等于把同一页的产物重读几十遍。
    """
    return _around(deps.product_store(), book, page, col, slot, before, after, {})


class AroundBatchIn(BaseModel):
    book: str
    before: int = 10
    after: int = 10
    # 每项 {page, col, slot[, sub]}；不用 "p:c:s" 字符串键——slot 可能带 sub（"3a"),
    # 用字符串拼接容易在多处 split 逻辑里出岔子，结构化更省心。
    # 带了非空 sub 的项，返回键是 "p:c:s<sub>"（夹注 a/b 两格各自一份上下文）；不带照旧 "p:c:s"。
    items: list[dict]


@router.post("/api/review/around/batch")
def api_review_around_batch(req: AroundBatchIn) -> dict:
    """批量版：一页产物只读一次（`cache` 在整个请求里共用），装一批卡的上下文。

    单条版按待审卡数逐个请求，一批 400 张卡等于 400 次 HTTP + 重复读同一页
    产物 ~20 次（一列 ~21 格）——candidate 查询卡顿的教训（2026-09-07）
    在这里会重演，所以跟 `/api/rare/batch` 一样直接给批量接口。
    """
    st = deps.product_store()
    cache: dict = {}
    out = {}
    for it in req.items:
        pg, cl, sl = int(it["page"]), int(it["col"]), int(it["slot"])
        sub = str(it.get("sub") or "")
        out[f"{pg}:{cl}:{sl}{sub}"] = _around(st, req.book, pg, cl, sl, req.before, req.after,
                                              cache, sub or None)
    return {"around": out}



@router.get("/api/review/context-img/{book}/{page}/{col}/{slot}.png")
@maps_http
def api_review_context_img(book: str, page: int, col: int, slot: int, around: int = 2) -> Response:
    """裁切前的列图，围绕这一格上下各留 `around` 格：看「切分/收框前长什么样」。

    用户 2026-09-09：「点一下看到上下多两个字的位置的图片，我想看到切分前
    的图片的样子，防止切分和缩框等等改变了图片。」`char_patch`（审查卡片贴
    的那张）是 Step4 紧框收缩之后的图，缩框本身可能就是噪声/误判的来源，
    拿它自证看不出问题。这里改用 Step2 的 `column_image`（矫正+去噪，但
    **没有**逐字切分/紧框收缩）配 `char_index` 的 `bbox_col`，只在列图坐标
    上取一段——同一坐标系（`COLUMN_PX`），不用换算。

    ⚠️ `column_image` 是**缓存**、不是常驻产物——`ImageCache.get()` 缓存没命中
    就返回 `None`，跟 `char_patch` 一样得走 `RunContext.materialize()` 现算
    （2026-09-09 实测：vol02 页 3 那张点开「看原图」是空图标，缓存早没了，
    `/api/cache/...` 走的正是这条路才没坏）。
    """
    st = deps.product_store()
    ci = st.read(book, "cell_shrink", page_key(page), "char_index")
    cc = ci.column(col) if ci else None
    if cc is None:
        raise ImageMissing("没有这一列的字框")
    rows = sorted(cc.chars, key=lambda r: r.slot)
    idx = next((k for k, r in enumerate(rows) if r.slot == slot), None)
    if idx is None:
        raise ImageMissing("没有这一格的字框")
    lo, hi = max(0, idx - around), min(len(rows), idx + around + 1)
    ys = [r.bbox_col[1] for r in rows[lo:hi]] + [r.bbox_col[3] for r in rows[lo:hi]]
    pad = 8
    y0, y1 = int(min(ys)) - pad, int(max(ys)) + pad
    ctx = RunContext(load_book(book), st, deps.image_cache(), log=lambda s: None)
    try:
        path = ctx.materialize("column_image", column_key(page, col))
    except Exception as e:   # noqa: BLE001
        raise ImageMissing(f"列图算不出来: {e}") from e
    img = cv_imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ImageMissing("列图读不出来")
    h = img.shape[0]
    y0 = max(0, min(h - 1, y0)); y1 = max(y0 + 1, min(h, y1))
    ok, buf = cv2.imencode(".png", img[y0:y1])
    if not ok:
        raise EncodeFailed("编码失败")
    return Response(content=buf.tobytes(), media_type="image/png")



# ── Step4 随机层裁决（overview 2026-09-11 下发：01-补随机层金标.md）───
#
# Step4 现在报 R4 = 0.51%，但没有人工核校的独立基准说这个数对不对。
# `self_assess_r1~r4` 虽然也叫 rand，但 label_origin 全是 model（算法自评），
# 不能当验收基准。这一组接口出等概率随机抽样的候选，裁决走既有的
# POST /api/events（kind=confirm, payload.v=seg_defect），落
# char-segmentation/instances，stratum=rand_human 与既有各层分开算。


@router.get("/api/cell-shrink-rand/sample")
def api_cell_shrink_rand_sample(n: int = 400, seed: int = 20260911, tag: str = "r1") -> dict:
    return rand_sample(n=n, seed=seed, tag=tag, store=deps.product_store())


@router.get("/api/cell-shrink-rand/context/{book}/{page}/{col}/{slot}.png")
@maps_http
def api_cell_shrink_rand_context(book: str, page: int, col: int, slot: int,
                                 pad: int = 28, scale: float = 1.0) -> Response:
    """原图裁一块，供随机层裁决台的语境图用：**红框=Step4 紧裁框**，
    **蓝线=Step3 实际折线切缝**（`row_segment` 的 `seam_top`/`seam_bottom`，
    逐列映射回原图，不是矩形近似）。

    2026-09-12 教训：最初这里画的是 `quad_page`（矩形外接框），把真实的
    折线抹平成了直线——`vol02:135:3:5`「其」字八字底右边一撇被切掉，
    原以为是 Step4 `_assign_column` 判错了方向，实际是 **Step3 的折线本身
    在这里贴着撇画左侧凹陷抄近道，把整撇划给了下一格**；矩形框看不出
    折线会拐弯，把这条线索盖住了。折线用 `ColumnMapper`（与 `row_segment.py`
    产出 `quad_page` 时同一套映射，重建自 `column_windows` 的窗口参数）
    逐点映射，不能直接拿 `quad_page` 的四个角点连线。

    Step3 没有这一格的产物、或没有 `column_windows`（切分失败/尚未跑）时
    静默跳过蓝线，不报错——语境图仍然可看，只是少一条参考线。

    `bbox_page` 是 raw_page_px@top-right（右上原点、x 向左），cv2 读的图是
    左上原点、x 向右——换算与 `render/overlay.py::overlay` 的 cell_shrink
    分支一致（`x_tr_to_tl`，左右两边各自转换后互换）。
    """
    ci = deps.product_store().read(book, "cell_shrink", page_key(page), "char_index")
    cc = ci.column(col) if ci else None
    if cc is None:
        raise ImageMissing("没有这一列的字框")
    ch = next((r for r in cc.chars if r.slot == slot), None)
    if ch is None or ch.bbox_page is None:
        raise ImageMissing("没有这一格的字框")
    b = load_book(book)
    p = effective_raw_path(b, page)
    if not p.exists():
        raise ImageMissing("原图缺失")
    img = cv_imread(str(p), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ImageMissing("原图读不出来")
    h, w = img.shape
    bx0, by0, bx1, by1 = ch.bbox_page
    x0, x1 = x_tr_to_tl(bx1, w), x_tr_to_tl(bx0, w)
    x0, y0, x1, y1 = int(round(x0)), int(round(by0)), int(round(x1)), int(round(by1))

    seam_lines = _step3_seam_lines(deps.product_store(), book, page, col, slot)

    all_x = [x0, x1] + [px for line in seam_lines for px, _ in line]
    all_y = [y0, y1] + [py for line in seam_lines for _, py in line]
    cx0, cy0 = max(0, min(all_x) - pad), max(0, min(all_y) - pad)
    cx1, cy1 = min(w, max(all_x) + pad), min(h, max(all_y) + pad)
    if cx1 <= cx0 or cy1 <= cy0:
        raise ImageMissing("裁切区域超出原图范围")
    c = cv2.cvtColor(img[cy0:cy1, cx0:cx1], cv2.COLOR_GRAY2BGR)
    for line in seam_lines:
        import numpy as np
        pts = np.array([(px - cx0, py - cy0) for px, py in line], dtype=np.int32)
        cv2.polylines(c, [pts], False, (255, 120, 0), 1)
    cv2.rectangle(c, (x0 - cx0, y0 - cy0), (x1 - cx0 - 1, y1 - cy0 - 1), (0, 0, 255), 1)
    if scale != 1.0:
        c = cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", c)
    if not ok:
        raise EncodeFailed("编码失败")
    return Response(content=buf.tobytes(), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


def _step3_seam_lines(store, book: str, page: int, col: int, slot: int
                      ) -> list[list[tuple[int, int]]]:
    """这一格上下两条切缝，映射回原图（左上原点）的折线点列。

    `seam_top`/`seam_bottom` 是列图局部坐标（逐 x 一个 y，x 从
    `content_x[0]` 起）；没有这条切缝（列首/列尾贴版框）时该侧为 `None`，
    静默跳过，不补一条假线。
    """
    step3 = store.read(book, "row_segment", page_key(page), "cells")
    col3 = step3.column(col) if step3 else None
    cell3 = next((r for r in (col3.cells if col3 else []) if r.slot == slot), None)
    if cell3 is None or col3.content_x is None:
        return []
    windows = store.read(book, "column_windows", page_key(page), "column_windows")
    wrec = windows.column(col) if windows else None
    if wrec is None:
        return []
    mapper = ColumnMapper(windows.page_size[0], wrec.left_line.to_vline(),
                          wrec.right_line.to_vline(), wrec.top_y, wrec.bottom_y)
    page_w = windows.page_size[0]
    x0 = col3.content_x[0]
    lines = []
    for seam in (cell3.seam_top, cell3.seam_bottom):
        if not seam:
            continue
        pts = []
        for i, y in enumerate(seam):
            px_tr, py = mapper.to_page_tr(x0 + i, y)
            pts.append((int(round(x_tr_to_tl(px_tr, page_w))), int(round(py))))
        lines.append(pts)
    return lines



# ── 复核队列：同一个格被不同人裁法不一致（2026-09-26，任务书 §做什么·4）───
#
# **只读、只标记与查询**——不改 `feedback/consumers.py` 的写入流程（那是 H 道
# 「人裁单写者」在做跨进程锁的地方，见任务书「不要碰」）。事件日志本来就是
# 追加写：两个校对者对同一个格提交不同裁决，两条事件**都已经**在日志里，
# 不会互相覆盖——会被覆盖的只是下游裁决表里那一条（后到覆盖，见
# `feedback/consumers.py` 头注），这里不动那条路径，只是多扫一遍事件日志，
# 把"两个人对同一个格给出不同答案"这件事挑出来给复核台看。

_IGNORE_PAYLOAD_KEYS = {"t", "client_ts", "dwell_ms"}


def _event_signature(payload: dict) -> str:
    """裁决的「内容」签名，去掉跟裁得对不对无关的计时字段。"""
    filtered = {k: v for k, v in payload.items() if k not in _IGNORE_PAYLOAD_KEYS}
    return json.dumps(filtered, sort_keys=True, ensure_ascii=False, default=str)


@router.get("/api/review/conflicts")
def api_review_conflicts(batch: str | None = None, book: str | None = None) -> list[dict]:
    """同一个格（`step`+`unit`+`kind`+`key`）被不同校对者（`event.reviewer`）
    裁出不同结果——两条都在事件日志里，这里只挑出「不一致」的那些分组供复核。

    `reviewer` 是可选字段（老事件没有，见 `feedback/events.py`），没带这个字段
    的事件（老数据、非控制台直连写入的收割数据）不参与比对。同一人对同一个格
    改判多次，只看他**最后一条**（按 `(batch, seq)` 排序）。
    """
    evs = deps.event_log().read(batch) if batch else list(deps.event_log().iter_all())
    if book:
        evs = [e for e in evs if e.target.book == book]
    groups: dict[tuple, list] = {}
    for e in evs:
        if not e.reviewer:
            continue
        groups.setdefault((e.target.step, e.target.unit, e.kind, e.target.key), []).append(e)
    out = []
    for (step, unit, kind, key), group in groups.items():
        last_by_reviewer = {}
        for e in sorted(group, key=lambda x: x.order):
            last_by_reviewer[e.reviewer] = e
        if len(last_by_reviewer) < 2:
            continue
        sigs = {r: _event_signature(e.payload) for r, e in last_by_reviewer.items()}
        if len(set(sigs.values())) < 2:
            continue
        first = next(iter(last_by_reviewer.values()))
        out.append({
            "step": step, "unit": unit, "kind": kind, "key": key, "book": first.target.book,
            "reviewers": [{"reviewer": r, "event_id": e.id, "ts": e.ts, "payload": e.payload}
                         for r, e in sorted(last_by_reviewer.items())],
        })
    return out
