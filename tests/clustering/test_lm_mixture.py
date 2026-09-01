"""LM 线性插值与剪枝的单测。"""

import math

from open_guji_cv.clustering.lm import (CharNgramLM, InterpolatedLM, UniformLM,
                                        train_ngram)


def test_mixture_is_between_components():
    a = train_ngram(["天下之至柔馳騁天下之至堅"], 3)
    b = train_ngram(["欽定四庫全書總目提要"], 3)
    m = InterpolatedLM([(a, 0.5), (b, 0.5)])
    for ch, ctx in [("全", ("庫",)), ("之", ("下",))]:
        lo = min(a.logp(ch, ctx), b.logp(ch, ctx))
        hi = max(a.logp(ch, ctx), b.logp(ch, ctx))
        assert lo <= m.logp(ch, ctx) <= hi


def test_one_component_ignorance_does_not_veto():
    """线性插值的全部意义：一个分量没见过的字，另一个分量还救得回来。

    对数线性（几何）混合在这里会被拖到接近零——本书专名恰好就是通用
    语料没有的那些，一票否决等于把混合的收益全否掉。
    """
    general = train_ngram(["天下之至柔馳騁天下之至堅" * 20], 3)
    book = train_ngram(["永樂大典" * 20], 3)
    mixed = InterpolatedLM([(general, 0.1), (book, 0.9)])
    ctx = ("樂",)
    assert mixed.logp("大", ctx) > general.logp("大", ctx)
    # 几何混合的对照：会低于线性混合，被无知分量拖下去
    geo = 0.1 * general.logp("大", ctx) + 0.9 * book.logp("大", ctx)
    assert mixed.logp("大", ctx) > geo


def test_weights_are_normalised():
    a = train_ngram(["甲乙丙丁"], 3)
    b = train_ngram(["戊己庚辛"], 3)
    assert InterpolatedLM([(a, 2), (b, 6)]).name == \
        InterpolatedLM([(a, 0.25), (b, 0.75)]).name


def test_zero_weight_component_dropped():
    a = train_ngram(["甲乙丙丁"], 3)
    b = train_ngram(["戊己庚辛"], 3)
    m = InterpolatedLM([(a, 1.0), (b, 0.0)])
    assert len(m.components) == 1


def test_empty_mixture_is_uniform():
    m = InterpolatedLM([])
    assert m.logp("甲", ()) == UniformLM().logp("甲", ())


def test_prune_drops_hapax_high_order_but_keeps_backoff():
    lm = CharNgramLM(order=3)
    lm.train(["甲乙丙" * 5, "丁戊己"])
    before = len(lm.counts[2])
    lm.prune(min_count=2)
    assert len(lm.counts[2]) < before
    assert len(lm.counts[0]) == 1        # 一元兜底不许被剪掉
    assert lm.logp("甲", ("丁",)) > -math.inf
