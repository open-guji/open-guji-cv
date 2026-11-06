"""切点判官结果落盘复用（`seg.cut_select`，2026-11-05）：命中时与现算在调用方读的值（墨像素上的归属与置信）逐位相同。"""
import numpy as np

from open_guji_cv.seg import cut_select as CS


class _FakeJudge(CS.UNetJudge):
    def __init__(self):                      # 不加载权重：前向换成确定性的假网络
        self.fingerprint = "fake:f64"
        self.f64 = True
        self.calls = 0

    def _owner(self, win, th, cc):
        self.calls += 1
        W = (win < th).astype(np.uint8)
        rng = np.random.default_rng(int(win.sum()))
        pa = rng.random(win.shape)
        owner = np.where(W > 0, np.where(pa >= 0.5, 1, 2), 0).astype(np.uint8)
        return W, owner, np.abs(2 * pa - 1)


def _win(seed):
    rng = np.random.default_rng(seed)
    return np.where(rng.random((60, 50)) < 0.2, 0, 255).astype(np.uint8)


def test_disk_hit_equals_fresh_on_ink(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    win = _win(1)
    a = _FakeJudge()
    W0, o0, c0 = a.owner(win)
    assert a.calls == 1 and list((tmp_path / "cache" / "_judge").rglob("*.npz"))
    b = _FakeJudge()                         # 新进程（空的内存缓存）：从盘上取，不前向
    W1, o1, c1 = b.owner(win)
    assert b.calls == 0
    ink = W0 > 0
    assert np.array_equal(W0, W1) and np.array_equal(o0, o1)
    assert np.array_equal(c0[ink], c1[ink]) and c0.dtype == c1.dtype


def test_other_window_or_switch_off_recomputes(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    _FakeJudge().owner(_win(1))
    j = _FakeJudge()
    j.owner(_win(2))
    assert j.calls == 1
    monkeypatch.setenv("GUJI_JUDGE_CACHE", "0")
    k = _FakeJudge()
    k.owner(_win(1))
    assert k.calls == 1
