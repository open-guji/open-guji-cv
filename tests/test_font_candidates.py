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


import numpy as np
import pytest

from open_guji_cv.clustering.font_candidates import (book_charset, candidates,
                                                     candidates_batch, _font_files)

# 用生产代码那个 `_font_files()` 判，不要自己 glob 相对路径（2026-09-17）：
# 它按引擎仓定位、认 .otf（康熙体是 otf），而 `glob("fonts/*/*.ttf")` 靠 cwd、
# 还漏 otf——守卫与被测代码认两套路径，迟早给出不一致的结论。
#
# `fonts/` 是**引擎自带**的字体档（随仓库走、入 git），不是某本书的数据，
# 所以这里依赖它不违反「测试只依赖本仓库」——它不会跟着跑批变。
_FONTS = _font_files()
assert _FONTS, ("fonts/ 下一个字体都没有。字体档随引擎仓走（见 fonts/README.md），"
                "缺了是仓库不完整，不是环境问题——所以这里直接红，不 skip。")


def test_fonts_are_found_in_priority_order():
    """I.Ming（传承字形）排在 Jigmo 前面——刻本用的是旧字形。"""
    files = _font_files()
    assert files, "一个字体都没找到"
    assert "iming" in files[0].lower().replace("\\", "/")


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


def test_candidates_batch_matches_sequential():
    """`candidates_batch` 必须与逐个调用 `candidates` 位级相同（2026-09-10，
    生僻字候选提速：一页多字改成一次矩阵-矩阵乘法，不能悄悄改变排名）。"""
    from open_guji_cv.clustering.synth import render_char
    cs = ["袤", "袠", "褻", "衣", "矛", "一", "二", "三"]
    fonts = _font_files()
    patches = [render_char(ch, fonts[0], size=64).astype(np.uint8)
               for ch in ("袤", "衣", "三")]
    seq = [candidates(p, cs, k=5) for p in patches]
    batch = candidates_batch(patches, cs, k=5)
    for s, b in zip(seq, batch):
        assert [(h.char, h.font) for h in s] == [(h.char, h.font) for h in b]
        # 分数不能要求逐位相同：同一个点积，矩阵-矩阵乘法与逐个向量乘法走的是
        # 不同的 BLAS 路径，累加次序不同就会差一个 ulp（实测 0.509911 vs
        # 0.509912）。要钉的是**排名不变**，不是浮点位相同——`round(x, 6)`
        # 那种写法只是把容差藏进了四舍五入里，边界上照样翻车。
        assert [h.score for h in s] == pytest.approx([h.score for h in b], abs=1e-5)


def test_book_charset_excludes_non_han(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("臣等謹按，卷一。ABC 123", encoding="utf-8")
    cs = book_charset(str(p))
    assert "臣" in cs and "按" in cs
    assert "A" not in cs and "1" not in cs and "，" not in cs

# ── 召回率那两条已迁出测试（2026-09-20）─────────────────────────────────
#
# `test_recall_on_rare_char_set` 与 `test_two_tier_charset_beats_single_table`
# 量的是**字体模板在 rare-char 集上的 top-1 / top-10 召回率**。那是评测，不是
# 测试：它依赖仓外的 `../open-guji-dataset/rare-char/items.jsonl` ＋ 本地跑批
# 才有的 `cache/<book>/char_patch/` 字块图，还依赖完整整理本语料（仓内只有
# 6000 字小样本，字表 ~1100 字种，docstring 里 4636 字种那组数字全部失真）。
# 三样东西缺一就 `skip`，于是云端三条常年一条都没跑。
#
# 同一个量本来就有评测在做，而且比这两条完整（分层报、可出报告）：
#
#     python scripts/eval_rare_char.py --k 10        # 或 guji eval run --only rare_char
#
# 结论数字与「别再走的三条路」留在 `doc/glyph_db_expansion_research.md` §6，
# 不靠测试的 docstring 当档案。这里只留**代码行为**的用例：候选去重排序、
# batch 与逐个调用排名一致、字表构造只收汉字。
