# -*- coding: utf-8 -*-
"""任务库执行方：单上没带 GUJI_ACTOR 时缺省填执行方名字（GUJI_JOBS_WHO），单上带了的照旧（2026-11-04）。"""
from __future__ import annotations

from open_guji_cv.jobs import runner as R


def _job(spec):
    r = object.__new__(R.Job)
    r.spec, r.dry, r.ws, r.prep_override = spec, False, None, {}
    r.id, r.aid, r.dir = 1, 1, None
    return r


def test_default_actor_is_worker_name(monkeypatch):
    monkeypatch.delenv("GUJI_ACTOR", raising=False)
    monkeypatch.setenv("GUJI_JOBS_WHO", "worker-40")
    assert _job({"env": {}}).env()["GUJI_ACTOR"] == "worker-40"
    assert _job({}).env()["GUJI_ACTOR"] == "worker-40"


def test_job_actor_is_kept(monkeypatch):
    monkeypatch.delenv("GUJI_ACTOR", raising=False)
    monkeypatch.setenv("GUJI_JOBS_WHO", "worker-40")
    assert _job({"env": {"GUJI_ACTOR": "A31"}}).env()["GUJI_ACTOR"] == "A31"


def test_no_worker_name_no_default(monkeypatch):
    monkeypatch.delenv("GUJI_ACTOR", raising=False)
    monkeypatch.delenv("GUJI_JOBS_WHO", raising=False)
    assert "GUJI_ACTOR" not in _job({"env": {}}).env()
