"""执行方领单前的 ML 环境自检（_ml_env_gate）：缺依赖补装、拉不到权重就不领单。"""
import subprocess
from types import SimpleNamespace

from open_guji_cv.jobs import runner as R


def _fake(calls, probe_out, rc_install=0, rc_dl=0):
    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "uv":
            return SimpleNamespace(returncode=rc_install, stdout="", stderr="boom")
        if "find_spec" in cmd[2]:
            return SimpleNamespace(returncode=0, stdout=probe_out, stderr="")
        return SimpleNamespace(returncode=rc_dl, stdout="", stderr="offline")
    return run


def test_ok(monkeypatch):
    calls = []
    monkeypatch.delenv("GUJI_JOBS_SKIP_ML_CHECK", raising=False)
    monkeypatch.setattr(R, "_ml_ok_at", 0.0)
    monkeypatch.setattr(subprocess, "run", _fake(calls, ""))
    assert R._ml_env_gate(lambda *_: None) is None
    assert not any(c[0] == "uv" for c in calls)


def test_missing_installs(monkeypatch):
    calls = []
    monkeypatch.delenv("GUJI_JOBS_SKIP_ML_CHECK", raising=False)
    monkeypatch.setattr(R, "_ml_ok_at", 0.0)
    monkeypatch.setattr(subprocess, "run", _fake(calls, "transformers anthropic"))
    assert R._ml_env_gate(lambda *_: None) is None
    assert any(c[0] == "uv" and "transformers>=4.40" in c for c in calls)


def test_install_fail_blocks(monkeypatch):
    monkeypatch.delenv("GUJI_JOBS_SKIP_ML_CHECK", raising=False)
    monkeypatch.setattr(R, "_ml_ok_at", 0.0)
    monkeypatch.setattr(subprocess, "run", _fake([], "transformers", rc_install=1))
    assert "补装失败" in R._ml_env_gate(lambda *_: None)


def test_weights_fail_blocks(monkeypatch):
    monkeypatch.delenv("GUJI_JOBS_SKIP_ML_CHECK", raising=False)
    monkeypatch.setattr(R, "_ml_ok_at", 0.0)
    monkeypatch.setattr(subprocess, "run", _fake([], "", rc_dl=1))
    assert "权重" in R._ml_env_gate(lambda *_: None)
