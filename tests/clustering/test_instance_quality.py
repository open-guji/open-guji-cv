"""单字图块质量标注格式 + 自检评测的单测。"""

import pytest

from open_guji_cv.clustering.instance_quality import (InstanceQuality,
                                                      evaluate_self_detection,
                                                      format_report,
                                                      load_dataset,
                                                      save_dataset)


def _iq(page, quality, layout="rigid"):
    return InstanceQuality(book="v", page=page, col=1, idx=0,
                           quality=quality, layout=layout)


def test_rejects_unknown_quality():
    with pytest.raises(ValueError):
        _iq("1", "mangled")


def test_roundtrip(tmp_path):
    items = [_iq("1", "clean"), _iq("2", "contaminated", "elastic")]
    f = tmp_path / "d.json"
    save_dataset(items, f)
    back = load_dataset(f)
    assert [b.quality for b in back] == ["clean", "contaminated"]
    assert back[1].layout == "elastic"
    assert back[0].key == "1:1:0"


def test_defect_recall_counts_all_three_defect_classes():
    gold = [_iq("1", "contaminated"), _iq("2", "truncated"),
            _iq("3", "not_text"), _iq("4", "clean")]
    flags = {"1:1:0": ["rule_like"], "2:1:0": [], "3:1:0": ["suspect_empty"],
             "4:1:0": []}
    r = evaluate_self_detection(gold, flags)
    assert r["n_defect"] == 3
    assert r["defect_recall"] == pytest.approx(2 / 3, abs=1e-4)
    assert r["false_alarm_rate"] == 0.0
    assert r["flag_precision"] == 1.0


def test_false_alarm_counted_and_lowers_precision():
    gold = [_iq("1", "contaminated"), _iq("2", "clean")]
    flags = {"1:1:0": ["bad_seg"], "2:1:0": ["rule_like"]}
    r = evaluate_self_detection(gold, flags)
    assert r["false_alarm_rate"] == 1.0
    assert r["flag_precision"] == 0.5


def test_any_flag_counts_as_detected():
    """驱动人工审查的是「有没有进队列」，不是标了哪个具体原因。"""
    gold = [_iq("1", "truncated")]
    assert evaluate_self_detection(gold, {"1:1:0": ["whatever"]})["defect_recall"] == 1.0
    assert evaluate_self_detection(gold, {"1:1:0": []})["defect_recall"] == 0.0


def test_report_mentions_each_class():
    gold = [_iq("1", "clean"), _iq("2", "contaminated")]
    txt = format_report(evaluate_self_detection(gold, {}))
    assert "clean" in txt and "contaminated" in txt and "缺陷检出率" in txt
