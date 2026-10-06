"""真刻例原型档内存缓存留两档（overview#429）：基集 / 升级档交替查不再互相挤掉重建。

不装 torch、不读 checkpoint：`load_real_exemplars` 换成计数桩（返回空池，走「没有原型」
那条路），只验缓存命中与淘汰。"""
from __future__ import annotations

from open_guji_cv.clustering import cnn_candidates as cc


def _bare(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(cc, "load_real_exemplars", lambda sp, cs: calls.append(cs) or {})
    inst = cc.CnnCandidates.__new__(cc.CnnCandidates)
    inst._real_slots = []
    inst._ensure = lambda: True
    return inst, calls


def test_base_and_escalate_alternate_without_rebuild(monkeypatch):
    inst, calls = _bare(monkeypatch)
    base, esc = tuple("天地玄黃"), tuple("𠀀𠀁")
    for cs in (base, esc, base, esc, base):
        inst._real_index(cs, list(cs), specs=("s",))
    assert calls == [base, esc]                         # 两档各建一次


def test_third_charset_evicts_least_recent_and_none_clears(monkeypatch):
    inst, calls = _bare(monkeypatch)
    a, b, c = tuple("甲"), tuple("乙"), tuple("丙")
    for cs in (a, b, a, c, a, b):                       # c 进来挤掉最久未用的 b；a 一直在
        inst._real_index(cs, list(cs), specs=("s",))
    assert calls == [a, b, c, b]
    inst._real_cs = None                                # 测试里清缓存的老写法仍然有效
    inst._real_index(a, list(a), specs=("s",))
    assert calls[-1] == a and len(inst._real_slots) == 1
