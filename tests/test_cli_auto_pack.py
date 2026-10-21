"""`guji pipeline` 整册从头跑到尾时自动存产物包（sheldon 10-21）：何时存、何时不存。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from open_guji_cv import cli_v2

FULL = ["a", "b", "c"]


def _eng(tmp_path):
    return SimpleNamespace(book=SimpleNamespace(id="vol01"), store=SimpleNamespace(root=Path(tmp_path)))


def _setup(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli_v2, "cli_steps", lambda eng, f, t: list(FULL))
    import open_guji_cv.cli_products as CP
    import open_guji_cv.datastore.packs as PK
    monkeypatch.setattr(CP, "book_versions", lambda book, root: {"cv": "0", "cv_commit": None})
    monkeypatch.setattr(PK, "push_products",
                        lambda book, root, **kw: calls.append((book, kw)) or {"name": f"p/{book}/x", "bytes": 1})
    monkeypatch.setenv("GUJI_DATA_TOKEN", "t")
    monkeypatch.delenv("GUJI_AUTO_PACK", raising=False)
    return calls


def test_full_book_full_pipeline_packs(monkeypatch, tmp_path, capsys):
    calls = _setup(monkeypatch, tmp_path)
    cli_v2._auto_pack(SimpleNamespace(pages="all", no_pack=False), _eng(tmp_path), list(FULL))
    assert calls and calls[0][0] == "vol01" and calls[0][1]["change"] == "full"
    assert "已自动存包" in capsys.readouterr().out


def test_partial_runs_do_not_pack(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path)
    cli_v2._auto_pack(SimpleNamespace(pages="1-5", no_pack=False), _eng(tmp_path), list(FULL))
    cli_v2._auto_pack(SimpleNamespace(pages="all", no_pack=False), _eng(tmp_path), FULL[1:])
    cli_v2._auto_pack(SimpleNamespace(pages="all", no_pack=True), _eng(tmp_path), list(FULL))
    monkeypatch.setenv("GUJI_AUTO_PACK", "0")
    cli_v2._auto_pack(SimpleNamespace(pages="all", no_pack=False), _eng(tmp_path), list(FULL))
    assert calls == []


def test_no_token_or_failure_only_warns(monkeypatch, tmp_path, capsys):
    calls = _setup(monkeypatch, tmp_path)
    monkeypatch.delenv("GUJI_DATA_TOKEN")
    cli_v2._auto_pack(SimpleNamespace(pages="all", no_pack=False), _eng(tmp_path), list(FULL))
    assert calls == [] and "没自动存包" in capsys.readouterr().out
    monkeypatch.setenv("GUJI_DATA_TOKEN", "t")
    import open_guji_cv.datastore.packs as PK

    def boom(*a, **k):
        raise RuntimeError("403")
    monkeypatch.setattr(PK, "push_products", boom)
    cli_v2._auto_pack(SimpleNamespace(pages="all", no_pack=False), _eng(tmp_path), list(FULL))
    assert "自动存包失败" in capsys.readouterr().out
