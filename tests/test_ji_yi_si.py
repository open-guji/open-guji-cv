# -*- coding: utf-8 -*-
"""己/已/巳：字形只定一族，哪个字由文意定（utils/ji_yi_si.py，用户 2026-09-26）。"""
from open_guji_cv.utils.ji_yi_si import resolve


def test_ganzhi_and_time():
    assert resolve("癸", "雨", None)[0] == "巳"      # 十一日癸巳雨
    assert resolve("日", "丑", "已")[0] == "己"      # 八日己丑：干支压过整理本
    assert resolve("辰", "間", None)[0] == "巳"
    assert resolve("罷", "初", None)[0] == "巳"      # 巳初


def test_ji_collocation_and_default():
    assert resolve("自", "之", None)[0] == "己"
    assert resolve("而", "今", "巳")[0] == "已"      # 四庫整理本也把「而已」寫成「而巳」，不信
    assert resolve("未", "者", None)[0] == "已"      # 未已：前字是地支也不當干支
    assert resolve("書", "見", "己")[0] == "己"      # 整理本給「己」才採信


def test_wei_after_is_negation_unless_date():
    assert resolve("而", "未", None)[0] == "已"      # 繕錄而已未嘗
    assert resolve("日", "未", None)[0] == "己"      # 十七日己未
    assert resolve("稱", "未", None, next2="歳")[0] == "己"   # 自序稱己未歳
