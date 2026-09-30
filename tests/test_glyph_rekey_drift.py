# -*- coding: utf-8 -*-
"""挪回漂移人裁（`scripts/glyph_rekey_drift.py`）：以前两处 `continue` 会整行吞掉、
跑完一句话都不留（任务书 H·v1重键与撤例按B后重定 §5：vol02 187:9:4 那条静默跳过）——
现在都要落进 `noop` 并打印原因。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering.canonical import to_canonical
from open_guji_cv.clustering.glyph_db import GlyphDB
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.utils.binarized import binarize_page

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("glyph_rekey_drift", REPO / "scripts" / "glyph_rekey_drift.py")
DRIFT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DRIFT)


def _canon_png(k: int) -> tuple[bytes, np.ndarray]:
    """一张已经跑过 binarize+canonical 的图（幂等——脚本会再跑一遍这两步，
    结果要一样，cov 才能到 1.0）。"""
    img = np.full((80, 80), 255, np.uint8)
    cv2.rectangle(img, (16 + k, 16), (64, 64 - k), 0, 4)
    canon = to_canonical(binarize_page(img, edge_margin=0))
    return cv2.imencode(".png", canon)[1].tobytes(), canon


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "g.db"
    png0, canon0 = _canon_png(0)
    g = GlyphDB(db_path)
    g.admit_instance("v2:vol01:5:3:2", "甲", png0, provenance="human", page="5", col=3, idx=2)
    g.close()
    cache_root = tmp_path / "cache"
    cache = ImageCache(cache_root)
    cache.put("vol01", "char_patch", "p0005c03s2", canon0)   # 缓存里同一格现在还是这张图
    monkeypatch.setenv("GUJI_GLYPH_DB", str(db_path))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache_root))
    return db_path, cache_root


def _run(monkeypatch, rows_path, *extra):
    monkeypatch.setattr(sys, "argv", ["x", str(rows_path), *extra])
    assert DRIFT.main() == 0


def test_missing_instance_reports_noop_not_silent(env, monkeypatch, capsys, tmp_path):
    """`instance_id` 库里压根没有（打错、或已被别的批次撤过）：以前直接 `continue`，
    现在要落进 `noop` 并说明「库里没有这实例」。"""
    import json
    db_path, cache_root = env
    rows = tmp_path / "rows.jsonl"
    rows.write_text(json.dumps({"instance_id": "v2:vol01:5:3:999", "cell": "vol01:5:3:999",
                                "check": "drift", "why": "manual"}) + "\n", encoding="utf-8")
    _run(monkeypatch, rows)
    out = capsys.readouterr().out
    assert "noop v2:vol01:5:3:999 库里没有这实例" in out
    assert "不用挪/查不到 1" in out
    assert "可挪 0，挪不动 0" in out


def test_already_at_current_cell_reports_noop_not_silent(env, monkeypatch, capsys, tmp_path):
    """算出来的现格就是自己当前的格（图没变、drift 检测多疑了一场）：以前直接
    `continue`，现在要落进 `noop`，报「已经在算出来的现格，不用挪」。"""
    import json
    db_path, cache_root = env
    rows = tmp_path / "rows.jsonl"
    rows.write_text(json.dumps({"instance_id": "v2:vol01:5:3:2", "cell": "vol01:5:3:2",
                                "check": "drift", "why": "manual"}) + "\n", encoding="utf-8")
    _run(monkeypatch, rows, "--debug")
    out = capsys.readouterr().out
    assert "noop v2:vol01:5:3:2 已经在算出来的现格 vol01:5:3:2，不用挪" in out
    assert "可挪 0，挪不动 0，不用挪/查不到 1" in out
