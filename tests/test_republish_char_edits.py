"""republish.bump_book_text：文本线 0.x 且本章有标点／实体时，bump 前先 char_edits.py record（改字清单）。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "zhengli"))
import republish as rp  # noqa: E402


def _setup(tmp_path, monkeypatch, version, with_punct=True, rc_record=0):
    repo, d, exp = tmp_path / "bt", tmp_path / "bt" / "d", tmp_path / "exp"
    (repo / "scripts" / "book-text").mkdir(parents=True)
    (repo / "scripts" / "book-text" / "char_edits.py").write_text("")
    d.mkdir(), exp.mkdir()
    (d / "007.char.json").write_text(json.dumps({"version": version}))
    (exp / "007.char.json").write_text(json.dumps({"version": version}))
    if with_punct:
        (d / "007.punct.json").write_text("{}")
    calls = []

    def fake_run(cmd, **kw):
        calls.append([str(c) for c in cmd])
        rc = rc_record if "char_edits.py" in str(cmd[1]) else 0
        return type("P", (), {"returncode": rc})()

    monkeypatch.setattr(rp, "book_text_to_dev", lambda r: None)
    monkeypatch.setattr(rp, "book_text_dir", lambda r, t: d)
    monkeypatch.setattr(rp, "run", fake_run)
    monkeypatch.setattr(rp, "push_book_text_dev", lambda r: True)
    return repo, {"text_id": "t", "chapter": "007", "export_dir": str(exp)}, calls


def test_record_before_bump(tmp_path, monkeypatch):
    repo, plan, calls = _setup(tmp_path, monkeypatch, "0.3.0")
    rp.bump_book_text(repo, plan, "换产物", ref="007-r4")
    names = [c[1].rsplit("/", 1)[-1] for c in calls]
    assert names[0] == "char_edits.py" and names[1] == "bump_original.py"
    assert "git:HEAD" in calls[0] and "007-r4" in calls[0]


def test_insert_delete_stops(tmp_path, monkeypatch):
    repo, plan, calls = _setup(tmp_path, monkeypatch, "0.3.0", rc_record=2)
    with pytest.raises(SystemExit, match="增删字"):
        rp.bump_book_text(repo, plan, "换产物")
    assert len(calls) == 1                                   # 没往下 bump


@pytest.mark.parametrize("version,with_punct", [("1.0.0", True), ("0.3.0", False)])
def test_no_record(tmp_path, monkeypatch, version, with_punct):
    repo, plan, calls = _setup(tmp_path, monkeypatch, version, with_punct)
    rp.bump_book_text(repo, plan, "换产物")
    assert not any("char_edits.py" in c[1] for c in calls)
