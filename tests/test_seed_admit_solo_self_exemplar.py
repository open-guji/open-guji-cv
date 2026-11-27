"""`solo_self_exemplar`：match_solo 系的刻例就在本页本列时不放行（殿本 vol01:88:6:9b 管→總、vol02:150:3:14 鶴→號）。"""
from open_guji_cv.steps.seed_admit import _same_column_exemplar
from open_guji_cv.steps.seed_admit_params import SeedAdmitParams


def test_same_page_column_hits():
    assert _same_column_exemplar("vol01:88:6:9b", "v2:vol01:88:6:6b")
    assert _same_column_exemplar("vol02:143:5:8a", "v2~r2~vol02~143~5~7a")


def test_other_page_or_column_or_missing_not_hit():
    assert not _same_column_exemplar("vol01:88:6:9b", "v2:vol01:12:6:6b")
    assert not _same_column_exemplar("vol01:88:6:9b", "v2:vol01:88:5:6b")
    assert not _same_column_exemplar("vol01:88:6:9b", "v2:vol03:88:6:6b")
    assert not _same_column_exemplar("vol01:88:6:9b", None)
    assert not _same_column_exemplar("vol01:88:6:9b", "")


def test_default_off_and_not_in_dump():
    assert SeedAdmitParams().solo_self_exemplar is False
    assert "solo_self_exemplar" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(solo_self_exemplar=True).model_dump()["solo_self_exemplar"] is True
