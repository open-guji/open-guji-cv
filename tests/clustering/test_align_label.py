"""align_label.py 单测：对齐标签必须落在正确的实例上，错位一格就算失败。"""

import json

from open_guji_cv.clustering.align_eval import build_ngram_index
from open_guji_cv.clustering.align_label import (index_structure, label_book,
                                                 label_page, page_slots,
                                                 summarize)

CORPUS = ("欽定四庫全書總目卷首一聖諭乾隆三十七年正月初四日奉上諭朕稽古右文"
          "聿資治理幾餘典學日有孜孜因思策府縹緗載籍極博其鉅者羽翼經訓垂範方來")


def _slots(text, col=1):
    return [(col, i, ch) for i, ch in enumerate(text)]


def test_equal_block_labels_every_instance():
    text = CORPUS[10:40]
    labels, anchored = label_page("7", _slots(text), "tb", CORPUS,
                                  build_ngram_index(CORPUS))
    assert anchored
    assert len(labels) == len(text)
    assert [x.char for x in labels] == list(text)
    assert [x.instance_id for x in labels] == [f"tb:7:1:{i}" for i in range(len(text))]
    assert {x.op for x in labels} == {"equal"}


def test_replace_takes_gold_from_corpus_not_from_transcription():
    """转写错的位置正是最有价值的标注——金标取语料字，不取转写字。"""
    text = list(CORPUS[10:40])
    text[5] = "傅"          # 制造一个单字转写错误（两侧有长 equal 段夹住）
    labels, _ = label_page("7", _slots("".join(text)), "tb", CORPUS,
                           build_ngram_index(CORPUS))
    wrong = [x for x in labels if x.op == "replace"]
    assert len(wrong) == 1
    assert wrong[0].instance_id == "tb:7:1:5"
    assert wrong[0].hyp == "傅"
    assert wrong[0].char == CORPUS[15]   # 金标来自语料


def test_insertion_segment_is_dropped_not_forced():
    """多切一个格（插入一个字）：错位段整段丢弃，后半页不能整体偏一格。"""
    text = CORPUS[10:40]
    spliced = text[:12] + "囗" + text[12:]
    labels, _ = label_page("7", _slots(spliced), "tb", CORPUS,
                           build_ngram_index(CORPUS))
    got = {x.instance_id: x.char for x in labels}
    assert "tb:7:1:12" not in got                      # 多出来的格没有标签
    for i in range(13, len(spliced)):                  # 后半页仍然对得上
        assert got[f"tb:7:1:{i}"] == spliced[i]


def test_unanchorable_page_yields_nothing():
    labels, anchored = label_page("7", _slots("一二三四五六七八九十"), "tb",
                                  CORPUS, build_ngram_index(CORPUS))
    assert not anchored and labels == []


def _write_book(tmp_path, ranked_slots, index_slots):
    book = tmp_path / "tb"
    (book / "phase4_chars").mkdir(parents=True)
    (book / "phase6_labels").mkdir(parents=True)
    (book / "phase6_labels" / "ranked.json").write_text(json.dumps({
        "results": [{"id": f"tb:7:{c}:{i}", "best": ch}
                    for c, i, ch in ranked_slots]}), encoding="utf-8")
    with open(book / "phase4_chars" / "index.jsonl", "w", encoding="utf-8") as f:
        for c, i, _ in index_slots:
            f.write(json.dumps({"page": "7", "col": c, "idx": i}) + "\n")
    return book


def test_structure_drift_drops_the_whole_page(tmp_path):
    """转写产自更早一次切分（这一列多了一格）→ 整页丢弃，绝不硬配。"""
    text = CORPUS[10:40]
    ranked = _slots(text)
    drifted = ranked + [(1, len(text), "囗")]        # 当前切分多切了一格
    book = _write_book(tmp_path, ranked, drifted)
    labels, stats = label_book("tb", book, _corpus_file(tmp_path))
    assert labels == []
    assert stats[0].structure_ok is False
    assert summarize(stats)["n_anchored"] == 0


def test_structure_match_passes(tmp_path):
    text = CORPUS[10:40]
    book = _write_book(tmp_path, _slots(text), _slots(text))
    labels, stats = label_book("tb", book, _corpus_file(tmp_path))
    assert len(labels) == len(text)
    s = summarize(stats)
    assert s["n_structure_ok"] == 1 and s["n_labeled"] == len(text)


def test_page_filter_and_index_structure(tmp_path):
    text = CORPUS[10:40]
    book = _write_book(tmp_path, _slots(text), _slots(text))
    labels, _ = label_book("tb", book, _corpus_file(tmp_path), pages={"999"})
    assert labels == []
    assert index_structure(book / "phase4_chars" / "index.jsonl") == {
        "7": [(1, i) for i in range(len(text))]}


