# -*- coding: utf-8 -*-
"""ls 上失败单的原因一行：失败、拦下、取消的显示 error；排队中的显示上次失败原因；成功的不显示。"""
from __future__ import annotations

import datetime as dt

import pytest

from open_guji_cv.jobs import cli as C


def _job(status: str, error: str | None, **kw) -> dict:
    j = {"id": 7, "status": status, "kind": "rerun", "book": "vol10", "spec": {"kind": "rerun", "book": "vol10",
         "cv": "a" * 40, "cv_ref": "v0.5.31", "pipeline": "keben_body_v2", "steps": {"from": None, "to": None},
         "pages": "all", "book_overrides": {}, "env": {}, "compare_to": None, "run": None},
         "priority": 100, "attempts": 1, "error": error, "submitted_by": "A31",
         "created_at": dt.datetime(2026, 10, 27, 22, 4, tzinfo=dt.timezone.utc), "run_after": None,
         "duplicate_of": None, "worker": "worker-3", "stage": None}
    j.update(kw)
    return j


@pytest.mark.parametrize("status", ["failed", "blocked", "cancelled"])
def test_failed_shows_reason_line(status):
    out = C._line(_job(status, "run：guji pipeline keben_body_v2 退出码 1：✗ glyph_match 返回码 1"))
    assert out.splitlines()[1].strip().startswith("↳ ")
    assert "glyph_match 返回码 1" in out.splitlines()[1]


def test_succeeded_has_no_reason_line():
    assert "↳" not in C._line(_job("succeeded", None))


def test_queued_after_env_failure_shows_last_reason():
    out = C._line(_job("queued", "环境：准备「拉库」段失败", run_after=None))
    assert "上次失败" in out and "环境：准备" in out


def test_long_reason_is_cut_to_one_line():
    out = C._line(_job("failed", "x" * 500))
    assert len(out.splitlines()[1]) < 200
    assert out.splitlines()[1].endswith("…")


def test_multiline_error_is_flattened():
    out = C._line(_job("failed", "第一行\n  第二行"))
    assert "第一行 第二行" in out
