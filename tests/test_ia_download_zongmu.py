"""scripts/ia_download_zongmu.py 的书单与选文件（GUJI-648）：全书 99 册两段编号，缺省取 _tif.zip。不联网。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "ia_download_zongmu", Path(__file__).resolve().parents[1] / "scripts" / "ia_download_zongmu.py")
M = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(M)


def test_items_two_ranges():
    assert len(M.ITEMS) == 99
    assert M.ITEMS[0] == "06061300.cn" and M.ITEMS[20] == "06061320.cn"   # vol21 是第一段最后一册
    assert M.ITEMS[21] == "06066140.cn" and M.ITEMS[-1] == "06066217.cn"
    assert "06061321.cn" not in M.ITEMS                                   # 06061321 起是别的书


def test_select_by_volume():
    assert M.select("11-12,22") == ["06061310.cn", "06061311.cn", "06066140.cn"]
    assert M.select(None) == M.ITEMS
    with pytest.raises(SystemExit):
        M.select("100")


def test_pick_prefers_tif_zip():
    meta = {"files": [{"name": "x_cnbook.zip", "size": "900"}, {"name": "x_tif.zip", "size": "500"},
                      {"name": "x.pdf", "size": "300"}]}
    assert M.pick_file(meta, "tif")["name"] == "x_tif.zip"
    assert M.pick_file(meta, "pdf")["name"] == "x.pdf"
    assert M.pick_file({"files": [{"name": "x_cnbook.zip", "size": "9"}]}, "tif")["name"] == "x_cnbook.zip"
