# -*- coding: utf-8 -*-
"""Step5-d 锚定判据：8-gram 投票 + **相邻偏移合并**。

2026-09-20 重写。原先这个模块把隔壁 `open-guji-dataset` 的
`char-segmentation/align-anchor` 分片逐条读进来当参数化用例，还有一条专门
断言「那个分片里必须有这 8 个 id」。两个问题：

- 分片不在（云端、别人的机器）就整条 skip，等于没测；
- 「分片里必须有哪几条」是**测试集仓的内容**，该由那边守。在这儿写，等于
  一个仓的测试去管另一个仓的数据长什么样。

真实页的回归集留在测试集仓（那正是它该在的地方，跑评测时用）。这里改为
自己合成三种形态，把**判据的机制**钉住——机制是代码的，具体页是数据的：

1. 干净页 → 锚到准确偏移；
2. 页内多处漏字导致偏移累积漂移 → 仍要锚到原偏移（`POOL_RADIUS` 就是为
   这个存在的：一次漏字只把偏移挪 1~2 位，页内多处就会摊成一片相邻偏移，
   不合并的话真锚点的票被切成几堆互相当对手，整页误判失败）；
3. 语料里压根没有这一页 → 如实报失败，不许硬锚。

第 2 条附带验证「合并是必要的」：把半径压到 1（等于不合并）同一页就锚不上。
半径本身的标定数据（vol01/vol02/vol03 全量 337 页回归零退化）记在
`align_eval.POOL_RADIUS` 的注释里，不在这儿重复。
"""

from __future__ import annotations

import random

import pytest

import open_guji_cv.clustering.align_eval as ae
from open_guji_cv.clustering.align_eval import anchor_page_diag, build_ngram_index

#: 合成语料用的字池：取自《四庫全書總目》提要里的常见字，拼出来的串在
#: 8-gram 尺度上基本唯一——这正是真语料的性质（两百卷里 8 字串很少重复）。
POOL = ("臣等謹按是書凡二十卷舊本題宋某撰其文簡質而義精核採進本浙江巡撫"
        "四庫全書總目卷一經部易類論語孟子詩書禮春秋左傳公羊穀梁爾雅孝經")
OFFSET = 1500          # 这一页在语料里的真实起点
PAGE_LEN = 300


@pytest.fixture(scope="module")
def corpus() -> str:
    rng = random.Random(3)
    return "".join(rng.choice(POOL) for _ in range(4000))


@pytest.fixture(scope="module")
def index(corpus):
    return build_ngram_index(corpus)


@pytest.fixture(scope="module")
def page(corpus) -> str:
    return corpus[OFFSET:OFFSET + PAGE_LEN]


def _drop_every(text: str, step: int) -> str:
    """每隔 `step` 个字漏一个——模拟页内多处漏字造成的**累积**漂移。"""
    gone = set(range(step, len(text), step))
    return "".join(ch for i, ch in enumerate(text) if i not in gone)


def test_clean_page_anchors_at_the_exact_offset(index, page):
    d = anchor_page_diag(page, index)
    assert d.anchored, d.reason
    assert d.offset == OFFSET
    assert d.vote_frac == 1.0, "干净页该是全票"


def test_page_with_accumulated_drift_still_anchors(index, page):
    """页内 14 处漏字把偏移摊成一片相邻值，真锚点仍要认得出来。"""
    drifted = _drop_every(page, 20)
    d = anchor_page_diag(drifted, index)
    assert d.anchored, d.reason
    assert d.offset == OFFSET, f"漂移页锚到了 {d.offset}，应为 {OFFSET}"
    assert d.vote_frac < 0.6, (
        f"票占比 {d.vote_frac:.2f} 太高，说明这页根本没漂移，"
        "这条用例就测不到它要测的东西")


def test_merging_adjacent_offsets_is_what_makes_that_work(index, page, monkeypatch):
    """把合并半径压到 1（等于不合并），同一页立刻锚不上。

    这就是 `POOL_RADIUS` 存在的理由：真锚点的票散在相邻偏移上，孤立比较
    会让它们互相"抵消"——占比各自不达标、优势又互相压制。
    """
    drifted = _drop_every(page, 20)
    monkeypatch.setattr(ae, "POOL_RADIUS", 1)
    d = anchor_page_diag(drifted, index)
    assert not d.anchored, (
        "不合并也能锚上的话，这条用例护不住 POOL_RADIUS——"
        f"换一个漂移更重的合成页：{d}")


def test_page_absent_from_the_corpus_reports_failure(index):
    """语料未收录（如目录页）→ 如实报失败。判据不许"来者不拒"。"""
    rng = random.Random(9)
    other = "".join(rng.choice("甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥")
                    for _ in range(PAGE_LEN))
    d = anchor_page_diag(other, index)
    assert not d.anchored
    assert d.offset is None
    assert d.reason, "没锚上却不说为什么"


def test_text_shorter_than_one_gram_is_not_an_error(index):
    """短于一个 n-gram 的页（几乎空白的页）报 0 票、不抛异常。"""
    d = anchor_page_diag("臣等", index)
    assert not d.anchored and d.n_grams == 0 and d.reason
