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

from open_guji_cv.clustering import font_candidates as fc
from open_guji_cv.clustering.font_candidates import (all_ready, book_charset, candidates,
                                                     candidates_batch, index_ready,
                                                     warm, _font_files, _index,
                                                     _index_key)

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

# ── K19：universe 借矩阵 / warm() 去重（任务书-K-控制台常驻内存，2026-09-28）──
#
# 背景见 `font_candidates.warm()` 与 `_topk_from_sims` 模块头：`_rare_charsets()`
# 的 small⊆big 此前各建各的索引，控制台冷启动实测两份矩阵各 ~495MB 同时常驻。
# 这几条钉住「小表查询借大表矩阵、不再单独建索引」这个行为，不追真书规模。

@pytest.fixture(autouse=True)
def _clear_index_cache():
    """`_index()` 是 `lru_cache`，同一进程内测试之间不清会互相污染——这个文件里
    好几条测试故意用相同/重叠的字集，要确保每条测试测的是它自己真正触发的
    那次建索引，不是上一条测试残留在内存里的结果。"""
    _index.cache_clear()
    yield
    _index.cache_clear()


def test_candidates_with_universe_only_builds_the_universe_index():
    """`charset` 是 `universe` 的子集时，只应该建/命中 `universe` 那份索引——
    `charset` 自己的 key 对应的缓存文件不该出现。"""
    from open_guji_cv.clustering.synth import render_char

    small = ("袤", "衣")
    big = ("袤", "衣", "褻", "矛", "袠")
    q = render_char("袤", _font_files()[0], size=64).astype(np.uint8)

    hits = candidates(q, small, k=5, universe=big)
    assert {h.char for h in hits} <= set(small), f"universe 应该把答案限制在 charset 里：{hits}"

    key_small = _index_key(tuple(small), "fonts", "hog")
    key_big = _index_key(tuple(big), "fonts", "hog")
    assert not (fc._index_dir() / f"{key_small}.npz").exists(), "不该为子集单独建索引文件"
    assert (fc._index_dir() / f"{key_big}.npz").exists(), "universe 那份索引应该已经落盘"


def test_candidates_batch_with_universe_matches_sequential_universe_calls():
    from open_guji_cv.clustering.synth import render_char

    small = ("袤", "衣")
    big = ("袤", "衣", "褻", "矛", "袠", "一", "二")
    fonts = _font_files()
    patches = [render_char(ch, fonts[0], size=64).astype(np.uint8) for ch in ("袤", "衣")]

    seq = [candidates(p, small, k=5, universe=big) for p in patches]
    batch = candidates_batch(patches, small, k=5, universe=big)
    for s, b in zip(seq, batch):
        assert [(h.char, h.font) for h in s] == [(h.char, h.font) for h in b]


def test_candidates_universe_never_returns_chars_outside_charset():
    """即便 `universe` 里排名更高的字不在 `charset` 里，也不能混进结果——
    这是「只在 charset 里选答案」的字面意思，不是「优先 charset、不够再补」。"""
    from open_guji_cv.clustering.synth import render_char

    charset = ("矛",)                      # 明显不是查询字，用来当「窄字表」
    universe = ("矛", "袤", "衣", "褻", "袠")  # 查询字「袤」在这里
    q = render_char("袤", _font_files()[0], size=64).astype(np.uint8)

    hits = candidates(q, charset, k=5, universe=universe)
    assert all(h.char == "矛" for h in hits), f"结果跑出了 charset 之外：{hits}"


def test_warm_skips_charsets_that_are_subsets_of_another():
    """`warm([small, big])`：small⊆big 时只建 big 一份索引文件。"""
    small = ("一", "二")
    big = ("一", "二", "三", "十", "土")
    warm([small, big])

    key_small = _index_key(tuple(small), "fonts", "hog")
    key_big = _index_key(tuple(big), "fonts", "hog")
    assert not (fc._index_dir() / f"{key_small}.npz").exists()
    assert (fc._index_dir() / f"{key_big}.npz").exists()
    assert index_ready(tuple(big))
    assert not index_ready(tuple(small)), (
        "small 从未单独建过索引——查询时全靠调用方传 universe=big 才有答案，"
        "index_ready(small) 如实报告「没有它自己的那份缓存」")


