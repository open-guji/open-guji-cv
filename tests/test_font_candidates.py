"""L1 字体模板候选的回归。

**只出候选，永不放行**——`glyph_db_expansion_research.md` §6.2 实测过字体渲染
字形不能当精确判据（对/错 f1 分布重叠，阈值划不出来），那条结论不动。本模块
回答的是另一个问题：库/OCR/上下文三路都给不出答案时，能不能把答案捞进 top-10。

2026-09-04 在 `rare-char` 21 条上实测：

| 分层 | 现状 top-10 | 字体模板 top-10 |
|---|---|---|
| 全部 21 | 33.3% | **76.2%**（并集 85.7%）|
| 真难题 14（三路都没答案）| 0.0% | **78.6%** |
| 稀有但候选里有 7 | 100% | 71.4% |

命中时中位名次 **1**，21 条里 16 条落在 top-3。㕔 和 効 都是名次 1——正是
用户点名「要去字统网查」的那类字。
"""

from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pytest

from open_guji_cv.clustering.font_candidates import (book_charset, candidates,
                                                     _font_files)

FONTS_OK = bool(glob.glob("fonts/*/*.ttf"))
needs_fonts = pytest.mark.skipif(not FONTS_OK, reason="没有字体文件")


@needs_fonts
def test_fonts_are_found_in_priority_order():
    """I.Ming（传承字形）排在 Jigmo 前面——刻本用的是旧字形。"""
    files = _font_files()
    assert files, "一个字体都没找到"
    assert "iming" in files[0].lower().replace("\\", "/")


@needs_fonts
@pytest.mark.parametrize("ch", ["袤", "㕔", "䙝", "効", "槧"])
def test_renders_rare_chars(ch):
    """生僻字必须渲染得出来——这是它相对字形库的全部优势所在。

    库按本书用字频次长，整理本里出现 ≤3 次的 1801 字种有 1551 个一个例都没有；
    字体覆盖 Unihan 十万字，生僻字和常用字一视同仁。
    """
    from open_guji_cv.clustering.synth import render_char
    ok = []
    for f in _font_files():
        try:
            img = render_char(ch, f, size=64)
        except Exception:
            continue
        if img is not None and img.any():
            ok.append(f)
    assert ok, f"{ch} 一套字体都渲染不出来"


@needs_fonts
def test_candidates_are_deduped_and_ranked():
    """同字被多套字体命中只留最高分——候选是给人看的，不该重复。"""
    from open_guji_cv.clustering.synth import render_char
    cs = ["袤", "袠", "褻", "衣", "矛"]
    q = render_char("袤", _font_files()[0], size=64)
    hits = candidates(q.astype(np.uint8), cs, k=5)
    chars = [h.char for h in hits]
    assert len(chars) == len(set(chars)), f"候选里有重复：{chars}"
    assert hits[0].char == "袤", f"自己对自己都没排第一：{chars}"
    assert all(hits[i].score >= hits[i + 1].score for i in range(len(hits) - 1))


def test_book_charset_excludes_non_han(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("臣等謹按，卷一。ABC 123", encoding="utf-8")
    cs = book_charset(str(p))
    assert "臣" in cs and "按" in cs
    assert "A" not in cs and "1" not in cs and "，" not in cs


@needs_fonts
def test_recall_on_rare_char_set():
    """在真集上跑：真难题那档 top-10 召回不该掉到 60% 以下。

    这条是 C 刀的验收线。跑得慢（要建 4600 字 × 4 字体的索引），
    但它是唯一能证明「字体模板对生僻字有用」的用例。
    """
    ds = Path("../open-guji-dataset/rare-char/items.jsonl")
    if not ds.exists():
        pytest.skip("没有 rare-char 集，先跑 scripts/build_rare_char_set.py")
    import json

    import cv2

    from open_guji_cv.clustering.normalize import normalize_patch

    items = [json.loads(l) for l in ds.read_text(encoding="utf-8").splitlines()]
    hard = [i for i in items if not i["expected"]["in_candidates"]]
    assert hard, "集里没有「三路都没答案」的样本，这条用例失去意义"
    cs = book_charset("corpus/zongmu_wuyingdian_reference.txt",
                      [i["expected"]["char"] for i in items])
    hit = 0
    for it in hard:
        p = it["input"]["patch"]
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE) if p else None
        if img is None:
            continue
        got = [h.char for h in candidates(normalize_patch(img), cs, k=10)]
        hit += it["expected"]["char"] in got
    rate = hit / len(hard)
    assert rate >= 0.60, f"真难题 top-10 召回掉到 {rate:.1%}（2026-09-04 实测 78.6%）"


def test_two_tier_charset_beats_single_table():
    """两档字表：小表 top3 占前三、大表补后——top1 与 top10 都要拿到。

    2026-09-04 用户反馈「点生僻字查询准确率不高」，量出来是字表扩张的代价：
    并上异体展开后字表 4636 → 20059，多出的一万五千个罕用形在 HOG 上与正确
    答案难分伯仲，**top-1 从 43% 掉到 29%**。

    | 字表 | top1 | top3 | top10 |
    |---|---|---|---|
    | 小表（整理本 4636 字）| 43% | 71% | 71% |
    | 大表（+异体 20059 字）| 29% | 67% | **76%** |
    | **小表 top3 + 大表** | **43%** | **71%** | **76%** |

    小表名次准但召不全（㕔/䙝 整理本频次 0，压根不在表里）；大表召得全但名次
    被冲垮。位次合并两头都拿到。

    三条无效的路（别再走）：本书频次加权把 top3 从 67% 打到 33%——要找的字
    本来就罕见，频次先验反着起作用；异体身份加权 67% → 62%；相似度闸控扩表
    从不触发，因为小表 top1 分数恒 >0.84，**错的时候也高**。
    """
    ds = Path("../open-guji-dataset/rare-char/items.jsonl")
    if not ds.exists() or not FONTS_OK:
        pytest.skip("没有 rare-char 集或字体")
    import json

    import cv2

    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.variants import variants_of

    items = [json.loads(l) for l in ds.read_text(encoding="utf-8").splitlines()]
    small = tuple(book_charset("corpus/zongmu_wuyingdian_reference.txt"))
    big = set(small)
    for ch in small:
        big.update(v[0] if isinstance(v, (tuple, list)) else v
                   for v in (variants_of(ch) or ()))
    big = tuple(sorted(big))

    t1 = t10 = n = 0
    for it in items:
        p = it["input"]["patch"]
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE) if p else None
        if img is None:
            continue
        norm = normalize_patch(img)
        a = candidates(norm, small, k=10)
        b = candidates(norm, big, k=10)
        out, seen = [], set()
        for h in list(a[:3]) + list(b) + list(a[3:]):
            if h.char not in seen:
                seen.add(h.char)
                out.append(h.char)
        out = out[:10]
        ref = it["expected"]["char"]
        n += 1
        t1 += out[:1] == [ref]
        t10 += ref in out
    assert n
    assert t1 / n >= 0.38, f"top-1 掉到 {t1/n:.0%}（2026-09-04 实测 43%）"
    assert t10 / n >= 0.70, f"top-10 掉到 {t10/n:.0%}（2026-09-04 实测 76%）"
