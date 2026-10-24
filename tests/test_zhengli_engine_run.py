"""scripts/zhengli/engine_run.py：旧引擎读事件时跳过不认的种类，不许 compact。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import open_guji_cv.feedback.events as ev
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("engine_run", ROOT / "scripts/zhengli/engine_run.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _confirm(seq):
    return make_event("b", seq, "confirm",
                      EventTarget(step="seed_admit", unit="cell", key=f"vol06:3:1:{seq}", book="vol06",
                                  page=3, col=1, slot=seq),
                      {"v": "confirm", "shape": "欽"}, source_format="server")


def test_skips_unknown_kind_and_blocks_compact(tmp_path, monkeypatch):
    # 打补丁前先登记原方法，测完由 monkeypatch 还原
    monkeypatch.setattr(ev.EventLog, "read", ev.EventLog.read)
    monkeypatch.setattr(ev.EventLog, "compact", ev.EventLog.compact)
    log = EventLog(tmp_path)
    log.append([_confirm(1), _confirm(2)])
    path = log.batch_path("b")
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    row.update(kind="future_kind_xyz", seq=3, id="evt_b_000003")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with pytest.raises(Exception):          # 原样读：新种类拒收
        EventLog(tmp_path).read("b")

    skipped = _mod().patch_events()
    got = EventLog(tmp_path).read("b")
    assert [e.seq for e in got] == [1, 2]
    assert skipped == {"future_kind_xyz": 1}
    with pytest.raises(RuntimeError):
        EventLog(tmp_path).compact("b")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3   # 文件没被改写
