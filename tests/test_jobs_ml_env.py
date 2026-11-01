"""执行方领单前的 ML 环境自检（_ml_env_gate）：缺依赖补装、拉不到权重或超时就不领单，并退避重试。"""
import sys

from open_guji_cv.jobs import runner as R


def _setup(monkeypatch, results):
    """results：按调用顺序依次返回的 (rc, out)；返回调用记录。"""
    calls = []
    it = iter(results)
    monkeypatch.delenv("GUJI_JOBS_SKIP_ML_CHECK", raising=False)
    monkeypatch.setattr(R, "_ml_ok_at", 0.0)
    monkeypatch.setattr(R, "_ml_fail", None)
    monkeypatch.setattr(R, "_find_uv", lambda: "uv")
    monkeypatch.setattr(R, "_run_bounded", lambda cmd, timeout, env=None: (calls.append(cmd), next(it))[1])
    return calls


def test_ok(monkeypatch):
    calls = _setup(monkeypatch, [(0, ""), (0, "/x")])
    assert R._ml_env_gate(lambda *_: None) is None
    assert not any(c[0] == "uv" for c in calls)


def test_missing_installs(monkeypatch):
    calls = _setup(monkeypatch, [(0, "transformers anthropic"), (0, ""), (0, "/x")])
    assert R._ml_env_gate(lambda *_: None) is None
    assert any(c[0] == "uv" and "transformers>=4.40" in c for c in calls)


def test_install_fail_blocks_and_backs_off(monkeypatch):
    calls = _setup(monkeypatch, [(0, "transformers"), (-9, "超过 600 秒被杀")])
    msg = R._ml_env_gate(lambda *_: None)
    assert "补装失败" in msg
    n = len(calls)
    assert R._ml_env_gate(lambda *_: None) == msg      # 退避期内不重跑
    assert len(calls) == n


def test_weights_fail_blocks(monkeypatch):
    _setup(monkeypatch, [(0, ""), (1, "offline")])
    assert "权重" in R._ml_env_gate(lambda *_: None)


def test_bounded_kills_on_timeout():
    rc, out = R._run_bounded([sys.executable, "-c", "import time;time.sleep(30)"], 1)
    assert rc == -9
