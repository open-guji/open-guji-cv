# -*- coding: utf-8 -*-
"""任务库准备改值走运行覆盖（2026-11-03）：rerun_prep.sh 报 OVERRIDE=…，执行方带到 pipeline 的 --override 和各条 guji 命令的环境里；
CLI 的 --override 叠在环境里已有的覆盖上。"""
from __future__ import annotations

import json

import pytest

from open_guji_cv.core import book_config as BC
from open_guji_cv.jobs import runner as R


def _runner(tmp_path, monkeypatch, spec):
    monkeypatch.setattr(R, "HOME", tmp_path)
    r = object.__new__(R.Job)
    r.spec, r.dry, r.ws, r.prep_override = spec, False, None, {}
    r.id, r.aid, r.dir = 1, 1, tmp_path
    r.ev = lambda *a, **k: None
    r.db = lambda *a, **k: None
    return r


SPEC = {"book": "vol03", "cv": "abc1234", "ws_glob": "96mid1ogzk-*", "pipeline": "keben_body_v2", "pages": "all",
        "steps": {"from": None, "to": None}, "force": False, "book_overrides": {"corpus": 23}}


def test_prep_override_reaches_pipeline_and_env(tmp_path, monkeypatch):
    r = _runner(tmp_path, monkeypatch, dict(SPEC))
    out = f'WS={tmp_path}\n' + 'OVERRIDE={"corpus": 23, "cv_version": "0.6.1"}\n'
    monkeypatch.setattr(r, "sh", lambda argv, **k: out, raising=False)
    r.prep()
    assert r.prep_override == {"corpus": 23, "cv_version": "0.6.1"}
    assert json.loads(r.env()["GUJI_BOOK_OVERRIDE"]) == {"corpus": 23, "cv_version": "0.6.1"}
    seen = []
    monkeypatch.setattr(r, "guji", lambda *a, **k: seen.append(a) or "", raising=False)
    r.run_pipeline()
    args = seen[0]
    ov = json.loads(args[args.index("--override") + 1])
    assert ov == {"corpus": 23, "cv_version": "0.6.1"}      # 自己合好：旧版 cv 的 --override 会顶掉环境变量
    # 同一会话同配置再备：从标记里取回覆盖
    r2 = _runner(tmp_path, monkeypatch, dict(SPEC))
    r2.prep()
    assert r2.prep_override == {"corpus": 23, "cv_version": "0.6.1"}


def test_old_tag_without_override_line(tmp_path, monkeypatch):
    r = _runner(tmp_path, monkeypatch, dict(SPEC, book_overrides={}))
    monkeypatch.setattr(r, "sh", lambda argv, **k: "WS=/w/x\n", raising=False)
    r.prep()
    monkeypatch.delenv(BC.OVERRIDE_ENV, raising=False)
    assert r.prep_override == {} and BC.OVERRIDE_ENV not in r.env()


def test_cli_override_merges_with_env(monkeypatch):
    monkeypatch.setenv(BC.OVERRIDE_ENV, json.dumps({"cv_version": "0.6.1", "corpus": 23,
                                                   "params": {"seed_admit": {"a": 1, "b": 2}}}))
    got = json.loads(BC.merge_override_env(json.dumps({"corpus": 24, "params": {"seed_admit": {"b": 3}}})))
    assert got == {"cv_version": "0.6.1", "corpus": 24, "params": {"seed_admit": {"a": 1, "b": 3}}}


def test_cli_override_without_env(monkeypatch):
    monkeypatch.delenv(BC.OVERRIDE_ENV, raising=False)
    assert json.loads(BC.merge_override_env('{"corpus": 5}')) == {"corpus": 5}
    with pytest.raises(BC.BookConfigError):
        BC.merge_override_env("[1]")
