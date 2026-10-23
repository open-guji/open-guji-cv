"""_materialize：读的过程中工作区有新写入导致还原不一致时重读，没有新写入时照抛（10-23 A30 db sync 撞上）。"""

from __future__ import annotations

import pytest

from open_guji_cv.datastore import materialize as mat_mod
from open_guji_cv.datastore import workcopy
from open_guji_cv.datastore.materialize import MaterializeError


class _Src:
    def __init__(self, revs, changed=True):
        self.revs = list(revs)
        self.changed = changed

    def status(self):
        return self.revs.pop(0) if len(self.revs) > 1 else self.revs[0]

    def changes_since(self, ws, rev, limit=1):
        return 1 if self.changed else 0


def test_retries_when_write_happened_during_read(monkeypatch, tmp_path):
    calls = []

    def fake(src, ws, dest, prefixes, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise MaterializeError("admissions.jsonl: 库里有超出 n_lines 的行 [5]")
        return {"files": 1}

    monkeypatch.setattr(mat_mod, "materialize", fake)
    rev, stats = workcopy._materialize(_Src([10, 11, 11, 11]), "ws", tmp_path, None, "main")
    assert len(calls) == 2 and rev == 11 and stats == {"files": 1}


def test_raises_when_no_write_during_read(monkeypatch, tmp_path):
    def fake(src, ws, dest, prefixes, **kw):
        raise MaterializeError("真不一致")

    monkeypatch.setattr(mat_mod, "materialize", fake)
    with pytest.raises(MaterializeError):
        workcopy._materialize(_Src([10], changed=False), "ws", tmp_path, None, "main")
