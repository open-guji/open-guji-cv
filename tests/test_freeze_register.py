# -*- coding: utf-8 -*-
"""ops/freeze_register.py（GUJI-694）：自造产物、假 R2、临时 git 仓，不碰真书与网络。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from open_guji_cv.core.cv_version import frozen_mismatch
from open_guji_cv.datastore import packs as PK
from open_guji_cv.ops import freeze as FZ
from open_guji_cv.ops import freeze_register as FR


def _products(tmp: Path) -> Path:
    root = tmp / "products"
    (root / "vol05" / "seed_admit").mkdir(parents=True)
    (root / "vol05" / "seed_admit" / "p0001.json").write_text('{"a": 1}', encoding="utf-8")
    (root / "vol05" / "seed_admit" / "_manifest.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "vol05" / "_prev").mkdir()
    (root / "vol05" / "_prev" / "old.json").write_text("x", encoding="utf-8")
    return root


def _repo(tmp: Path, *, push: bool = True) -> Path:
    origin, repo = tmp / "origin.git", tmp / "cv"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(repo), "config", k, v], check=True)
    (repo / "f.txt").write_text("1", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "c"], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(origin)], check=True)
    if push:
        subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "HEAD:refs/heads/main"], check=True)
        subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin"], check=True)
    return repo


def test_baseline_skips_prev_and_manifest(tmp_path):
    b = FR.products_baseline(_products(tmp_path), "vol05", "2026-10-23T00:00:00Z", {"version": "0.5.10"})
    assert list(b["files"]) == ["products/vol05/seed_admit/p0001.json"] and b["format"] == "guji-snap/1"
    # 与 compare_products 对得上：本机产物没动 → 全同
    cmp = FZ.compare_products(b, tmp_path / "products")
    assert cmp == {"same": 1, "changed": [], "missing": []}


def test_rewrite_yaml_keeps_other_lines():
    old = ("# 册 005\nid: vol05\ncv_version: \"0.4.0\"\nfreeze:\n  at: \"0.1.0\"\n  snapshot: snap/x\n\n"
           "pages:\n  - 1   # 注释留着\n")
    new = FR.rewrite_yaml(old, {"at": "1.0.0", "pack": "freeze-1.0.0-x"}, "0.5.10")
    assert "# 册 005" in new and "  - 1   # 注释留着" in new and "snapshot" not in new
    assert new.count("cv_version:") == 1 and 'cv_version: "0.5.10"' in new
    import yaml
    d = yaml.safe_load(new)
    assert d["freeze"] == {"at": "1.0.0", "pack": "freeze-1.0.0-x"} and d["pages"] == [1] and d["cv_version"] == "0.5.10"


def test_plan_refuses_unpushed_commit_and_bad_version(tmp_path):
    root = _products(tmp_path)
    p = FR.plan("vol05", "1.0", text_id="96mid1ogzk", ws_name="demo-ws", products_root=root,
                repo=_repo(tmp_path, push=False), now=1793000000)
    assert any("X.Y.Z" in x for x in p["problems"]) and any("远端" in x for x in p["problems"])


def test_plan_and_execute(tmp_path, monkeypatch):
    root = _products(tmp_path)
    repo = _repo(tmp_path)
    p = FR.plan("vol05", "1.0.0", text_id="96mid1ogzk", ws_name="demo-ws", products_root=root, repo=repo,
                now=1793000000, note="试")
    assert p["problems"] == []
    assert p["label"].startswith("freeze-1.0.0-") and p["record"]["tag"].startswith("freeze/96mid1ogzk-vol05-")
    puts, promoted = {}, []
    monkeypatch.setattr(PK, "push_products", lambda book, r, label, vers, note: {"name": f"products/demo-ws/{book}/{label}"})
    monkeypatch.setattr(PK, "_client", lambda: object())
    monkeypatch.setattr(PK, "_call", lambda src, m, key, data=None, **kw: puts.__setitem__(key, data))
    monkeypatch.setattr(PK, "promote", lambda book, label, note="", src=None: promoted.append(label))
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path / "feedback"))
    y = tmp_path / "vol05.yaml"
    y.write_text("id: vol05\n", encoding="utf-8")
    done = FR.execute(p, products_root=root, yaml_path=y, vers={"db_rev": "demo-ws@main:42"})
    assert promoted == [p["label"]] and done["tagged"] is None and done["files"] == 1
    base = json.loads(puts[f"products/demo-ws/vol05/{p['label']}/baseline.json"])
    assert "products/vol05/seed_admit/p0001.json" in base["files"]
    rec = json.loads((tmp_path / "feedback" / "lists" / "freeze" / "vol05.jsonl").read_text(encoding="utf-8"))
    assert rec["version"] == "1.0.0" and rec["db_rev"] == "demo-ws@main:42" and rec["snapshot_id"] == p["label"]
    import yaml
    d = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert d["freeze"]["pack"] == p["label"] and d["cv_version"] == d["freeze"]["cv_version"]


def test_load_baseline_from_pack_cache_and_guard(tmp_path):
    ws = tmp_path / "ws"
    cache = ws / ".freeze_cache" / "vol05" / "freeze-1.0.0-x.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"format": "guji-snap/1", "files": {}}), encoding="utf-8")
    book = SimpleNamespace(id="vol05", freeze={"pack": "freeze-1.0.0-x", "cv_commit": "a" * 40})
    assert FZ.is_frozen(book) and FZ.load_baseline(book, ws)["format"] == "guji-snap/1"
    # 冻结护栏也认 pack
    assert frozen_mismatch(book.freeze, installed_commit="b" * 40, installed_version="0.5.10")
    assert frozen_mismatch(book.freeze, installed_commit="a" * 40, installed_version="0.5.10") is None


def test_cli_plan_only(tmp_path, monkeypatch, capsys):
    from open_guji_cv import cli_freeze
    root = _products(tmp_path)
    monkeypatch.setattr(PK, "_ws_name", lambda: "demo-ws")
    monkeypatch.setattr("open_guji_cv.core.book._book_yaml_path", lambda b: tmp_path / f"{b}.yaml")
    monkeypatch.setattr(FR, "cv_state", lambda repo=None: {"version": "0.5.10", "commit": "c" * 40, "dirty": False, "on_remote": True})
    args = SimpleNamespace(book="vol05", version="1.0.0", text_id="96mid1ogzk", text_dir=None, root=str(root),
                           note=None, tag_via=None, execute=False, json=False)
    cli_freeze.cmd_freeze(args)
    out = capsys.readouterr().out
    assert "只出计划" in out and "freeze/96mid1ogzk-vol05-" in out
    with pytest.raises(SystemExit):
        cli_freeze.cmd_freeze(SimpleNamespace(**{**vars(args), "version": "1"}))
