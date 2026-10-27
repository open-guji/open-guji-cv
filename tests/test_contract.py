# -*- coding: utf-8 -*-
"""pipeline / manager 契约（doc/契约.md）：版本信息、manifest 新字段不进指纹。"""
import json

from open_guji_cv import api
from open_guji_cv.core import cv_version as cvv
from open_guji_cv.core.contract import CONTRACT_VERSION, MANAGER_VERSION_ENV
from open_guji_cv.products.manifest import ManifestEntry


def test_version_info_shape():
    info = api.version_info()
    assert info["contract_version"] == CONTRACT_VERSION
    assert "seed_admit" in info["steps"] and len(info["steps"]) >= 19


def test_manifest_fields_carry_contract_and_manager(monkeypatch):
    monkeypatch.setenv(MANAGER_VERSION_ENV, "m0.1.0")
    f = cvv.manifest_fields()
    assert f["contract_version"] == CONTRACT_VERSION and f["manager_version"] == "m0.1.0"
    monkeypatch.delenv(MANAGER_VERSION_ENV)
    assert cvv.manifest_fields()["manager_version"] is None


def test_old_manifest_line_without_new_fields_loads(tmp_path):
    from open_guji_cv.products.manifest import Manifest
    p = tmp_path / "_manifest.jsonl"
    p.write_text(json.dumps({"key": "p1", "fingerprint": "f"}) + "\n", encoding="utf-8")
    e = Manifest(p).get("p1")
    assert isinstance(e, ManifestEntry) and e.contract_version is None and e.manager_version is None


def test_cli_version_json(capsys):
    from open_guji_cv.cli_v2 import main
    main(["version", "--json"])
    assert json.loads(capsys.readouterr().out)["contract_version"] == CONTRACT_VERSION


def test_derived_fetch_prefers_local_dir_then_fetcher(tmp_path, monkeypatch):
    from open_guji_cv.core import derived
    src = tmp_path / "d" / "lm"
    src.mkdir(parents=True)
    (src / "x.json").write_text("{}")
    monkeypatch.setenv(derived.DIR_ENV, str(tmp_path / "d"))
    dest = tmp_path / "out" / "x.json"
    assert derived.fetch_derived("lm", "x.json", dest) and dest.read_text() == "{}"
    monkeypatch.delenv(derived.DIR_ENV)
    calls = []
    monkeypatch.setattr(derived, "FETCHER", lambda k, n, d: calls.append((k, n)) or True)
    assert derived.fetch_derived("lm", "y.json", tmp_path / "y") and calls == [("lm", "y.json")]
    monkeypatch.setattr(derived, "FETCHER", None)
    assert not derived.fetch_derived("lm", "z.json", tmp_path / "z")


def test_plugin_commands_merge_and_builtin_wins(monkeypatch):
    import argparse
    import types
    from open_guji_cv import cli_v2
    calls = []

    def add_new(sub):
        sub.add_parser("zz-plugin-cmd")

    def add_dup(sub):                      # 本仓自带 pipeline：不应被登记
        raise AssertionError("builtin 命令不该被插件覆盖")
    mod = types.SimpleNamespace(COMMANDS={"zz-plugin-cmd": (add_new, lambda a: calls.append(1)),
                                          "pipeline": (add_dup, lambda a: None)})
    ep = types.SimpleNamespace(name="t", load=lambda: mod)
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group=None: [ep])
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("pipeline")
    try:
        assert cli_v2.load_plugin_commands(sub) == ["zz-plugin-cmd"]
        assert cli_v2.COMMANDS_V2["zz-plugin-cmd"] is not None
    finally:
        cli_v2.COMMANDS_V2.pop("zz-plugin-cmd", None)
