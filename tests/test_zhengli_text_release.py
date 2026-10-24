# -*- coding: utf-8 -*-
"""scripts/zhengli/text_release.py（冲 1.0 锁输入、1.0 检查一条命令）：自造工作区，不连网。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "zhengli"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("zl_text_release", SCRIPTS / "text_release.py")
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)


def _ws(tmp_path):
    ws = tmp_path / "abc123-书"
    (ws / "books").mkdir(parents=True)
    (ws / "books" / "vol06.yaml").write_text("id: vol06\ncorpus: 14\nglyph_pin: 1\nreferences:\n  - file: ref.txt\n"
                                             "steps:\n  row_segment:\n    layout_prior: corpus/daizhige/layout.jsonl\n", encoding="utf-8")
    (ws / "corpus" / "daizhige").mkdir(parents=True)
    (ws / "corpus" / "ref.txt").write_text("甲乙", encoding="utf-8")
    (ws / "corpus" / "daizhige" / "layout.jsonl").write_text("{}\n", encoding="utf-8")
    (ws / "config" / "corpus-pack" / "v14").mkdir(parents=True)
    (ws / "config" / "corpus-pack" / "v14" / "m.json").write_text("{}", encoding="utf-8")
    (ws / "config" / "groups").mkdir(parents=True)
    (ws / "config" / "groups" / "freq.json").write_text("{}", encoding="utf-8")
    return ws


def test_pin_then_drift_kinds(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    fp = tr.fingerprint(ws, "vol06")
    assert fp["corpus"]["version"] == 14 and fp["layout"]["path"] == "corpus/daizhige/layout.jsonl" and fp["references"]["ref.txt"]
    assert tr.main(["check-pin", "--book", "vol06", "-w", str(ws)]) == 0           # 没 pin：不在冲 1.0
    assert tr.main(["pin", "--book", "vol06", "-w", str(ws), "--pack", "cv0.5.7-c14"]) == 0
    assert json.loads(tr.pin_path(ws, "vol06").read_text(encoding="utf-8"))["pack"] == "cv0.5.7-c14"
    assert tr.main(["check-pin", "--book", "vol06", "-w", str(ws)]) == 0
    (ws / "corpus" / "ref.txt").write_text("甲丙", encoding="utf-8")                 # 别处更新了参照本：共享
    assert tr.main(["check-pin", "--book", "vol06", "-w", str(ws)]) == 2
    y = ws / "books" / "vol06.yaml"
    y.write_text(y.read_text(encoding="utf-8") + "rare_ref: true\n", encoding="utf-8")   # 本册 yaml 变：本册
    assert tr.main(["check-pin", "--book", "vol06", "-w", str(ws)]) == 1
    out = capsys.readouterr().out
    assert "共享输入 references 变了" in out and "本册输入 yaml 变了" in out


def test_pin_refuses_repin_without_force(tmp_path, monkeypatch):
    import pytest
    ws = _ws(tmp_path)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    assert tr.main(["pin", "--book", "vol06", "-w", str(ws)]) == 0
    with pytest.raises(SystemExit, match="已经 pin 过"):
        tr.main(["pin", "--book", "vol06", "-w", str(ws)])
    assert tr.main(["pin", "--book", "vol06", "-w", str(ws), "--force", "--note", "重跑后重锁"]) == 0
