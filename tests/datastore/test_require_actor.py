"""推库必须带操作人（2026-11-04 殿本账本事故：actor 为空查不出来源）。"""
import pytest

from open_guji_cv.cli_db import require_actor


def test_actor_from_env(monkeypatch):
    monkeypatch.setenv("GUJI_ACTOR", "A23")
    assert require_actor() == "A23"


def test_missing_actor_refused(monkeypatch):
    monkeypatch.delenv("GUJI_ACTOR", raising=False)
    monkeypatch.setenv("USER", "root")
    with pytest.raises(SystemExit):
        require_actor()
    monkeypatch.delenv("USER")
    with pytest.raises(SystemExit):
        require_actor()


def test_dry_run_and_user_fallback(monkeypatch):
    monkeypatch.delenv("GUJI_ACTOR", raising=False)
    monkeypatch.delenv("USER", raising=False)
    assert require_actor(dry_run=True) is None
    monkeypatch.setenv("USER", "ubuntu")
    assert require_actor() == "ubuntu"
