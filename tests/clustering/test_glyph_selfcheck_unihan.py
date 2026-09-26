# -*- coding: utf-8 -*-
"""体检的 Unihan 异体豁免：只认指定属性的边，形近字（无边 / kSpoofingVariant）照旧互判。"""

from open_guji_cv.clustering.glyph_selfcheck import UNIHAN_SAME_WIDE, _unihan_same


def test_unihan_same_default_and_wide():
    uv = _unihan_same()
    assert uv("強", "强") and uv("戸", "戶") and uv("卽", "即")
    assert not uv("內", "内")            # 只有简繁边，缺省不认
    assert not uv("千", "干") and not uv("強", "強")
    wide = _unihan_same(UNIHAN_SAME_WIDE)
    assert wide("內", "内") and wide("別", "别")
    assert not wide("千", "干")
