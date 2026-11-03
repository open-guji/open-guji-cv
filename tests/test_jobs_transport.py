"""任务库连接选路：有 JOBSDB_TOKEN 走新机隧道，没有仍走 Neon；看板的中心库写仍走 Neon。"""
import pytest

from open_guji_cv.jobs import jobsdb, store


def test_disabled_without_token(monkeypatch):
    monkeypatch.delenv("JOBSDB_TOKEN", raising=False)
    assert jobsdb.enabled() is False


def test_enabled_with_token(monkeypatch):
    monkeypatch.setenv("JOBSDB_TOKEN", "  tok  ")
    assert jobsdb.enabled() is True


def test_connect_falls_back_to_neon(monkeypatch):
    monkeypatch.delenv("JOBSDB_TOKEN", raising=False)
    called = []
    monkeypatch.setattr(store, "connect_neon", lambda: called.append("neon") or "NEON")
    assert store.connect() == "NEON"
    assert called == ["neon"]


def test_connect_uses_jobsdb_when_token(monkeypatch):
    monkeypatch.setenv("JOBSDB_TOKEN", "tok")
    class C:
        autocommit = False
    monkeypatch.setattr(jobsdb, "connect", lambda: C())
    monkeypatch.setattr(store, "connect_neon", lambda: pytest.fail("不该走 Neon"))
    c = store.connect()
    assert c.autocommit is True


def test_pin_is_sha256_hex_after_normalise(monkeypatch):
    monkeypatch.delenv("JOBSDB_CERT_SHA256", raising=False)
    p = jobsdb._pin()
    assert len(p) == 64 and all(ch in "0123456789abcdef" for ch in p)
