# -*- coding: utf-8 -*-
"""`utils/calibrate.py`：册级先验的实测 vs yaml 现值对照。

这里钉死的是**判定口径**，不是量法本身（量法是 `measure_*` 的事，各有自己的测试）。
最要紧的一条是最后那个：一个都没测出来时**不许报成功**。
"""
from __future__ import annotations

from open_guji_cv.utils.calibrate import DRIFT_FRAC, Row, format_table


def test_verdict_一致_与_漂了():
    """偏差在阈值内判「一致」，超出判「漂了」。边界按 DRIFT_FRAC 算。"""
    assert Row("period_prior", 100.0, 102.0).verdict == "一致"      # +2% < 3%
    assert Row("period_prior", 100.0, 110.0).verdict == "漂了"      # +10% > 3%
    # 恰好卡在阈值上算一致（判据是 > 才算漂）
    assert Row("period_prior", 100.0, 100.0 + 100.0 * DRIFT_FRAC).verdict == "一致"


def test_verdict_未配_与_未测出():
    """「没测出来」「yaml 没配」都不是「漂了」——三者要分得开。"""
    assert Row("bottom_gap", None, 325.0).verdict == "未配"
    assert Row("bottom_gap", 325.0, None).verdict == "未测出"
    assert Row("bottom_gap", None, None).verdict == "未测出"


def test_drift_pct_只在两边都有时才算():
    assert Row("x", 100.0, 110.0).drift_pct == 10.0
    assert Row("x", 100.0, None).drift_pct is None
    assert Row("x", None, 110.0).drift_pct is None


def test_一个都没测出来时不报成功():
    """**这条是本模块的红线。**

    「没测出来」和「测了没问题」是两回事。四庫總目那十册 yaml 里没写 `pages:`，
    早期版本在这里拿到 0 页、一个先验都没比，却照印「✅ 都与 yaml 一致」——
    看的人会以为复核过了。现在必须明说「没比」。
    """
    rows = [Row("period_prior", 115.0, None, ""), Row("bottom_gap", 325.0, None, "")]
    txt = format_table(rows, {"pages": 0, "body_pages": None, "body_source": "x"}, "vol01")
    assert "✅" not in txt
    assert "没比" in txt


def test_有比对且都一致时报成功且说清比了几个():
    rows = [Row("period_prior", 115.0, 114.0, ""), Row("bottom_gap", 325.0, None, "")]
    txt = format_table(rows, {"pages": 206, "body_pages": 204, "body_source": "闸1 page_type"}, "vol01")
    assert "✅" in txt
    assert "1 个" in txt          # 只有 period_prior 真比上了，bottom_gap 未测出不算


def test_产物过期时不认那个一致():
    """**第二条红线。**

    `period_prior` 是从闸2 产物**读**出来的——产物陈旧就等于拿旧算法的结果去
    复核新配置。2026-09-16 bxgb 实测踩到：册 yaml 把 `expected_cols` 从 20 改成
    19 之后产物全过期，`calibrate` 照样把旧产物平均了印出「✅ 一致」。
    数值碰巧相符不代表复核过了。
    """
    rows = [Row("period_prior", 70.6, 72.0, "")]
    diag = {"pages": 54, "body_pages": 54, "body_source": "闸1 page_type",
            "stale": 19, "checked": 54}
    txt = format_table(rows, diag, "bxgb")
    assert "✅" not in txt
    assert "过期" in txt
    assert "不作数" in txt


def test_产物新鲜时照常报成功():
    """过期数为 0 / 查不到（None）时不该平白多出警告。"""
    rows = [Row("period_prior", 115.0, 114.0, "")]
    for st in (0, None):
        diag = {"pages": 206, "body_pages": 204, "body_source": "闸1 page_type",
                "stale": st, "checked": 206}
        txt = format_table(rows, diag, "vol01")
        assert "✅" in txt
        assert "过期" not in txt


def test_漂了时提示不自动改yaml():
    """漂了要给的是「去查为什么」，不是「照抄实测值」——自动回写是明确不做的事。"""
    rows = [Row("period_prior", 70.6, 106.5, "")]
    txt = format_table(rows, {"pages": 54, "body_pages": 54, "body_source": "闸1 page_type"}, "bxgb")
    assert "⚠️" in txt
    assert "不会自动改 yaml" in txt
    assert "period_prior" in txt
