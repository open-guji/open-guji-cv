"""册号统一（core/volume_id，2026-11-02）。"""
from open_guji_cv.core.volume_id import chapter_of, from_dict, vol_label, volume_of, width_for


def test_width_by_total():
    # 用户 11-27：1–9 册 1 位、10–99 两位、100 起三位
    assert width_for(1) == 1 and width_for(6) == 1 and width_for(9) == 1
    assert width_for(10) == 2 and width_for(42) == 2 and width_for(99) == 2
    assert width_for(100) == 3 and width_for(248) == 3
    assert vol_label(7, 3) == "007" and vol_label(7, 1) == "7" and vol_label(7) == "07"


def test_one_digit_book_and_chapter_follow():
    v = from_dict("1", {"volume": 1, "volume_width": 1})
    assert (v.label, v.chapter, v.chapter_mismatch) == ("1", "1", False)
    v = from_dict("01", {"volume": 1, "volume_width": 2, "chapter_width": 3})   # 还没迁的脉经
    assert (v.label, v.chapter, v.chapter_mismatch) == ("01", "001", True)


def test_same_volume():
    from open_guji_cv.core.volume_id import same_volume
    assert same_volume("1", "001") and same_volume(1, "01") and same_volume("042", "42")
    assert not same_volume("1", "2") and not same_volume("vol01", "01") and not same_volume(None, "1")


def test_legacy_volnn_keeps_three_digit_chapter():
    v = from_dict("vol04", {})
    assert (v.volume, v.label, v.chapter) == (4, "04", "004")


def test_non_vol_name_no_longer_becomes_000():
    assert from_dict("bxgb", {}).chapter is None
    v = from_dict("bxgb", {"book_id": "988g7gsqhd", "volume": 1, "chapter_width": 3})
    assert (v.book_id, v.label, v.chapter) == ("988g7gsqhd", "01", "001")


def test_numeric_names_follow_book_width():
    assert from_dict("05", {"volume_width": 3}).label == "005"
    v = from_dict("005", {"volume": 5, "volume_width": 3})
    assert (v.label, v.chapter) == ("005", "005")
    assert from_dict("17", {}).chapter == "17"


def test_reads_workspace_yaml(tmp_path):
    books = tmp_path / "books"
    books.mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "book_defaults.yaml").write_text(
        "book_id: 995ejelvk0\nvolume_width: 3\n", encoding="utf-8")
    (books / "012.yaml").write_text("id: '012'\nvolume: 12\nraw_dir: x\n", encoding="utf-8")
    v = volume_of("012", books)
    assert (v.book_id, v.label, v.chapter) == ("995ejelvk0", "012", "012")
    assert chapter_of("012", None, books) == "012"
    assert chapter_of("012", "099", books) == "099"
    assert volume_of("nope", books).volume is None
