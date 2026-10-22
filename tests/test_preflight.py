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
