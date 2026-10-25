"""新册首跑存包后自动标 main（_auto_main_first）。"""
from open_guji_cv import cli_products as C


def test_first_run_formal_auto(monkeypatch):
    monkeypatch.setattr("open_guji_cv.datastore.client.is_exp_branch", lambda b: False)
    monkeypatch.setattr("open_guji_cv.core.workspace.active_branch", lambda: "main")
    assert C._auto_main_first(True, False, "0.5.17") is True


def test_not_first_run_or_flagged(monkeypatch):
    monkeypatch.setattr("open_guji_cv.datastore.client.is_exp_branch", lambda b: False)
    monkeypatch.setattr("open_guji_cv.core.workspace.active_branch", lambda: "main")
    assert C._auto_main_first(False, False, "0.5.17") is False
    assert C._auto_main_first(True, True, "0.5.17") is False


def test_informal_cv_or_exp_branch_not_auto(monkeypatch):
    monkeypatch.setattr("open_guji_cv.core.workspace.active_branch", lambda: "main")
    monkeypatch.setattr("open_guji_cv.datastore.client.is_exp_branch", lambda b: False)
    assert C._auto_main_first(True, False, "0.5.17.dev1+gabc") is False
    monkeypatch.setattr("open_guji_cv.datastore.client.is_exp_branch", lambda b: True)
    assert C._auto_main_first(True, False, "0.5.17") is False