def test_renumbered_column_is_drift_even_at_equal_count(tmp_path):
    """格数相同但 idx 起点变了，也是漂：编号对不上，标签会挂到别的实例上。"""
    text = CORPUS[10:40]
    ranked = _slots(text)
    renumbered = [(c, i + 1, ch) for c, i, ch in ranked]
    book = _write_book(tmp_path, ranked, renumbered)
    labels, stats = label_book("tb", book, _corpus_file(tmp_path))
    assert labels == [] and stats[0].structure_ok is False


def test_long_replace_run_is_rejected():
    """replace 段 >3 或没被 equal≥2 夹住的不采信（G5 采信规则）：
    段一长，位置本身就不可信，错标全从这里漏进来。"""
    text = list(CORPUS[10:40])
    for i in (5, 6, 7, 8):
        text[i] = "囗"
    labels, _ = label_page("7", _slots("".join(text)), "tb", CORPUS,
                           build_ngram_index(CORPUS))
    got = {x.instance_id for x in labels if x.op == "replace"}
    assert got == set()                       # 4 连错段整段不采
    for i in (5, 6, 7, 8):
        assert f"tb:7:1:{i}" not in {x.instance_id for x in labels}


def test_replace_at_window_edge_is_rejected():
    """页首的 replace 段没有左侧 equal 夹住 → 不采信。"""
    text = list(CORPUS[10:40])
    text[0] = "囗"
    labels, _ = label_page("7", _slots("".join(text)), "tb", CORPUS,
                           build_ngram_index(CORPUS))
    assert "tb:7:1:0" not in {x.instance_id for x in labels}


def test_page_slots_orders_by_column_then_index():
    ranked = [{"id": "tb:7:2:1", "best": "乙"}, {"id": "tb:7:1:0", "best": "甲"},
              {"id": "tb:7:2:0", "best": "丙"}]
    assert page_slots(ranked)["7"] == [(1, 0, "甲"), (2, 0, "丙"), (2, 1, "乙")]


def _corpus_file(tmp_path):
    p = tmp_path / "corpus.txt"
    p.write_text(CORPUS, encoding="utf-8")
    return p


def test_page_reference_no_gate_and_gaps():
    """免闸参考：长 replace 段也逐位给参考字；insert/delete 段给 None。

    与 label_page 的采信闸形成对照——参考层的用途是审查页面上给人看，
    噪声大没关系，位置对得上才是它的全部价值。
    """
    from open_guji_cv.clustering.align_eval import build_ngram_index
    from open_guji_cv.clustering.align_label import page_reference

    head = "天地玄黃宇宙洪荒日月盈昃辰宿列張"      # 16 字全对（锚定票源）
    mid = "寒來暑往秋"                               # 语料真文，载体错读成 誤×5
    tail = "收冬藏閏餘成歲律呂調陽"                  # 尾部再回到全对
    corpus = head + mid + tail
    idx = build_ngram_index(corpus)
    page_text = head + "誤誤誤誤誤" + tail
    slots = [(1, i, ch) for i, ch in enumerate(page_text)]
    refs = page_reference("1", slots, corpus, idx)
    assert refs[(1, 0)] == ("天", "equal")
    for i, want in enumerate(mid):                   # 段长 5 > 采信闸的 3
        got = refs[(1, len(head) + i)]
        assert got[0] == want and got[1] == "replace"


def test_carrier_slots_drops_stale_entries(tmp_path):
    """载体比索引多出格位 → 必须丢掉，否则整列文本后移一位。

    vol01 第 14 页实锤：切分重跑 164→163 格、载体仍 164 条，锚定照样
    "成功"但采信闸全灭（过闸对齐 162/180 → 0/163），且**不报任何错**
    ——整页看着像"没锚定"。这是最坏的失败模式，必须有回归钉住。
    """
    from open_guji_cv.clustering.align_label import carrier_slots
    p = tmp_path / "carrier.jsonl"
    p.write_text("".join(json.dumps(
        {"id": f"b:1:1:{i}", "char": c, "prob": 0.9}, ensure_ascii=False) + "\n"
        for i, c in enumerate("天地玄黃")), encoding="utf-8")

    # 不给 valid_ids：照单全收（旧行为，向后兼容）
    assert [c for _, _, c in carrier_slots(p)["1"]] == list("天地玄黃")
    # 给了索引 id：载体里多出的 b:1:1:2 被丢掉，剩下的顺序不变
    valid = {"b:1:1:0", "b:1:1:1", "b:1:1:3"}
    assert [c for _, _, c in carrier_slots(p, valid_ids=valid)["1"]] == \
        list("天地黃")


def test_carrier_slots_tolerates_missing_entries(tmp_path):
    """索引有而载体无：无害（那一格没 OCR 而已），不该报错也不该丢别的。"""
    from open_guji_cv.clustering.align_label import carrier_slots
    p = tmp_path / "carrier.jsonl"
    p.write_text(json.dumps({"id": "b:1:1:0", "char": "天", "prob": 0.9}) + "\n",
                 encoding="utf-8")
    got = carrier_slots(p, valid_ids={"b:1:1:0", "b:1:1:1", "b:1:1:2"})
    assert [c for _, _, c in got["1"]] == ["天"]
