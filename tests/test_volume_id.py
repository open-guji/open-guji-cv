"""册号统一（core/volume_id，2026-11-02）。"""
from open_guji_cv.core.volume_id import chapter_of, from_dict, vol_label, volume_of, width_for


def test_width_by_total():
    assert width_for(1) == 2 and width_for(42) == 2 and width_for(99) == 2
    assert width_for(100) == 3 and width_for(248) == 3
    assert vol_label(7, 3) == "007" and vol_label(7) == "07"


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
