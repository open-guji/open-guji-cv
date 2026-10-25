"""`ops/preflight.py`（GUJI-654）：起跑前查这次要跑的步骤本机缺不缺依赖。用假引擎，不碰真书。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from open_guji_cv import cli_v2
from open_guji_cv.ops import preflight


def _eng(cut_judge="unet", shadow_veto=False):
    vals = {"row_segment": SimpleNamespace(cut_judge=cut_judge), "seed_admit": SimpleNamespace(shadow_veto=shadow_veto)}
    return SimpleNamespace(_params=lambda step: vals.get(step.spec.id, SimpleNamespace()))


def _no(monkeypatch, *mods):
    monkeypatch.setattr(preflight, "_have", lambda m: m not in mods)


def test_everything_present_is_silent(monkeypatch):
    monkeypatch.setattr(preflight, "_have", lambda m: True)
    monkeypatch.setattr(preflight.Path, "is_file", lambda self: True)
    assert preflight.check(_eng(shadow_veto=True), ["row_segment", "rare_candidates", "seed_admit"]) == []


def test_missing_torch_only_matters_for_steps_that_use_it(monkeypatch):
    _no(monkeypatch, "torch")
    assert preflight.check(_eng(), ["border_detect"]) == []                      # 只跑不用模型的步骤：不查
    msgs = preflight.check(_eng(), ["row_segment", "rare_candidates"])
    assert len(msgs) == 2 and "row_segment" in msgs[0] and "rare_candidates" in msgs[1]
    assert preflight.check(_eng(cut_judge="rule"), ["row_segment"]) == []        # 裁判关了就不要 torch


def test_shadow_veto_needs_joblib(monkeypatch):
    _no(monkeypatch, "joblib")
    assert preflight.check(_eng(shadow_veto=False), ["seed_admit"]) == []
    [m] = preflight.check(_eng(shadow_veto=True), ["seed_admit"])
    assert "shadow_veto" in m and "joblib" in m


def test_cli_refuses_with_exit_2_unless_allowed(monkeypatch, capsys):
    _no(monkeypatch, "torch")
    monkeypatch.delenv("GUJI_ALLOW_MISSING_DEPS", raising=False)
    with pytest.raises(SystemExit) as e:
        cli_v2._preflight_deps(_eng(), ["rare_candidates"])
    assert e.value.code == 2 and "拒跑" in capsys.readouterr().err
    cli_v2._preflight_deps(_eng(), ["rare_candidates"], allow=True)              # --allow-missing-deps：只提醒
    assert "放行" in capsys.readouterr().err
    monkeypatch.setenv("GUJI_ALLOW_MISSING_DEPS", "1")
    cli_v2._preflight_deps(_eng(), ["rare_candidates"])


def test_human_events_dir_missing_refuses(monkeypatch):
    """字形库有人裁、事件目录却不在：数据目录没指对，拒跑（A24 2026-10-25，vol06／vol10 沙箱实测丢人裁）。"""
    monkeypatch.setattr(preflight, "_have", lambda m: True)
    eng = SimpleNamespace(_params=lambda step: SimpleNamespace(use_human_verdicts=True, db_path="g.db", shadow_veto=False))
    monkeypatch.setattr(preflight, "_human_events_missing", lambda db: "事件目录却不在")
    assert preflight.check(eng, ["seed_admit"]) == ["事件目录却不在"]
    assert preflight.check(eng, ["glyph_match"]) == []
    monkeypatch.setattr(preflight, "_human_events_missing", lambda db: None)
    assert preflight.check(eng, ["seed_admit"]) == []


def test_human_events_missing_checks_dir_and_library(monkeypatch, tmp_path):
    import open_guji_cv.feedback.events as ev
    import open_guji_cv.steps.seed_admit as sa
    db = tmp_path / "glyph.db"
    db.write_bytes(b"")
    root = tmp_path / "feedback"
    monkeypatch.setattr(ev, "default_feedback_root", lambda: root)
    monkeypatch.setattr(sa, "_human_shapes", lambda p: {"b:1:1:1": "甲"})
    assert "事件目录" in preflight._human_events_missing(str(db))       # 有人裁、没事件目录
    (root / "events").mkdir(parents=True)
    assert preflight._human_events_missing(str(db)) is None             # 事件目录在
    (root / "events").rmdir()
    monkeypatch.setattr(sa, "_human_shapes", lambda p: {})
    assert preflight._human_events_missing(str(db)) is None             # 库里没人裁（新书）
    assert preflight._human_events_missing(str(tmp_path / "none.db")) is None
