"""生僻字面板找不到识别权重文件要报错，不能悄悄返回少一路的候选（A23，2026-10-23）。"""
from __future__ import annotations

import pytest

from open_guji_cv.clustering import cnn_candidates as cc


def test_missing_checkpoint_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("GUJI_ALLOW_MISSING_DEPS", raising=False)
    cnn = cc.CnnCandidates(ckpt=tmp_path / "nope.pt")
    with pytest.raises(cc.CnnCheckpointMissing, match="缺识别权重"):
        cc.require_checkpoint(cnn)


def test_allow_missing_deps_env_lets_it_through(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_ALLOW_MISSING_DEPS", "1")
    cc.require_checkpoint(cc.CnnCandidates(ckpt=tmp_path / "nope.pt"))


def test_existing_checkpoint_passes(tmp_path, monkeypatch):
    monkeypatch.delenv("GUJI_ALLOW_MISSING_DEPS", raising=False)
    f = tmp_path / "best.pt"
    f.write_bytes(b"x")
    cc.require_checkpoint(cc.CnnCandidates(ckpt=f))
