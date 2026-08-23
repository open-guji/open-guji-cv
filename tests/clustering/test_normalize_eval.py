"""normalize_eval.py 单测：回归门必须真的会响。

一个永远通过的门等于没有门，所以这里重点测「改坏了会不会被抓住」，
而且分开测三个指标各自该抓的那类变化。
"""

import json
import random

import cv2
import numpy as np

from open_guji_cv.clustering.normalize import normalize_patch, skeletonize
from open_guji_cv.clustering.normalize_eval import (binary_iou, check_sample,
                                                    pixel_diff_ratio,
                                                    skeleton_endpoint_delta,
                                                    skeleton_nodes, summarize,
                                                    to_binary)
from open_guji_cv.clustering.synth import synthetic_glyph


def _gray(binary, canvas=100, offset=(10, 10)):
    gray = np.full((canvas, canvas), 230, dtype=np.uint8)
    h, w = binary.shape
    y, x = offset
    gray[y:y + h, x:x + w][binary > 0] = 25
    return gray


def _make_sample(tmp_path, name="001", status="verified", tol=None):
    d = tmp_path / name
    d.mkdir()
    gray = _gray(synthetic_glyph(random.Random(3)))
    norm = normalize_patch(gray)
    cv2.imwrite(str(d / "input.png"), gray)
    cv2.imwrite(str(d / "golden.png"), norm * 255)
    cv2.imwrite(str(d / "golden_skeleton.png"), skeletonize(norm) * 255)
    (d / "expected.json").write_text(json.dumps({
        "input": "input.png", "golden": "golden.png",
        "golden_skeleton": "golden_skeleton.png", "status": status,
        "tolerance": tol or {"pixel_diff_ratio": 0.01, "binary_iou_min": 0.98,
                             "skeleton_endpoint_delta_max": 2},
    }), encoding="utf-8")
    return d, norm


def test_identical_output_passes(tmp_path):
    d, norm = _make_sample(tmp_path)
    r = check_sample(d, norm, skeletonize(norm))
    assert r.passed and r.pixel_diff_ratio == 0.0 and r.binary_iou == 1.0


def test_shifted_output_fails_the_gate(tmp_path):
    """整体平移 2px：像素比与 IoU 都该报。"""
    d, norm = _make_sample(tmp_path)
    moved = np.roll(norm, 2, axis=0)
    r = check_sample(d, moved, skeletonize(moved))
    assert not r.passed
    assert any("pixel_diff_ratio" in x for x in r.reasons)


def test_broken_stroke_is_caught_by_skeleton_even_if_pixels_barely_move(tmp_path):
    """断一笔只改几十个像素，像素比可能还在容差内——拓扑指标必须接住。"""
    d, norm = _make_sample(tmp_path)
    broken = norm.copy()
    ys, xs = np.nonzero(broken)
    cy = int(np.median(ys))
    broken[cy - 1:cy + 2, :] = 0                  # 横切一刀，笔画断开
    r = check_sample(d, broken, skeletonize(broken))
    assert not r.passed
    assert any("skeleton_endpoint_delta" in x for x in r.reasons)


def test_loose_tolerance_still_catches_gross_change(tmp_path):
    d, _ = _make_sample(tmp_path, tol={"pixel_diff_ratio": 0.5,
                                       "binary_iou_min": 0.1,
                                       "skeleton_endpoint_delta_max": 99})
    blank = np.zeros((64, 64), dtype=np.uint8)
    r = check_sample(d, blank, blank)
    assert not r.passed and any("binary_iou" in x for x in r.reasons)


def test_metrics_basics():
    a = np.zeros((8, 8), np.uint8)
    a[2:6, 2:6] = 1
    b = a.copy()
    b[2, 2] = 0
    assert pixel_diff_ratio(a, b) == 1 / 64
    assert abs(binary_iou(a, b) - 15 / 16) < 1e-9
    assert binary_iou(np.zeros((4, 4), np.uint8), np.zeros((4, 4), np.uint8)) == 1.0
    line = np.zeros((9, 9), np.uint8)
    line[4, 1:8] = 1
    assert skeleton_nodes(line)[0] == 2          # 一条线两个端点
    assert skeleton_endpoint_delta(line, line) == 0


def test_to_binary_thresholds_png_levels():
    assert to_binary(np.array([[0, 127, 128, 255]], np.uint8)).tolist() == [[0, 0, 1, 1]]


def test_summary_gates_verified_only(tmp_path):
    ok, norm = _make_sample(tmp_path, "001")
    bad, bad_norm = _make_sample(tmp_path, "002", status="known_defect")
    results = [check_sample(ok, norm, skeletonize(norm)),
               check_sample(bad, np.zeros((64, 64), np.uint8),
                            np.zeros((64, 64), np.uint8))]
    s = summarize(results)
    assert s["gate"]["ok"] and s["gate"]["n"] == 1
    assert s["known_defect"]["n"] == 1 and s["known_defect"]["unchanged"] == 0
    assert s["known_defect"]["changed"][0]["sample"] == "002"
