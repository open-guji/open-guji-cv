# -*- coding: utf-8 -*-
"""scripts/zhengli/sprite_pub.py 与 republish.py add-sprites（GUJI-675）：自造原图／cord／待审单，上传换成桩。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "zhengli"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"zl_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sp = _load("sprite_pub")
rp = _load("republish")


def _sheet(dir_: Path, name: str, color: int) -> bytes:
    Image.new("L", (96, 96), color).save(dir_ / name, "WEBP", quality=80)
    return (dir_ / name).read_bytes()


def test_attach_renames_by_hash_and_rewrites_refs(tmp_path):
    d = tmp_path / "sprites"
    d.mkdir()
    raw = _sheet(d, "p0003.webp", 10)
    alt = _sheet(d, "alt-004.webp", 200)
    (d / "assets.json").write_text(json.dumps({"files": [{"name": "p0003.webp"}, {"name": "alt-004.webp"}]}), encoding="utf-8")
    doc = {"rev": "004-r6", "cells": [
        {"cell": "1:1:1", "img": {"s": "p0003.webp", "x": 0, "y": 0, "w": 96, "h": 96},
         "alt": [{"c": "己", "g": {"s": "alt-004.webp", "x": 0, "y": 0, "w": 96, "h": 96}}, {"c": "已"}]}]}
    new, entries = sp.attach(doc, d)
    n_img = f"p0003.{hashlib.sha256(raw).hexdigest()[:8]}.webp"
    n_alt = f"alt-004.{hashlib.sha256(alt).hexdigest()[:8]}.webp"
    c = new["cells"][0]
    assert c["img"]["s"] == n_img and c["alt"][0]["g"]["s"] == n_alt and c["alt"][1] == {"c": "已"}
    assert [e["name"] for e in entries] == sorted([n_img, n_alt]) and new["sprites"] == entries
    e = next(x for x in entries if x["name"] == n_img)
    assert e == {"name": n_img, "sha256": hashlib.sha256(raw).hexdigest(), "md5": hashlib.md5(raw).hexdigest(), "bytes": len(raw)}
    assert (d / "pub" / n_img).read_bytes() == raw and doc["cells"][0]["img"]["s"] == "p0003.webp"   # 原 doc 不动


def test_upload_fails_loudly_when_a_sheet_is_missing(tmp_path, monkeypatch):
    import open_guji_cv.datastore.r2 as r2
    monkeypatch.setattr(r2, "upload_files", lambda imgs, bucket, ext: {"uploaded": 1, "put_403": 1})
    with pytest.raises(RuntimeError, match="没传完"):
        sp.upload([{"name": "a.webp", "sha256": "0" * 64}], tmp_path)
    monkeypatch.setattr(r2, "upload_files", lambda imgs, bucket, ext: {"uploaded": 1, "exists": 1})
    assert sp.upload([{"name": "a.webp", "sha256": "0" * 64}], tmp_path)["exists"] == 1


def _ws(tmp_path, monkeypatch):
    ws = tmp_path / "abc123-书"
    raw = tmp_path / "raw-vol06"
    raw.mkdir(parents=True)
    monkeypatch.setattr(rp, "raw_dir", lambda ws_, book: raw)       # 原图目录在工作区里，测试不去拼那个路径
    im = Image.new("L", (200, 300), 255)
    im.paste(0, (20, 20, 40, 40))
    im.save(raw / "1.png")
    export = ws / "reports" / "vol06" / "_export"
    export.mkdir(parents=True)
    boxes = ([10, 10, 40, 40], [10, 60, 40, 40])
    cord = {"pages": [{"page": 1, "image": {"width": 200, "height": 300},
                       "cells": [{"a": "1:1:1", "box": boxes[0]}, {"a": "1:1:2", "box": boxes[1]}]}]}
    (export / "006.cord.json").write_text(json.dumps(cord), encoding="utf-8")
    online = ws / "feedback" / "lists" / "proofing" / "abc123" / "006.pending.json"
    online.parent.mkdir(parents=True)
    online.write_text(json.dumps({"rev": "006-r3", "cells": [
        {"cell": "1:1:1", "review": "pending", "img": {"s": "p0001.webp", "x": 0, "y": 0, "w": 96, "h": 96}},
        {"cell": "1:1:2", "review": "pending", "img": {"s": "p0001.webp", "x": 96, "y": 0, "w": 96, "h": 96}}]}), encoding="utf-8")
    return ws, export, online


def test_add_sprites_rebuilds_uploads_and_patches_in_place(tmp_path, monkeypatch):
    ws, export, online = _ws(tmp_path, monkeypatch)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    sent = []
    monkeypatch.setattr(rp.sprite_pub, "upload", lambda entries, pub_dir, bucket="main": sent.append((entries, pub_dir)) or {"uploaded": len(entries)})
    before = json.loads(online.read_text(encoding="utf-8"))
    args = ["add-sprites", "--book", "vol06", "-w", str(ws), "--export-dir", str(export)]
    assert rp.main(args) == 0
    assert json.loads(online.read_text(encoding="utf-8")) == before and not sent               # 不给 --yes 不传不写
    assert rp.main(args + ["--yes"]) == 0
    after = json.loads(online.read_text(encoding="utf-8"))
    [entry] = after["sprites"]
    assert entry["name"].startswith("p0001.") and entry["name"].endswith(".webp")
    assert [c["img"]["s"] for c in after["cells"]] == [entry["name"]] * 2 and after["rev"] == "006-r3"
    assert sent and sent[0][0] == after["sprites"]
    assert rp.main(args + ["--yes"]) == 0 and len(sent) == 1                                    # 已有 sprites[] 不再动


def test_add_sprites_refuses_when_coordinates_differ(tmp_path, monkeypatch):
    ws, export, online = _ws(tmp_path, monkeypatch)
    cord = json.loads((export / "006.cord.json").read_text(encoding="utf-8"))
    cord["pages"][0]["cells"].reverse()                                                         # 格序变了，坐标就对不上
    (export / "006.cord.json").write_text(json.dumps(cord), encoding="utf-8")
    online.write_text(online.read_text(encoding="utf-8").replace('"x": 96', '"x": 192'), encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    with pytest.raises(SystemExit, match="坐标"):
        rp.main(["add-sprites", "--book", "vol06", "-w", str(ws), "--export-dir", str(export), "--yes"])


def test_missing_lists_refs_not_in_sprites():
    doc = {"cells": [{"cell": "1:1:1", "img": {"s": "p0001.ab.webp"},
                      "alt": [{"c": "己", "g": {"s": "alt-006.webp"}}, {"c": "已"}]}],
           "sprites": [{"name": "p0001.ab.webp"}]}
    assert sp.refs(doc) == {"p0001.ab.webp", "alt-006.webp"}
    assert sp.missing(doc) == ["alt-006.webp"]
    assert sp.missing({"cells": [{"cell": "1:1:1"}]}) == []


def test_push_gate_stops_on_unregistered_sprites():
    import argparse
    doc = {"cells": [{"cell": "1:1:1", "alt": [{"c": "己", "g": {"s": "alt-006.webp"}}]}], "sprites": []}
    with pytest.raises(SystemExit, match="alt-006.webp"):
        rp.sprites_gate(doc, argparse.Namespace(ack_missing_sprites=False))
    rp.sprites_gate(doc, argparse.Namespace(ack_missing_sprites=True))                          # 明说照推才放


def test_add_sprites_also_rebuilds_alt_sheet(tmp_path, monkeypatch):
    """线上单已有 sprites[]、相似字图却没登记（册 004–007）：add-sprites 连 alt 图一起重建、登记。"""
    ws, export, online = _ws(tmp_path, monkeypatch)
    doc = json.loads(online.read_text(encoding="utf-8"))
    doc["cells"][0]["alt"] = [{"c": "己", "g": {"s": "alt-006.webp", "x": 0, "y": 0, "w": 96, "h": 96}}]
    doc["sprites"] = [{"name": "p0001.webp"}]
    online.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    real_run = rp.run

    def fake_run(cmd, **kw):                         # alt_build 要字体，换成桩：出一张 alt 图、追加进 assets.json
        if "alt_build.py" not in str(cmd[1]):
            return real_run(cmd, **kw)
        import subprocess
        out = Path(cmd[cmd.index("--out") + 1])
        _sheet(out, "alt-006.webp", 128)
        man = json.loads((out / "assets.json").read_text(encoding="utf-8"))
        man["files"].append({"name": "alt-006.webp"})
        (out / "assets.json").write_text(json.dumps(man), encoding="utf-8")
        pend = json.loads(Path(cmd[cmd.index("--pending") + 1]).read_text(encoding="utf-8"))
        (out / "pending.with-alt.json").write_text(json.dumps(pend), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(rp, "run", fake_run)
    monkeypatch.setattr(rp.sprite_pub, "upload", lambda entries, pub_dir, bucket="main": {"uploaded": len(entries)})
    assert rp.main(["add-sprites", "--book", "vol06", "-w", str(ws), "--export-dir", str(export), "--yes"]) == 0
    after = json.loads(online.read_text(encoding="utf-8"))
    names = {e["name"] for e in after["sprites"]}
    assert any(n.startswith("alt-006.") for n in names) and any(n.startswith("p0001.") for n in names)
    assert sp.missing(after) == []


def test_add_sprites_accepts_hashed_names_on_online_doc(tmp_path, monkeypatch):
    """线上单已经是哈希名（册 006–010：p0001.<sha8>.webp），重建出来是 p0001.webp：坐标一样就该放行，不按文件名拒。"""
    ws, export, online = _ws(tmp_path, monkeypatch)
    doc = json.loads(online.read_text(encoding="utf-8"))
    for c in doc["cells"]:
        c["img"]["s"] = "p0001.0123abcd.webp"
    doc["cells"][0]["alt"] = [{"c": "己", "g": {"s": "alt-006.webp", "x": 0, "y": 0, "w": 96, "h": 96}}]
    doc["sprites"] = [{"name": "p0001.0123abcd.webp"}]
    online.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    real_run = rp.run

    def fake_run(cmd, **kw):
        if "alt_build.py" not in str(cmd[1]):
            return real_run(cmd, **kw)
        import subprocess
        out = Path(cmd[cmd.index("--out") + 1])
        _sheet(out, "alt-006.webp", 128)
        man = json.loads((out / "assets.json").read_text(encoding="utf-8"))
        man["files"].append({"name": "alt-006.webp"})
        (out / "assets.json").write_text(json.dumps(man), encoding="utf-8")
        pend = json.loads(Path(cmd[cmd.index("--pending") + 1]).read_text(encoding="utf-8"))
        (out / "pending.with-alt.json").write_text(json.dumps(pend), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(rp, "run", fake_run)
    monkeypatch.setattr(rp.sprite_pub, "upload", lambda entries, pub_dir, bucket="main": {"uploaded": len(entries)})
    assert rp.main(["add-sprites", "--book", "vol06", "-w", str(ws), "--export-dir", str(export), "--yes"]) == 0
    after = json.loads(online.read_text(encoding="utf-8"))
    assert sp.missing(after) == [] and after["rev"] == "006-r3"


def test_add_sprites_still_refuses_other_sheet_name(tmp_path, monkeypatch):
    """去掉哈希后页名不同（p0002 对 p0001）仍算对不上。"""
    ws, export, online = _ws(tmp_path, monkeypatch)
    online.write_text(online.read_text(encoding="utf-8").replace("p0001.webp", "p0002.0123abcd.webp"), encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    with pytest.raises(SystemExit, match="坐标"):
        rp.main(["add-sprites", "--book", "vol06", "-w", str(ws), "--export-dir", str(export), "--yes"])


def test_unhashed_strips_only_content_hash():
    assert sp.unhashed("p0001.0123abcd.webp") == "p0001.webp"
    assert sp.unhashed("p0001.webp") == "p0001.webp"
    assert sp.unhashed("alt-006.deadbeef.webp") == "alt-006.webp"
