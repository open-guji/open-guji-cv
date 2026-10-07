# -*- coding: utf-8 -*-
"""己已巳词组规则（research/char_groups/jys/rules.py，overview#443）。自造上下文，不读真书数据。"""
import importlib.util
from pathlib import Path

_p = Path(__file__).resolve().parents[1] / "research/char_groups/jys/rules.py"
_spec = importlib.util.spec_from_file_location("jys_rules", _p)
rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rules)


def test_ganzhi():
    assert rules.classify("康熙癸", "年")[0] == "巳"
    assert rules.classify("順治", "丑")[0] == "己"


def test_er_yi_and_exception():
    assert rules.classify("不過如此而", "矣")[0] == "已"
    # 书名《己易》被「而已」规则误伤（vol05:36:6:15）：改为弃权
    assert rules.classify("名徒生轇轕而", "易芥八卷浙江")[0] is None


def test_self():
    assert rules.classify("斷以", "意")[0] == "己"
    assert rules.classify("參以", "見")[0] == "己"
    assert rules.classify("克", "復禮")[0] == "己"


def test_abstain():
    assert rules.classify("又", "易一卷")[0] is None
