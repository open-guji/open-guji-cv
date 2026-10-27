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
