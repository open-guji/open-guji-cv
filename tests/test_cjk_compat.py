"""兼容汉字折叠（utils/cjk_compat）：福 U+FA1B → U+798F，入口出口都不留兼容码位。"""
from open_guji_cv.utils.cjk_compat import count_compat, fold_compat, fold_unique, is_compat

FU_COMPAT, FU = "福", "福"


def test_fold_basic():
    assert fold_compat(FU_COMPAT) == FU
    assert fold_compat("\U0002F8D0") == "㛈" or fold_compat("\U0002F8D0") != "\U0002F8D0"
    assert fold_compat(None) is None and fold_compat("") == ""
    assert fold_compat("福祿壽") == "福祿壽"           # 已是统一汉字原样


def test_true_unified_in_compat_block_untouched():
    # 兼容区里 12 个本就是统一汉字（无规范分解）：不折
    for cp in (0xFA0E, 0xFA0F, 0xFA11, 0xFA13, 0xFA14, 0xFA1F, 0xFA21, 0xFA23, 0xFA24,
               0xFA27, 0xFA28, 0xFA29):
        assert not is_compat(chr(cp)) and fold_compat(chr(cp)) == chr(cp)


def test_ids_and_ivs_untouched():
    assert fold_compat("⿰亻斯") == "⿰亻斯"
    assert fold_compat("葛\U000E0101") == "葛\U000E0101"


def test_fold_unique_and_count():
    assert fold_unique([FU_COMPAT, FU, "a"]) == [FU, "a"]
    assert count_compat(f"{FU_COMPAT}{FU}{FU_COMPAT}") == {FU_COMPAT: 2}


def test_charsets_have_no_compat():
    from open_guji_cv.clustering.charset_spec import base_charset
    for name in ("unicode-cjk-a", "unicode-compat", "unicode-all", "kangxi"):
        assert not any(is_compat(c) for c in base_charset(name)), name


def test_product_models_fold_char():
    from open_guji_cv.products.kinds.recog import AdmitRec
    assert AdmitRec(id="x", slot=1, char=FU_COMPAT).char == FU
