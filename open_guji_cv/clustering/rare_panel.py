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

from .font_candidates import book_charset, candidates
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


def rare_for(img, k: int) -> list[dict]:
    """一张字块图 → top-k 候选（含释义等修饰）。单查与批量共用这一份。"""
    cs_small, cs_big = _rare_charsets()
    norm = normalize_patch(img)
    a = candidates(norm, cs_small, k=max(k, 10))
    b = candidates(norm, cs_big, k=max(k, 10))
    hog_order, seen = [], set()
    for h in list(a[:3]) + list(b) + list(a[3:]):
        if h.char not in seen:
            seen.add(h.char)
            hog_order.append(h.char)
    by_char = {h.char: h for h in list(a) + list(b)}

    # ── 第四源：CNN（scripts/train_glyph_cnn.py），与 HOG 做倒数排名融合 ──
    # unseen 1,327 条实测：HOG 75.5/94.7，CNN 72.4/97.6，**RRF 86.7/98.3**（top1/top10）。
    # 两者看的东西不一样（整体轮廓 vs 部件局部），融合比任一单源 top-1 高 11 个点。
    # 没有 checkpoint 时静默退回 HOG，界面照常。
    from .cnn_candidates import (CNN_WEIGHT, EMB_WEIGHT, HOG_WEIGHT,
                                             rrf, shared)
    cnn = shared()
    cnn_order = [c for c, _ in cnn.topk(norm, cs_big, k=max(k, 10))] if cnn.available else []
    # 第五源：同一网络的 embedding 对字体模板做余弦检索——同网络换读法就高 8 个点
    # （unseen top-1 分类头 83.9 → 检索 91.9），见 cnn_candidates.emb_topk。
    emb_order = [c for c, _ in cnn.emb_topk(norm, cs_big, k=max(k, 10))] if cnn.available else []
    if cnn_order and emb_order:
        order = rrf(hog_order, cnn_order, emb_order, k=k,
                    weights=(HOG_WEIGHT, CNN_WEIGHT, EMB_WEIGHT))
    elif cnn_order:
        order = rrf(hog_order, cnn_order, k=k, weights=(HOG_WEIGHT, CNN_WEIGHT))
    else:
        order = hog_order[:k]
    hits = []
    for ch in order:
        h = by_char.get(ch)
        hits.append(h if h is not None else type("H", (), {"char": ch, "score": 0.0, "font": "cnn"})())
    freq = _corpus_freq(DEFAULT_CORPUS)
    return [{
        "char": h.char, "score": round(h.score, 4), "font": h.font,
        "ids": ids_of(h.char),
        "freq": freq.get(h.char, 0),
        "cp": f"U+{ord(h.char):04X}" if len(h.char) == 1 else "",
        "zi": f"https://zi.tools/zi/{h.char}",
        **char_hint(h.char),
    } for h in hits]


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
