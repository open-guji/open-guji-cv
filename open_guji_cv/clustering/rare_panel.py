# -*- coding: utf-8 -*-
"""生僻字面板的引擎：字表、候选融合、释义、频次。

从 `console/app.py` 搬来（控制台重构 C2）——原先它是被
`POST /api/rare/batch`（路由体 20 行）拖着的 100 行无家可归的领域代码，
`GET /api/rare/{…}`（体 48 行）又拖着候选融合的 57 行。搬出来之后两条路由
都变成薄转发，而这套引擎 CLI 与云端道直接能用（**不需要 GPU**，CNN
checkpoint 走 CPU 前向）。

**算法一行未改**：两档字表的位次合并、HOG＋CNN＋embedding 的 RRF、释义清洗
的那几条正则，连同各自的实测数字与用户裁决日期，全部原样保留。改的只有
函数改公开名、`ImageCache` 可注入、延迟 import 提到模块级，以及
「没有字块」那处由调用方去抛 HTTP（本模块不 import fastapi）。

⚠️ **`lru_cache` 必须跟着搬**（`_gloss` 8 MB 释义表、`_rare_charsets`、
`_corpus_freq`）。丢了它们，CLI 每起一次进程都要重算——方案 §四·4 记的
「生僻字首次 112 秒」就是这么来的。`warm_font_index()` 是为此准备的预热线程：
控制台 `serve()` 启动时起一个，CLI 要连查多张时也该先叫一次。
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import cv2

from .font_candidates import book_charset, candidates, candidates_batch
from .ids_guard import ids_of
from .normalize import normalize_patch
from ..products.cache import ImageCache
from ..steps.align_ref import DEFAULT_CORPUS
from ..utils.image_io import imread as cv_imread, imwrite as cv_imwrite


def rare_patch(book: str, page: int, col: int, slot: int, sub: str = "",
               cache: ImageCache | None = None):
    """字块图；没有就 None。"""
    ck = f"p{page:04d}c{col:02d}s{slot}{sub or ''}"
    path = (cache or ImageCache()).get(book, "char_patch", ck)
    if path is None:
        return None
    return cv_imread(str(path), cv2.IMREAD_GRAYSCALE)


def _book_norm_stroke(book: str | None) -> int | None:
    """这册书的笔宽归一（`font.norm_stroke`）——与 Step5-a 同一把尺子。"""
    if not book:
        return None
    try:
        from ..core.book import load_book
        return (load_book(book).font or {}).get("norm_stroke")
    except Exception:
        return None


def book_font_editions(book: str) -> list[str]:
    """这册书标定选用的字体域（`books/<id>.yaml` 的 `font.editions`）。

    2026-09-15 加。此前生僻字面板的模板候选走 `font_candidates._index`，那是
    **另一套东西**：写死 `fonts/` 目录下的 iming/jigmo/kangxi 三套（刻本链标定的），
    与字形库里的字体域毫无关系。后果是——我们为这本书标定了 I.Ming + SimSun
    并把它们导进了库，面板却在用刻本那三套，**SimSun 根本不在候选源里**。
    查不到就返回空列表，调用方退回原来那条路。
    """
    try:
        from ..core.book import load_book
        eds = (load_book(book).font or {}).get("editions") or []
        return [str(e) for e in eds]
    except Exception:
        return []


def db_font_topk(norm, editions: list[str], k: int, norm_stroke: int | None = None):
    """库里这些字体域 → top-k 候选 [(字, 分)]。

    与 Step5-a 用同一个 `GlyphMatcher`/同一套归一协议（`norm_stroke`），
    所以面板上看到的排序与管线判的是同一把尺子——差一把尺子的教训见
    `modern_print_pipeline.md` §五.4。
    """
    if not editions:
        return []
    from .glyph_db import GlyphDB
    from .seeding import cached_matcher_from_db
    from ..steps.glyph_match import db_fingerprint, _default_db
    path = _default_db()
    out: dict[str, float] = {}
    for ed in editions:
        try:
            m, _ = cached_matcher_from_db(path, db_fingerprint(path), edition=ed,
                                          knn_k=max(k, 10), norm_stroke=norm_stroke)
        except Exception:
            continue
        r = m.match(norm)
        for ch, cov in (r.candidates or []):
            if cov > out.get(ch, 0.0):
                out[ch] = float(cov)
    return sorted(out.items(), key=lambda t: -t[1])[:k]


def _db_topk_batch(norms: list, editions: list[str], k: int, norm_stroke: int | None = None):
    """库字体域的批量检索：**每套字体的 matcher 只建一次**，再逐图查。

    `cached_matcher_from_db` 的缓存只留最近一个 key（见 seeding.py 里的
    `_MATCHER_CACHE.clear()`），所以「逐字位 × 逐字体」地调它，两套字体会
    互相把对方挤出缓存，等于每次都重建索引。这里把循环顺序倒过来：
    外层字体、内层字位。
    """
    if not editions or not norms:
        return [[] for _ in norms]
    from .seeding import cached_matcher_from_db
    from ..steps.glyph_match import _default_db, db_fingerprint
    path = _default_db()
    acc: list[dict] = [{} for _ in norms]
    for ed in editions:
        try:
            m, _ = cached_matcher_from_db(path, db_fingerprint(path), edition=ed,
                                          knn_k=max(k, 10), norm_stroke=norm_stroke)
        except Exception:
            continue
        for i, n in enumerate(norms):
            for ch, cov in (m.match(n).candidates or []):
                if cov > acc[i].get(ch, 0.0):
                    acc[i][ch] = float(cov)
    return [sorted(d.items(), key=lambda t: -t[1])[:k] for d in acc]


def _fuse(a, b, cnn_topk, emb_topk, k: int, db_topk=None) -> list[dict]:
    """HOG（两档字表，`cnn.available` 为 False 时才有）+ CNN 分类 + CNN
    embedding → 融合后的候选字典列表。

    `rare_for`（单查）与 `rare_for_batch`（批量）在拿到各自的 `candidates()`/
    `topk()`/`emb_topk()` 原始结果后，共用这一份融合与释义修饰——融合算法
    本身跟单查/批量无关，一行没变，只是把它从 `rare_for` 里抽出来复用。

    ## 2026-09-10：CNN 可用时不再跑 HOG

    `HOG_WEIGHT=0.0` 已经把 HOG 排出 RRF 排名之外三天了（2026-09-07 起）——
    vol01 全部 12 页 dev_set（1934 字）实测：跑不跑 HOG，最终候选逐字比对
    **零差异**。之前 HOG 还留着算，是因为它同时给 `by_char` 供了展示用的
    `score`/`font` 字段（CNN-only 命中的字之前退化成写死的 `score=0.0`）。
    现在 CNN 命中的字改用 CNN 自己的真实分数（`font` 标 `cnn`/`emb`），
    HOG 的 `candidates()` 调用（两档字表各一次矩阵乘法，是 `rare_for` 全链路
    里最贵的部分，见 `font_candidates.candidates_batch` 模块头）就完全不用
    跑了——`a`/`b` 只在 CNN 不可用时才现算，见 `rare_for`/`rare_for_batch`。
    """
    from .cnn_candidates import CNN_WEIGHT, EMB_WEIGHT, HOG_WEIGHT, rrf
    cnn_order = [c for c, _ in cnn_topk]
    emb_order = [c for c, _ in emb_topk]
    db_order = [c for c, _ in (db_topk or [])]

    if db_order and (cnn_order or emb_order):
        # 三路 RRF：库里这册书标定的字体域 + CNN 分类 + CNN embedding。
        # 字体模板权重取 CNN 那一档（它是**这本书实际印刷字形**的证人，
        # 比通用 CNN 更贴题；但单套字体覆盖有限，不给到 embedding 那么高）。
        by_char = {c: ("cnn", p) for c, p in cnn_topk}
        by_char.update({c: ("emb", p) for c, p in emb_topk})
        by_char.update({c: ("font", p) for c, p in (db_topk or [])})
        # 分类头同样走门控（理由见下面 CNN 两路分支的注释）。库字体域**不门控**：
        # 它是这册书实际印刷字形的证人，字表由 `font.editions` 定，不受 classes 限制。
        from .cnn_candidates import cls_gate_weight, shared_classes
        w_cls = cls_gate_weight(emb_order, shared_classes())
        orders = [o for o in (db_order, cnn_order, emb_order) if o]
        weights = tuple(w for o, w in ((db_order, CNN_WEIGHT), (cnn_order, w_cls),
                                       (emb_order, EMB_WEIGHT)) if o)
        order = rrf(*orders, k=k, weights=weights)
        hits = [(ch, *by_char.get(ch, ("cnn", 0.0))) for ch in order]
    elif db_order and not (cnn_order or emb_order):
        # CNN 不可用（没 checkpoint）：字体域单撑，好过返回空列表
        hits = [(ch, "font", p) for ch, p in (db_topk or [])[:k]]
    elif cnn_order or emb_order:
        # CNN 可用：不跑 HOG，by_char 直接用 CNN/embedding 自己的分数
        # （命中两边时优先 embedding——它是最强单源，见模块头引用的实测）。
        by_char = {c: ("cnn", p) for c, p in cnn_topk}
        by_char.update({c: ("emb", p) for c, p in emb_topk})
        if cnn_order and emb_order:
            # 分类头按「这个字位像不像类外字」动态调权（`cls_gate_weight` 的
            # docstring 有判据与实测表）。类外字它的输出全是错的，恒权会把
            # embedding 的正确答案压下去——314 条类外真刻例实测，
            # emb 单源 top-1 67.8%，两路恒权 RRF 只剩 26.4%。
            from .cnn_candidates import cls_gate_weight, shared_classes
            w_cls = cls_gate_weight(emb_order, shared_classes())
            order = rrf(cnn_order, emb_order, k=k, weights=(w_cls, EMB_WEIGHT))
        else:
            order = (cnn_order or emb_order)[:k]
        hits = [(ch, *by_char.get(ch, ("cnn", 0.0))) for ch in order]
    else:
        # 没有 checkpoint：唯一的候选来源，算法不变（两档字表位次合并）。
        hog_order, seen = [], set()
        for h in list(a[:3]) + list(b) + list(a[3:]):
            if h.char not in seen:
                seen.add(h.char)
                hog_order.append(h.char)
        by_char_hog = {h.char: h for h in list(a) + list(b)}
        order = hog_order[:k]
        hits = [(ch, by_char_hog[ch].font, by_char_hog[ch].score)
                if ch in by_char_hog else (ch, "cnn", 0.0) for ch in order]

    return _decorate(hits)


def struct_hint(ch: str) -> dict:
    """候选的结构解释：{"top": "⿰", "slots": {"L": "言", "R": "俞"}}（`ids_struct` 口径）。
    独体字 top="独体"、slots 空。给审字卡片的解释行用（设计稿 §4.2 Step A 产出 ②）。"""
    from .ids_struct import SINGLE, structure_of
    st = structure_of(ch)
    if st.top == SINGLE:
        return {"top": SINGLE, "slots": {}}
    return {"top": st.top, "slots": {k: "".join(v) for k, v in st.top_slots().items()}}


def _decorate(hits: list[tuple[str, str, float]]) -> list[dict]:
    """(字, 来源, 分) → 面板要的字典：IDS / 结构 / 形近字 / 频次 / 码点 / 释义 / 正字 / 深链。

    `near`（2026-09-22，T6）：`config/ids/confusable_pairs_v1.tsv` 里该字的形近字前 3 个，
    带差在哪个槽（`⿰:R:俞/侖`）——告诉人该盯哪里看，不投票、不放行。"""
    from .confusables import near_forms
    freq = _corpus_freq(DEFAULT_CORPUS)
    return [{
        "char": ch, "score": round(score, 4), "font": font,
        "ids": ids_of(ch),
        "struct": struct_hint(ch),
        "near": near_forms(ch, k=3),
        "freq": freq.get(ch, 0),
        "cp": f"U+{ord(ch):04X}" if len(ch) == 1 else "",
        "zi": f"https://zi.tools/zi/{ch}",
        **char_hint(ch),
    } for ch, font, score in hits]


def ids_fallback(top: str | None = None, slots: dict[str, str] | None = None,
                 components: list[str] | None = None, img=None, k: int = 10,
                 book: str | None = None, corpus: str | None = None,
                 pool: int = 400) -> list[dict]:
    """**候选全错时的兜底**：按结构 + 已认出的部件在 IDS 倒排里取字集，再用 emb 排序。

    `top`（⿰ / ⿱ …）是硬过滤；`slots={"L": "言"}` 与 `components=["俞"]` 每中一条 +1；
    先按命中数取前 `pool` 个，再（有字块图且 CNN 可用时）按 emb 余弦在这个池子里
    排序——**池子由结构定、顺序由形状定**，两者各管一半。没有图就按命中数 + 语料
    频次排。字表不限基集：兜底本来就是为了够到基集外的字，白名单（简体否决）照用。

    只出候选。它是 `rare_char_matching_survey.md` G4 说的 L2，M0 版（2026-09-21）。
    """
    from .ids_struct import shared_index
    idx = shared_index()
    # 先取**全部**命中再排、再截池：只按命中数截会让平局按码点排，欠定查询
    # （只给「含鹿」）时 麓 这种基本区常用字被扩A 的一堆字挤出池子（2026-09-21 测试撞上）。
    hits = idx.search(top=top or None, slots=slots or None,
                      components=components or (), limit=1_000_000)
    if not hits:
        return []
    freq0 = _corpus_freq(corpus or DEFAULT_CORPUS)

    def _block(ch: str) -> int:      # 基本区 < 扩A < 兼容区 < 扩B+：没有频次时的「常用度」代理
        o = ord(ch[0])
        return 0 if 0x4E00 <= o <= 0x9FFF else 1 if 0x3400 <= o <= 0x4DBF \
            else 2 if 0xF900 <= o <= 0xFAFF else 3
    hits = sorted(hits, key=lambda t: (-t[1], -freq0.get(t[0], 0), _block(t[0]), t[0]))[:pool]
    allow = "none"
    keep: frozenset = frozenset()
    try:
        from .charset_spec import filter_candidates, spec_for_book
        allow = spec_for_book(book).get("allow", "none") if book else "no-simplified"
        keep = _corpus_keep(corpus)
    except Exception:
        pass
    chars = [ch for ch, _ in hits]
    score = {ch: float(n) for ch, n in hits}
    if allow != "none":
        chars = [c for c, _ in filter_candidates([(c, score[c]) for c in chars], allow, keep)]

    from .cnn_candidates import shared
    cnn = shared()
    if img is not None and cnn.available and chars:
        from .synth import render_char
        from .font_candidates import _font_files
        fonts = _font_files()
        tmpl, names = [], []
        for ch in chars:
            ims = []
            for fp in fonts:
                try:
                    im = render_char(ch, fp, size=64)
                except Exception:
                    continue
                if im is not None and im.any():
                    ims.append(im.astype("uint8"))
            if ims:
                tmpl.append(ims); names.append(ch)
        if names:
            flat = [im for ims in tmpl for im in ims]
            E = cnn.embed(flat)
            q = cnn.embed([normalize_patch(img)])[0]
            out, i = [], 0
            for ch, ims in zip(names, tmpl):
                v = E[i:i + len(ims)].mean(0); i += len(ims)
                v = v / (float((v ** 2).sum()) ** 0.5 + 1e-9)
                out.append((ch, "ids+emb", float(v @ q) + score[ch]))   # 命中数是整数档，余弦只在档内排
            out.sort(key=lambda t: -t[2])
            return _decorate(out[:k])
    return _decorate([(c, "ids", score[c]) for c in chars[:k]])   # chars 已按 命中→频次→区块 排好


def rare_for(img, k: int, corpus: str | None = None,
             book: str | None = None) -> list[dict]:
    """单查：直接走批量版，保证审阅页与 Step5-b **同一条口径**。

    2026-09-17 起不再单独实现——阶梯与白名单两套逻辑要是各写一遍，
    迟早分叉（面板给一个答案、产物给另一个）。批量版对 1 张图没有额外开销。
    """
    return rare_for_batch([img], k, corpus, book)[0] if img is not None else []


def _rare_for_single_legacy(img, k: int, corpus: str | None = None,
                            book: str | None = None) -> list[dict]:
    """一张字块图 → top-k 候选（含释义等修饰）。单查用这个；一页多个字块
    用 `rare_for_batch`——五路检索改成矩阵-矩阵乘法/网络批前向，快数倍
    （2026-09-10，见 `font_candidates.candidates_batch` 与
    `cnn_candidates.emb_topk_batch` 模块头）。"""
    norm = normalize_patch(img)

    from .cnn_candidates import shared
    cnn = shared()
    # unseen 1,327 条实测：HOG 75.5/94.7，CNN 72.4/97.6，**CNN+embedding RRF
    # 86.7/98.3**（top1/top10）。CNN 可用时 HOG_WEIGHT=0.0 早已让 HOG 出局
    # （见 _fuse 模块头「2026-09-10」一节），这里索性不跑它，省下两档字表
    # 各一次矩阵乘法——checkpoint 缺席才现算 HOG 当唯一候选源。
    a = b = []
    cnn_topk = emb_topk = []
    if cnn.available:
        cs_big = _rare_charsets(corpus)[1]
        cnn_topk = cnn.topk(norm, cs_big, k=max(k, 10))
        emb_topk = cnn.emb_topk(norm, cs_big, k=max(k, 10))
    else:
        cs_small, cs_big = _rare_charsets(corpus)
        a = candidates(norm, cs_small, k=max(k, 10))
        b = candidates(norm, cs_big, k=max(k, 10))
    db_topk = db_font_topk(norm, book_font_editions(book), max(k, 10),
                           _book_norm_stroke(book)) if book else []
    return _fuse(a, b, cnn_topk, emb_topk, k, db_topk)


def rare_for_batch(imgs: list, k: int, corpus: str | None = None,
                   book: str | None = None, struct_rerank: bool = False,
                   struct_probe: str | None = None) -> list[list[dict]]:
    """`rare_for` 的批量版：一页多个字块图一次性做检索，逐图融合。

    `struct_rerank`（2026-09-21，缺省关）：融合后再按部件袋头的一致性重排前 30 名
    （`ids_struct.struct_rerank`）。**效果未量**，量法见 `scripts/eval_struct_rerank.py`；
    量出 oov_bench / 北行 top-1、top-10 不掉之前不要在生产配置里打开。

    ## 2026-09-10：一页一个字一个字查，把这一步拖慢了 10~100 倍

    `RareCandidatesStep.run_page` 原先对页里每个字都单独调一次 `rare_for`，
    而检索里模板矩阵/网络权重整页不变，变的只是查询图——单独查是拿一个
    查询向量对几万行模板矩阵做矩阵-向量乘法（GEMV）、网络也单独前向
    一次，逐字重复地付出「加载/调度」成本。这一版把整页的归一化图一次性
    传给 `candidates_batch`（矩阵-矩阵乘法，GEMM）与
    `topk_batch`/`emb_topk_batch`（网络一次前向吃满 batch）。融合逻辑
    （`_fuse`）与单查完全一致，结果逐字比对为位级相同（同一份归一化、
    同一套索引，只是批处理 IO）。

    ## CNN 可用时不跑 HOG（同一天第二次改）

    `_fuse` 已经改成 CNN 可用时完全不用 HOG 的候选（`HOG_WEIGHT=0.0` 三天了，
    vol01 全量实测零差异，见 `_fuse` 模块头）。批处理版同步：`cnn.available`
    时 `a_list`/`b_list` 传空，省下 `candidates_batch` 那两次大矩阵乘法——
    它是 `rare_for` 全链路里最贵的部分（HOG 6.4×、CNN 2.9×，见旧版基准）。
    checkpoint 缺席时才现算 HOG batch，当唯一候选源，与单查同一条口径。
    """
    if not imgs:
        return []
    norms = [normalize_patch(img) for img in imgs]

    from .cnn_candidates import shared
    cnn = shared()
    spec: dict = {}
    if cnn.available:
        cs_base, cs_esc, spec = book_charsets(book, corpus)
        a_list = b_list = [[] for _ in norms]
        cnn_list = cnn.topk_batch(norms, cs_base, k=max(k, 10))
        emb_list = cnn.emb_topk_batch(norms, cs_base, k=max(k, 10))
        # GlyphWiki 变体形模板赢过字体均值的字位（`cnn_candidates.GW_CATALOG`，T4）：
        # 记下是哪张形赢的，最后挂到候选的 `gw` 字段——告诉人「匹配到的是中华字海的这个异体」。
        gw_prov = [dict(d) for d in cnn.last_gw_prov] or [{} for _ in norms]

        # ── 阶梯：基集 top-1 分数低的字位，**追加**升级档候选（不是替换）──
        #
        # 为什么是追加：扩B 里全是常用字的罕见异写，形状极近**且得分更高**
        # （斲 0.816 → 𣂪 0.831、言 0.818 → 𧥜 0.832），直接并进大表会抢答，
        # 北行实测 top-1 掉 2.1 点。追加则基集首选留在原位，抢答不发生、
        # 救回照样发生。阈值 0.80 实测甜点：升级率 15.7%，top-1 +0.2、top-10 +1.3。
        # 完整阈值扫描与「为什么不能靠分数分开命中/未命中」见 charset_spec 模块头。
        if cs_esc:
            th = spec.get("escalate_threshold", 0.80)
            idx = [i for i, e in enumerate(emb_list)
                   if (not e) or e[0][1] < th]
            if idx:
                sub = cnn.emb_topk_batch([norms[i] for i in idx], cs_esc,
                                         k=max(k, 10))
                for i, d in zip(idx, cnn.last_gw_prov):
                    gw_prov[i].update(d)
                for i, extra in zip(idx, sub):
                    # ⚠️ **按分数归并，不能简单拼接**（2026-09-17 实测）。
                    # 先写的是 `emb_list[i] + extra`，结果阈值扫描从 0.80 到 1.0
                    # 一个点都不涨——RRF 只看**名次**，拼在后面的升级档一律从第
                    # 11 位起，权重 4/(60+10) 打到底，金标明明在升级档的第 2~3 名
                    # （𠊓 𨕖 𠀉 实测都在）也挤不进最终 top-10。
                    # 归并后升级档凭自己的余弦分与基集同台排名，才真的能救回来。
                    merged = list(emb_list[i]) + list(extra)
                    seen: dict[str, float] = {}
                    for ch, sc in merged:
                        if sc > seen.get(ch, -1.0):
                            seen[ch] = sc
                    emb_list[i] = sorted(seen.items(), key=lambda t: -t[1])[:max(k, 10)]
    else:
        cs_small, cs_big = _rare_charsets(corpus)
        a_list = candidates_batch(norms, cs_small, k=max(k, 10))
        b_list = candidates_batch(norms, cs_big, k=max(k, 10))
        cnn_list = emb_list = [[] for _ in norms]
        gw_prov = [{} for _ in norms]

    eds = book_font_editions(book) if book else []
    ns = _book_norm_stroke(book) if book else None
    # matcher 建一次、批量查（`db_font_topk` 每次调用都要 `cached_matcher_from_db`，
    # 缓存只保留最近一个 key，两套字体轮流查会互相把对方挤掉 → 每个字位重建两次
    # 索引，163 个字位跑了一个多小时也没完，2026-09-15 实测）。
    db_list = _db_topk_batch(norms, eds, max(k, 10), ns) if eds else [[]] * len(norms)

    # ── 白名单否决：在 `_fuse` **之前**滤各路输入 ──
    #
    # 必须在融合前滤：`_fuse` 里 RRF 会先截到 k 条，之后再滤就等于白白浪费名额
    # （滤掉 3 个简体，列表就只剩 7 条，而不是让后面的正字递补上来）。
    # `keep` = 本册语料用过的字，无条件放行（判据再准也可能有例外，
    # 而语料是这本书自己的证据）。
    allow = (spec or {}).get("allow", "none")
    if allow != "none":
        from .charset_spec import filter_candidates
        keep = _corpus_keep(corpus)
        f = lambda rows: [filter_candidates(r, allow, keep) for r in rows]  # noqa: E731
        cnn_list, emb_list = f(cnn_list), f(emb_list)
        a_list, b_list, db_list = f(a_list), f(b_list), f(db_list)

    if struct_probe:
        # Step A′ 外挂结构头（2026-09-22）：主干不动，只给重排换一副更细的眼睛
        cnn.attach_probe(struct_probe)
    def _gw(hits: list[dict], prov: dict) -> list[dict]:
        for h in hits:
            p = prov.get(h["char"])
            if p:
                h["gw"] = {"name": p[0], "source": p[1], "cos": round(p[2], 4),
                           "url": f"https://glyphwiki.org/wiki/{p[0]}"}
        return hits

    if not (struct_rerank and cnn.available):
        return [_gw(_fuse(a, b, cnn_topk, emb_topk, k, dbk), pv)
                for a, b, cnn_topk, emb_topk, dbk, pv
                in zip(a_list, b_list, cnn_list, emb_list, db_list, gw_prov)]

    # 重排要看前 30 名，先按 30 融合再截 k；部件概率整页一次前向
    from .ids_guard import components as first_level_components
    from .ids_struct import STRUCT_RERANK_TOP_M, struct_rerank as _rerank
    m = max(k, STRUCT_RERANK_TOP_M)
    fused = [_fuse(a, b, cnn_topk, emb_topk, m, dbk)
             for a, b, cnn_topk, emb_topk, dbk
             in zip(a_list, b_list, cnn_list, emb_list, db_list)]
    # Step A 的槽位头（部件@槽）比部件袋头（只管有没有、不管在哪）更细，有就用它
    if cnn.has_struct_heads:
        from .ids_struct import slot_keys_of
        probs, comps_of = cnn.slot_probs_batch(norms), slot_keys_of
    else:
        probs, comps_of = cnn.comp_probs_batch(norms), first_level_components
    out = []
    for hits, pr, pv in zip(fused, probs, gw_prov):
        by_char = {h["char"]: h for h in hits}
        order = _rerank([h["char"] for h in hits], pr, comps_of, k=k)
        out.append(_gw([by_char[ch] for ch in order], pv))
    return out


def char_hint(ch: str) -> dict:
    """给一个候选字配「常见意思」和「对应哪个繁体正字」。

    用户 2026-09-05：「异体字不用显示 unicode 和 ids，最好可以显示常见意思，
    以及对应哪个繁体整体字。」

    - `gloss`：`config/gloss/gloss.json`（69,835 字，康熙/教育部/维基词典/Unihan 汇编）
      的释义首句 + 拼音。释义可以很长（康熙的整段引证），这里截到一句话。
    - `std`：这个字在**整理本**里对应哪个字。做法不是查"哪个是正字"（异体组里没有
      客观正字），而是**在异体组里找整理本实际用过的那个**——整理本是繁体传承字形，
      它用哪个就是这本书要录的那个。㕔 → 廳、䙝 → 褻 都能对上；候选自己就在整理本里
      用过（freq > 0）时不再重复标。
    """
    out: dict = {}
    g = _gloss().get(ch)
    if g:
        d = (g.get("d") or "").strip()
        # 维基词典那一档偶尔混进 MediaWiki 模板标记（如 __NOTITLECONVERT__），去掉
        d = re.sub(r"__[A-Z]+__|\{\{[^}]*\}\}", "", d).strip()
        # 出处不要（用户 2026-09-07「康熙字典也不需要说明，留空间给正式解释」）：
        # 「【唐韻】【集韻】𠀤徒弄切，音洞。【廣韻】過也。」→ 反切/注音那句整句丢，
        # 「《康熙字典》〈補遺 酉集〉…」这种书名号引注也丢；只留释义正文。
        d = re.sub(r"《[^》]*》〈[^〉]*〉", "", d)
        d = re.sub(r"【[^】]*】", "", d)
        d = re.sub(r"[-]", "", d)          # 康熙条目里的私用区乱码
        sents = [s.strip("，, ") for s in d.split("。") if s.strip("，, ")]
        # 反切/注音不是释义：句首连串的「側氏切阻氏切，」「𠀤徒弄切，音洞，」先剥掉，
        # 剥完只剩反切/「音某」的整句跳过
        sents = [re.sub(r"^(?:[^，,。\s]{1,3}切[，,]?)+(?:音.[，,]?)?", "", s).strip("，, ") for s in sents]
        sents = [s for s in sents if s and not re.search(r"切[，,]?(音.)?$|^音.$", s)]
        if sents:
            # 有地方了就多给几句（「姓。通「倪」。如漢代有兒寬」比只剩「姓」有用），到 40 字为止
            head = "。".join(sents)
            out["gloss"] = (head[:40] + "…") if len(head) > 40 else head
        # 注音不给（用户 2026-09-07「注音不需要」）——留在 title 里悬停看
        if g.get("p"):
            out["py"] = g["p"]
    freq = _corpus_freq(DEFAULT_CORPUS)
    if not freq.get(ch):
        try:
            from ..variants import variants_of
            best, best_n = "", 0
            for v, _src in variants_of(ch):
                n = freq.get(v, 0)
                if n > best_n:
                    best, best_n = v, n
            if best:
                out["std"] = best
                out["std_freq"] = best_n
        except Exception:
            pass
    return out


@lru_cache(maxsize=1)
def _gloss() -> dict:
    """单字速查释义表（`config/gloss/README.md` 列了各源授权）。8 MB，进程内只读一次。"""
    import json
    f = Path(__file__).resolve().parent.parent.parent / "config" / "gloss" / "gloss.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _rare_charsets(corpus: str | None = None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """两档字表各算一次。元组身份稳定，`font_candidates._index` 的缓存才命中。

    此前每次请求重新拼 `tuple(sorted(big))`，lru_cache 按值哈希本该命中，
    但大表第一次建就是 8 分钟，且进程重启就丢——现在索引本身也落盘了
    （见 font_candidates._index）。
    """
    small = tuple(book_charset(corpus or DEFAULT_CORPUS))
    big = set(small)
    try:
        from ..variants import variants_of
        for ch in small:
            big.update(v[0] if isinstance(v, (tuple, list)) else v
                       for v in (variants_of(ch) or ()))
    except Exception:
        pass
    return small, tuple(sorted(big))


@lru_cache(maxsize=4)
def book_charsets(book: str | None, corpus: str | None
                  ) -> tuple[tuple[str, ...], tuple[str, ...], dict]:
    """这册书的 `(基集字表, 升级档字表, 规格)`——**候选字表的唯一入口**（2026-09-17）。

    与旧的 `_rare_charsets`（只吃整理本用字）的区别见
    `charset_spec` 模块头：整理本从「唯一来源」降级成「叠加项」，
    基集改由册配置 `font.charset.base` 决定，缺省按 `edition` 取。

    返回的两个元组**身份稳定**（`lru_cache` + `charset_spec` 内部也各自
    记忆化），下游 `_emb_index` / `font_candidates._index` 的索引缓存才命中——
    每次现拼新元组会让 7 万字的索引反复重建（实测一次 5 分钟）。
    """
    from .charset_spec import build_charsets, spec_for_book
    spec = spec_for_book(book)
    base, esc = build_charsets(
        spec["base"], spec["escalate"], corpus,
        spec["corpus"], spec["variants"], tuple(spec["extra"]))
    return base, esc, spec


@lru_cache(maxsize=4)
def _corpus_keep(corpus: str | None) -> frozenset:
    """本册语料真实用过的字——白名单的无条件放行集（见 `filter_candidates`）。"""
    if not corpus or not Path(corpus).exists():
        return frozenset()
    return frozenset(book_charset(corpus))


def warm_font_index() -> None:
    """后台线程预热字体索引。首次建大表要几分钟，别让第一个点按钮的人等。"""
    try:
        from .font_candidates import warm
        warm(list(_rare_charsets()))
    except Exception:
        pass


@lru_cache(maxsize=2)
def _corpus_freq(path: str) -> dict:
    from collections import Counter
    f = Path(path)
    if not f.exists():
        return {}
    return Counter(ch for ch in f.read_text(encoding="utf-8")
                   if "㐀" <= ch <= "鿿")


def rare_batch(book: str, slots: list[str], k: int = 3,
               cache: ImageCache | None = None) -> dict:
    """**批量版**（2026-09-07）。字表与 CNN 索引只热一次，图块顺序读。

    单查一条 0.35s，审查页要预取几十张，串行等不起、并发 4 条也只是把 7s 压到 2s
    ——瓶颈在每条都要过一遍两次字表检索 ＋ CNN 前向。一页（约 30 个待审位）
    实测从 ~10s 降到 ~2s。缺图的位返回空数组，不报错：批量里一个坏位
    不该让整批失败。
    """
    out: dict[str, list] = {}
    # 字表按这册书的整理本算（`references[0].file`）——写死刻本链那份语料的话，
    # 换一本书就指向一个不存在的文件，整个面板 500（2026-09-15 北行日錄实测）。
    from ..steps.align_ref import book_corpus
    corpus = book_corpus(book)
    for s in slots[:400]:
        try:
            parts = s.split(":")
            page, col, tail = int(parts[0]), int(parts[1]), parts[2]
            sub = tail[-1] if tail[-1:] in ("a", "b") else ""
            slot = int(tail[:-1] if sub else tail)
        except Exception:
            out[s] = []
            continue
        img = rare_patch(book, page, col, slot, sub, cache)
        out[s] = rare_for(img, k, corpus, book) if img is not None else []
    return {"book": book, "n": len(out), "rare": out}
