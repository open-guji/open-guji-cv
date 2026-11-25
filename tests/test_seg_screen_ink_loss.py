"""seg_screen 清理吃掉字笔两条墨账（全唐文 R033／R038，2026-11-18）：erased_strokes、bbox_drop。"""
import numpy as np

from open_guji_cv.eval.seg_screen import bbox_drop, erased_strokes

H, W = 1000, 340


def _col():
    g = np.full((H, W), 255, np.uint8)
    g[:, 2:6] = 0                          # 右界行（贯穿）
    g[:, 334:338] = 0
    return g


def test_erased_stroke_reported():
    """「十」的竖贴着界行、下半截被清界行抹了：被抹的那块离两边都远、上下不贯穿 → 报。"""
    raw = _col()
    raw[300:308, 150:270] = 0              # 横
    raw[250:420, 250:265] = 0              # 竖
    clean = raw.copy()
    clean[:, 0:8] = 255                    # 界行抹掉：贴边，不报
    clean[:, 332:] = 255
    clean[310:420, 250:265] = 255          # 竖的下半截被当界行抹了
    hits = erased_strokes(raw, clean)
    assert len(hits) == 1 and hits[0]["bbox"][0] == 250


def test_inner_rule_erased_not_reported():
    """页边列双线：内框贯穿多格，抹掉是对的。"""
    raw = _col()
    raw[:, 300:306] = 0
    clean = raw.copy()
    clean[:, 298:] = 255
    clean[:, :8] = 255
    assert erased_strokes(raw, clean) == []


def test_bbox_drop_reports_lost_radical():
    """单字成列的「制」：刂 在字框外、字所在那几行里 → 报，归第 5 格。"""
    g = np.full((H, W), 255, np.uint8)
    g[300:480, 70:190] = 0                 # 左半，在字框里
    g[300:490, 220:250] = 0                # 刂，字框外
    hits = bbox_drop(g, [("5", (64, 295, 195, 495))])
    assert len(hits) == 1 and hits[0]["slot"] == "5"


def test_bbox_drop_ignores_rules_and_specks():
    g = _col()
    g[300:480, 70:250] = 0
    g[600:605, 200:210] = 0                # 麻点
    assert bbox_drop(g, [("5", (64, 295, 255, 485))]) == []