def test_warm_builds_each_charset_when_none_is_a_subset_of_another():
    """互不包含的字表：两份都要建，谁也不能被吞掉。"""
    a = ("一", "二")
    b = ("三", "十")
    warm([a, b])
    assert index_ready(tuple(a))
    assert index_ready(tuple(b))


def test_index_ready_false_before_build_true_after():
    cs = ("一", "二", "三")
    assert not index_ready(cs)
    _index(cs)
    assert index_ready(cs)


def test_all_ready_accounts_for_subset_dedup():
    """`index_ready(small)` 永远是 False（K19 去重后 small 从不单独落盘），
    但 `all_ready([small, big])` 建完 big 之后该是 True——它跟 `warm()` 走
    同一套「被更大字表包含就不用单独建」的判断，不是逐个 `index_ready` 的 AND。
    """
    small = ("一", "二")
    big = ("一", "二", "三", "十")
    assert not all_ready([small, big]), "还没建过，两个都不该判就绪"
    warm([small, big])
    assert not index_ready(small), "small 从没有属于自己的 .npz——这是设计使然"
    assert all_ready([small, big]), "但整批已经就绪：small 的查询借用 big 的矩阵"


def test_all_ready_false_when_any_independent_charset_missing():
    """互不包含时是逐个真查——其中一个没建过，整批就不算就绪。"""
    a = ("一", "二")
    b = ("三", "十")
    warm([a])
    assert not all_ready([a, b]), "b 还没建过"
    warm([a, b])
    assert all_ready([a, b])



# ── font_set_fingerprint 按内容算，不按 mtime（2026-09-28）───────────────
#
# CV 总管 09-27 23:45Z 追加到任务书-R-rare前向去重与测试隔离（K 快照自动导入
# #51 查出）：改前按 `名字:大小:mtime` 拼，字体逐字节相同、只是不同机器
# checkout 的 mtime 不同，key 就跟着变——云端预建的 embedding/HOG 索引到服务器
# 上全部 miss，服务器只能现建（K18 实测冷建近 1 小时，差点 OOM）。与
# `cnn_candidates.fingerprint`/`real_proto_fingerprint`/`gw_catalog_fingerprint`
# 同一个坑、同一个改法，这里钉住同一条规矩：换 mtime 不变，换内容才变。
def test_font_set_fingerprint_survives_mtime_change(tmp_path):
    from open_guji_cv.clustering.font_candidates import (FONT_ORDER,
                                                         font_set_fingerprint)

    root = tmp_path / "fonts"
    d = root / FONT_ORDER[0]
    d.mkdir(parents=True)
    f = d / "a.ttf"
    f.write_bytes(b"hello font bytes" * 50)

    fp1 = font_set_fingerprint(str(root))
    import os
    import time
    time.sleep(0.01)
    os.utime(f, (time.time() + 1000, time.time() + 1000))  # 未来 mtime，模拟换机器 checkout
    fp2 = font_set_fingerprint(str(root))
    assert fp1 == fp2


def test_font_set_fingerprint_changes_with_content(tmp_path):
    from open_guji_cv.clustering.font_candidates import (FONT_ORDER,
                                                         font_set_fingerprint)

    root = tmp_path / "fonts"
    d = root / FONT_ORDER[0]
    d.mkdir(parents=True)
    f = d / "a.ttf"
    f.write_bytes(b"aaaa")
    fp1 = font_set_fingerprint(str(root))
    f.write_bytes(b"bbbb")
    fp2 = font_set_fingerprint(str(root))
    assert fp1 != fp2


def test_font_set_fingerprint_relative_root_matches_absolute():
    """`root` 不管传相对路径（缺省 `"fonts"`）还是绝对路径，只要指向同一份
    仓内字体档，都该按仓根解析出同一个 key——不该跟着 cwd 漂
    （`_font_files` 本身的 cwd-then-repo-root 兼容逻辑是给「找文件」用的，
    指纹计算这里显式钉死走仓根）。"""
    from open_guji_cv.clustering.font_candidates import _REPO_ROOT, font_set_fingerprint

    assert font_set_fingerprint("fonts") == font_set_fingerprint(str(_REPO_ROOT / "fonts"))


def test_font_set_fingerprint_no_fonts_is_nofonts(tmp_path):
    from open_guji_cv.clustering.font_candidates import font_set_fingerprint

    assert font_set_fingerprint(str(tmp_path / "empty")) == "nofonts"

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
