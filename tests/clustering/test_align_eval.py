"""align_eval.py 单测：n-gram 锚定 + 序列对齐评测。"""

from open_guji_cv.clustering.align_eval import (align_page, anchor_page,
                                                 build_ngram_index,
                                                 evaluate_book, top_confusions)

CORPUS = ("欽定四庫全書總目卷首一聖諭乾隆三十七年正月初四日奉上諭朕稽古右文聿資治理"
         "幾餘典學日有孜孜因思策府縹緗載籍極博其鉅者羽翼經訓垂範方來固足稱千秋法鑒"
         "即在識小之徒專門撰述細及名物象數兼綜條貫各自成家亦莫不有所發明可爲游藝")


def test_anchor_page_finds_correct_offset():
    index = build_ngram_index(CORPUS)
    text = "卷首一聖諭乾隆三十七年正月"
    offset = anchor_page(text, index)
    assert offset is not None
    assert CORPUS[offset:offset + len(text)] == text


def test_anchor_page_rejects_unrelated_text():
    index = build_ngram_index(CORPUS)
    assert anchor_page("這一頁完全不在語料裡九九八七六五四三", index) is None


def test_anchor_page_too_short():
    index = build_ngram_index(CORPUS)
    assert anchor_page("短", index) is None


def test_align_page_perfect_match_scores_100pct():
    offset = 5
    text = CORPUS[offset:offset + 20]
    matched, total = align_page(text, CORPUS, offset)
    assert matched == total == 20


def test_align_page_tolerates_one_substitution():
    offset = 5
    text = list(CORPUS[offset:offset + 20])
    text[10] = "錯"
    matched, total = align_page("".join(text), CORPUS, offset)
    assert total == 20
    assert matched == 19          # 一字之差，其余全部命中


def test_evaluate_book_end_to_end(tmp_path):
    (tmp_path / "1.txt").write_text("卷首一聖諭乾\n隆三十七年正月初四日奉上諭朕",
                                    encoding="utf-8")
    (tmp_path / "2.txt").write_text("完全不相干的頁面內容九九八七六五四三二一零壹貳",
                                    encoding="utf-8")
    report = evaluate_book(tmp_path, CORPUS)
    assert report["n_pages"] == 2
    assert report["n_anchored"] == 1          # 第 2 页锚定不上，正确剔除
    assert report["accuracy"] == 1.0
    by_page = {p["page"]: p for p in report["pages"]}
    assert by_page["1"]["anchored"] is True
    assert by_page["2"]["anchored"] is False


def test_evaluate_book_page_sort_numeric_not_lexicographic(tmp_path):
    for n in (1, 2, 10):
        (tmp_path / f"{n}.txt").write_text("x", encoding="utf-8")
    report = evaluate_book(tmp_path, CORPUS)
    assert [p["page"] for p in report["pages"]] == ["1", "2", "10"]


def test_top_confusions_reports_replace_only(tmp_path):
    offset = 5
    text = list(CORPUS[offset:offset + 20])
    text[3] = "錯"
    (tmp_path / "1.txt").write_text("".join(text), encoding="utf-8")
    index = build_ngram_index(CORPUS)
    confusions = top_confusions(tmp_path, CORPUS, index)
    assert any(k.endswith(f"→{CORPUS[offset + 3]}") for k, _n in confusions)
