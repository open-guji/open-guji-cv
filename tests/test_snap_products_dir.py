"""`guji snap import` 要认 `GUJI_PRODUCTS_DIR`（沙箱），不能无视它写进工作区本体（GUJI-555）。"""
from __future__ import annotations

import os
from pathlib import Path

from open_guji_cv.snap import importer


def test_products_root_defaults_to_workspace_products(monkeypatch, tmp_path):
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    assert importer.products_root_for(tmp_path / "ws") == tmp_path / "ws" / "products"


def test_products_root_follows_sandbox_env(monkeypatch, tmp_path):
    box = tmp_path / "sandbox" / "products"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(box))
    assert importer.products_root_for(tmp_path / "ws") == box


def test_freshness_measures_the_same_root_and_restores_env(ws, monkeypatch, tmp_path):
    """量新鲜度时 `GUJI_PRODUCTS_DIR` 保持设着（量的就是沙箱那份），跑完环境原样还原。"""
    import open_guji_cv.core.engine as E
    box = tmp_path / "sandbox" / "products"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(box))
    monkeypatch.setenv("GUJI_WORKSPACE", "/elsewhere")
    seen: dict = {}

    class FakeEngine:
        def __init__(self, *a, **k):
            pass

        def status(self, pages=None):
            seen["products"] = os.environ.get("GUJI_PRODUCTS_DIR")
            seen["ws"] = os.environ.get("GUJI_WORKSPACE")
            return {"steps": {}}

    monkeypatch.setattr(E, "Engine", FakeEngine)
    importer.default_freshness(Path(ws), "keben", None)
    assert seen == {"products": str(box), "ws": str(ws)}
    assert os.environ["GUJI_PRODUCTS_DIR"] == str(box) and os.environ["GUJI_WORKSPACE"] == "/elsewhere"
