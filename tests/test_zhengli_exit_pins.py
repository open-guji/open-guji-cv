"""粗校出口报告的钉版提示（GUJI-656）：collect_exit._pins 只报没钉的项，exit_report 单列一行、不挡出口。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ZL = Path(__file__).resolve().parents[1] / "scripts" / "zhengli"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ZL / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pins_reports_unpinned(monkeypatch):
    ce = _load("collect_exit")
    import open_guji_cv.core.book as B
    monkeypatch.setattr(B, "load_book", lambda book: SimpleNamespace(cv_version="0.4.7", corpus=6, glyph_pin=None))
    p = ce._pins("vol04")
    assert p["corpus"] == 6 and p["warn"] == ["没钉 glyph_pin"]


def test_pins_unreadable_book_is_warn_not_crash(monkeypatch):
    ce = _load("collect_exit")
    import open_guji_cv.core.book as B

    def boom(book):
        raise FileNotFoundError("no yaml")
    monkeypatch.setattr(B, "load_book", boom)
    assert ce._pins("vol99")["warn"][0].startswith("读不到册配置")


def _items():
    ok = {"result": "PASS", "number": "n", "cmd": "c", "attach": ""}
    return {"R1": ok, "R2": ok, "R3": {"result": "REPORT", "number": "1%", "reason": "r", "cmd": "c"}, "R4": ok, "R5": ok}


def test_report_shows_pins_but_does_not_block(tmp_path, capsys):
    er = _load("exit_report")
    f = tmp_path / "in.json"
    f.write_text(json.dumps({"book": "vol04", "cv_version": "0.4.7", "generated": "x", "items": _items(),
                             "pins": {"cv_version": "0.4.7", "corpus": 6, "glyph_pin": None,
                                      "warn": ["没钉 glyph_pin"]}}, ensure_ascii=False), encoding="utf-8")
    assert er.main(str(f)) == 0
    out = capsys.readouterr().out
    assert "钉版：cv_version=0.4.7、corpus=6；⚠ 没钉 glyph_pin" in out and "总判：可出 0.1.0" in out


def test_report_without_pins_unchanged(tmp_path, capsys):
    er = _load("exit_report")
    f = tmp_path / "in.json"
    f.write_text(json.dumps({"book": "vol04", "cv_version": "0.4.7", "generated": "x", "items": _items()}),
                 encoding="utf-8")
    assert er.main(str(f)) == 0
    assert "钉版" not in capsys.readouterr().out
