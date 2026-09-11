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


def rare_patch(book: str, page: int, col: int, slot: int, sub: str = "",
               cache: ImageCache | None = None):
    """字块图；没有就 None。"""
    ck = f"p{page:04d}c{col:02d}s{slot}{sub or ''}"
    path = (cache or ImageCache()).get(book, "char_patch", ck)
    if path is None:
        return None
    return cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)


def _fuse(a, b, cnn_topk, emb_topk, k: int) -> list[dict]:
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

    if cnn_order or emb_order:
        # CNN 可用：不跑 HOG，by_char 直接用 CNN/embedding 自己的分数
        # （命中两边时优先 embedding——它是最强单源，见模块头引用的实测）。
        by_char = {c: ("cnn", p) for c, p in cnn_topk}
        by_char.update({c: ("emb", p) for c, p in emb_topk})
        if cnn_order and emb_order:
            order = rrf(cnn_order, emb_order, k=k, weights=(CNN_WEIGHT, EMB_WEIGHT))
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

    freq = _corpus_freq(DEFAULT_CORPUS)
    return [{
        "char": ch, "score": round(score, 4), "font": font,
        "ids": ids_of(ch),
        "freq": freq.get(ch, 0),
        "cp": f"U+{ord(ch):04X}" if len(ch) == 1 else "",
        "zi": f"https://zi.tools/zi/{ch}",
        **char_hint(ch),
    } for ch, font, score in hits]


def rare_for(img, k: int) -> list[dict]:
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
        cs_big = _rare_charsets()[1]
        cnn_topk = cnn.topk(norm, cs_big, k=max(k, 10))
        emb_topk = cnn.emb_topk(norm, cs_big, k=max(k, 10))
    else:
        cs_small, cs_big = _rare_charsets()
        a = candidates(norm, cs_small, k=max(k, 10))
        b = candidates(norm, cs_big, k=max(k, 10))
    return _fuse(a, b, cnn_topk, emb_topk, k)


def rare_for_batch(imgs: list, k: int) -> list[list[dict]]:
    """`rare_for` 的批量版：一页多个字块图一次性做检索，逐图融合。

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
    if cnn.available:
        cs_big = _rare_charsets()[1]
        a_list = b_list = [[] for _ in norms]
        cnn_list = cnn.topk_batch(norms, cs_big, k=max(k, 10))
        emb_list = cnn.emb_topk_batch(norms, cs_big, k=max(k, 10))
    else:
        cs_small, cs_big = _rare_charsets()
        a_list = candidates_batch(norms, cs_small, k=max(k, 10))
        b_list = candidates_batch(norms, cs_big, k=max(k, 10))
        cnn_list = emb_list = [[] for _ in norms]

    return [_fuse(a, b, cnn_topk, emb_topk, k)
            for a, b, cnn_topk, emb_topk in zip(a_list, b_list, cnn_list, emb_list)]


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
def _rare_charsets() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """两档字表各算一次。元组身份稳定，`font_candidates._index` 的缓存才命中。

    此前每次请求重新拼 `tuple(sorted(big))`，lru_cache 按值哈希本该命中，
    但大表第一次建就是 8 分钟，且进程重启就丢——现在索引本身也落盘了
    （见 font_candidates._index）。
    """
    small = tuple(book_charset(DEFAULT_CORPUS))
    big = set(small)
    try:
        from ..variants import variants_of
        for ch in small:
            big.update(v[0] if isinstance(v, (tuple, list)) else v
                       for v in (variants_of(ch) or ()))
    except Exception:
        pass
    return small, tuple(sorted(big))


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
        out[s] = rare_for(img, k) if img is not None else []
    return {"book": book, "n": len(out), "rare": out}
