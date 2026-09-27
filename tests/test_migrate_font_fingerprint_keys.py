# -*- coding: utf-8 -*-
"""`scripts/migrate_font_fingerprint_keys.py`：把旧（mtime）key 的 emb_*.npz
改名到新（内容）key，不重建、不改内容——2026-09-28，任务书-R-rare前向去重与
测试隔离追加项。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

_REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "migrate_font_fingerprint_keys", _REPO / "scripts" / "migrate_font_fingerprint_keys.py")
migrate_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate_mod)


@pytest.fixture
def _ckpt(cnn_test_ckpt) -> Path:
    return cnn_test_ckpt


def test_migrate_renames_old_key_file_without_touching_content(monkeypatch, _ckpt):
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.clustering import rare_panel as rare_panel_mod

    cs_base = tuple("一二三")
    monkeypatch.setattr(
        rare_panel_mod, "book_charsets",
        lambda book, corpus: (cs_base, (), {"base": "fake-base", "escalate": "fake-esc"}))
    monkeypatch.setattr("open_guji_cv.steps.align_ref.book_corpus", lambda book: None)

    # 造一个「旧 key」的假文件——内容随便（脚本只管改名，不解读内容）。
    old_key = migrate_mod._old_emb_index_key(_ckpt, cs_base, ())
    old_path = _ckpt.parent / f"emb_{old_key}.npz"
    np.savez(old_path, mat=np.zeros((3, 256), np.float32), chars=np.array(list(cs_base)))
    assert old_path.exists()

    new_key, new_path, _extra = cc.CnnCandidates(ckpt=_ckpt).emb_index_key(cs_base)
    assert new_key != old_key, "这条测试要验证的前提就是新旧 key 不同"
    assert not new_path.exists()

    report = migrate_mod.migrate_book("fakebook", _ckpt, dry_run=False)
    assert any("->" in line for line in report), report

    assert not old_path.exists(), "旧文件该被改名掉，不该还在"
    assert new_path.exists(), "新 key 的文件该出现"
    with np.load(new_path) as z:
        assert z["mat"].shape == (3, 256)
        assert list(z["chars"]) == list(cs_base)


def test_migrate_dry_run_does_not_rename(monkeypatch, _ckpt):
    from open_guji_cv.clustering import rare_panel as rare_panel_mod

    cs_base = tuple("十土王")
    monkeypatch.setattr(
        rare_panel_mod, "book_charsets",
        lambda book, corpus: (cs_base, (), {"base": "fake-base", "escalate": "fake-esc"}))
    monkeypatch.setattr("open_guji_cv.steps.align_ref.book_corpus", lambda book: None)

    old_key = migrate_mod._old_emb_index_key(_ckpt, cs_base, ())
    old_path = _ckpt.parent / f"emb_{old_key}.npz"
    np.savez(old_path, mat=np.zeros((3, 256), np.float32), chars=np.array(list(cs_base)))

    migrate_mod.migrate_book("fakebook2", _ckpt, dry_run=True)
    assert old_path.exists(), "--dry-run 不该真的改名"


def test_migrate_skips_when_old_file_absent(monkeypatch, _ckpt):
    from open_guji_cv.clustering import rare_panel as rare_panel_mod

    cs_base = tuple("人之")
    monkeypatch.setattr(
        rare_panel_mod, "book_charsets",
        lambda book, corpus: (cs_base, (), {"base": "fake-base", "escalate": "fake-esc"}))
    monkeypatch.setattr("open_guji_cv.steps.align_ref.book_corpus", lambda book: None)

    report = migrate_mod.migrate_book("fakebook3", _ckpt, dry_run=False)
    assert any("跳过" in line for line in report)
