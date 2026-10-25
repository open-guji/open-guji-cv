# -*- coding: utf-8 -*-
"""GUJI-601：close-check 冻结基线模式、`guji archive fetch`。自造数据，不碰真书。"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from open_guji_cv.core.book import load_book
from open_guji_cv.ops import archive_fetch as AF
from open_guji_cv.ops import close_check as CC
from open_guji_cv.ops import freeze as FZ


# ── 冻结基线 ──────────────────────────────────────────────────────────
def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class FakeEng:
    def __init__(self, root: Path, book, reasons: dict | None = None):
        self.store = SimpleNamespace(root=root)
        self.book = book
        self._reasons = reasons or {}

    def status(self, pages=None, code_ok=False):
        return {"steps": {sid: {"counts": {"stale": sum(r.values()), "missing": 0, "failed": 0,
                                           "blocked": 0},
                                "stale_reasons": r}
                          for sid, r in self._reasons.items()}}


@pytest.fixture
def frozen(tmp_path):
    prod = tmp_path / "products"
    files = {"products/bk/seed_admit/p0001.json": b'{"a":1}',
             "products/bk/seed_admit/p0002.json": b'{"a":2}'}
    for rel, data in files.items():
        f = prod / rel[len("products/"):]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    man = {"format": "guji-snap/1", "created": "2026-10-17T20:00:00Z", "cv": {"commit": "abc"},
           "files": {rel: {"sha256": _sha(d)} for rel, d in files.items()}}
    (tmp_path / "base.json").write_text(json.dumps(man), encoding="utf-8")
    book = SimpleNamespace(id="bk", freeze={"at": "0.1.0", "cv_version": "0.2.0",
                                            "manifest": "base.json"})
    fb = tmp_path / "feedback" / "events"
    fb.mkdir(parents=True)
    rows = [
        {"ts": "2026-10-17T19:00:00Z", "kind": "confirm", "target": {"book": "bk"}, "payload": {}},  # 基线前
        {"ts": "2026-10-18T01:00:00Z", "kind": "confirm", "target": {"book": "bk"}, "payload": {}},
        {"ts": "2026-10-18T02:00:00Z", "kind": "vision_check", "target": {"book": "bk"}, "payload": {}},
        {"ts": "2026-10-18T02:00:00Z", "kind": "confirm", "target": {"book": "other"}, "payload": {}},
    ]
    (fb / "b.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return tmp_path, prod, book


def test_book_yaml_freeze(tmp_path):
    (tmp_path / "v.yaml").write_text('id: v\ntitle: t\nraw_dir: raw\nfreeze:\n  at: "0.1.0"\n'
                                     '  snapshot: snap/ws/v/20261017T1243\n', encoding="utf-8")
    b = load_book("v", books_dir=tmp_path)
    assert FZ.is_frozen(b) and b.freeze["at"] == "0.1.0"
    (tmp_path / "d.yaml").write_text("id: d\ntitle: t\nraw_dir: raw\n", encoding="utf-8")
    assert not FZ.is_frozen(load_book("d", books_dir=tmp_path))


def test_frozen_passes_when_only_code_or_library_changed(frozen):
    ws, prod, book = frozen
    # cv 升版、人裁进库让 seed_admit 过期：冻结册不报
    eng = FakeEng(prod, book, {"seed_admit": {"代码或版本变了": 3}})
    it = FZ.fresh_frozen(eng, [1, 2], ws, feedback_root=ws / "feedback")
    assert it["status"] == CC.PASS, it
    assert it["data"]["new_human_events"] == 1           # 只算基线后、本册、算人裁的
    assert it["data"]["stale_not_counted"] == 3
    assert "基线后新人裁 1 条" in it["detail"]


def test_frozen_params_alarm_unclear_listed(frozen):
    ws, prod, book = frozen
    # 规矩表：参数变（含册 yaml 的 params:）要报警
    it = FZ.fresh_frozen(FakeEng(prod, book, {"seed_admit": {"参数变了": 1}}), [1, 2], ws,
                         feedback_root=ws / "feedback")
    assert it["status"] == CC.FAIL and it["data"]["config_changed"] == {"seed_admit": 1}
    # 旧条目分不清代码还是册配置：单列请人核，不判失败
    it = FZ.fresh_frozen(FakeEng(prod, book, {"seed_admit": {"代码或册配置变了（period_prior；旧条目没记册配置原值）": 2}}),
                         [1, 2], ws, feedback_root=ws / "feedback")
    assert it["status"] == CC.PASS and it["data"]["unclear_code_or_config"] == {"seed_admit": 2}
    assert "请人核" in it["detail"]
    # 只是共享输入（格位表、证人）被别处更新：单列，不报警（复盘 I）
    it = FZ.fresh_frozen(FakeEng(prod, book, {"row_segment": {"参数变了：layout_fingerprint": 3},
                                              "seed_admit": {"参数变了：witness_fingerprint、layout_fingerprint": 1}}),
                         [1, 2], ws, feedback_root=ws / "feedback")
    assert it["status"] == CC.PASS and it["data"]["config_changed"] is None
    assert it["data"]["shared_inputs"] == {"layout_fingerprint": 4, "witness_fingerprint": 1}
    assert "共享输入被别处更新" in it["detail"]


def test_frozen_fails_when_product_changed_or_missing(frozen):
    ws, prod, book = frozen
    (prod / "bk/seed_admit/p0001.json").write_bytes(b'{"a":9}')
    (prod / "bk/seed_admit/p0002.json").unlink()
    it = FZ.fresh_frozen(FakeEng(prod, book), [1, 2], ws, feedback_root=ws / "feedback")
    assert it["status"] == CC.FAIL
    assert it["data"]["changed"] == ["products/bk/seed_admit/p0001.json"]
    assert it["data"]["missing"] == ["products/bk/seed_admit/p0002.json"]


def test_frozen_fails_when_book_config_changed(frozen):
    ws, prod, book = frozen
    eng = FakeEng(prod, book, {"border_detect": {"册配置 period_prior 180→204": 4}})
    it = FZ.fresh_frozen(eng, [1], ws, feedback_root=ws / "feedback")
    assert it["status"] == CC.FAIL and it["data"]["config_changed"] == {"border_detect": 4}


def test_close_check_routes_frozen_and_draft(frozen, monkeypatch):
    ws, prod, book = frozen
    import open_guji_cv.core.workspace as W
    monkeypatch.setattr(W, "feedback_root", lambda: ws / "feedback")
    assert CC._fresh_or_frozen(FakeEng(prod, book), [1], ws)["name"] == "产物新鲜（冻结基线）"
    draft = SimpleNamespace(id="bk", freeze={})
    assert CC._fresh_or_frozen(FakeEng(prod, draft), [1], ws)["name"] == "产物新鲜"


def test_frozen_missing_baseline_is_error(tmp_path):
    book = SimpleNamespace(id="bk", freeze={"snapshot": "snap/none/bk/x"})
    with pytest.raises(FZ.FreezeError):
        FZ.load_baseline(book, tmp_path)


# ── archive fetch ─────────────────────────────────────────────────────
def _tar_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _fake(tar: bytes, digest: str | None):
    asset = {"name": "x-keep.tar", "size": len(tar), "url": "u",
             **({"digest": digest} if digest else {})}
    rel = {"tag_name": "t", "assets": [asset, {"name": "notes.txt"}]}
    return (lambda url: rel), (lambda url, dest: Path(dest).write_bytes(tar))


def test_fetch_verifies_and_extracts(tmp_path):
    tar = _tar_bytes({"feedback/events/a.jsonl": b"{}\n", "books/v.yaml": b"id: v\n"})
    gj, dl = _fake(tar, "sha256:" + _sha(tar))
    res = AF.fetch("t", tmp_path / "out", get_json=gj, download=dl, log=lambda s: None)
    assert res["verified"] and res["members"] == 2
    assert (tmp_path / "out/books/v.yaml").read_bytes() == b"id: v\n"
    assert not list(tmp_path.glob(".*part"))


def test_fetch_rejects_bad_sha_and_nonempty_out(tmp_path):
    tar = _tar_bytes({"a.txt": b"a"})
    gj, dl = _fake(tar, None)
    with pytest.raises(AF.ArchiveError, match="sha256"):        # 无 digest 也没给 --sha256
        AF.fetch("t", tmp_path / "o1", get_json=gj, download=dl, log=lambda s: None)
    with pytest.raises(AF.ArchiveError, match="不符"):
        AF.fetch("t", tmp_path / "o2", sha256="0" * 64, get_json=gj, download=dl, log=lambda s: None)
    (tmp_path / "o3").mkdir()
    (tmp_path / "o3" / "x").write_text("x")
    with pytest.raises(AF.ArchiveError, match="空目录"):
        AF.fetch("t", tmp_path / "o3", sha256=_sha(tar), get_json=gj, download=dl, log=lambda s: None)
    res = AF.fetch("t", tmp_path / "o4", no_verify=True, get_json=gj, download=dl, log=lambda s: None)
    assert not res["verified"]


def test_fetch_rejects_path_escape(tmp_path):
    tar = _tar_bytes({"../evil.txt": b"x"})
    gj, dl = _fake(tar, "sha256:" + _sha(tar))
    with pytest.raises(AF.ArchiveError, match="越界"):
        AF.fetch("t", tmp_path / "out", get_json=gj, download=dl, log=lambda s: None)
    assert not (tmp_path / "evil.txt").exists()


def test_compare_skips_step_manifest(tmp_path):
    """快照里的 `_manifest.jsonl` 是打包时重写的，和线上只追加的那份 sha 必然不同，不能算「被改」。"""
    from open_guji_cv.ops.freeze import compare_products
    from open_guji_cv.snap.manifest import sha256_file
    root = tmp_path / "p" / "bk" / "s"
    root.mkdir(parents=True)
    (root / "p0001.json").write_text("{}")
    (root / "_manifest.jsonl").write_text('{"k": 1}\n{"k": 1}\n')
    base = {"files": {
        "products/bk/s/p0001.json": {"sha256": sha256_file(root / "p0001.json")},
        "products/bk/s/_manifest.jsonl": {"sha256": "0" * 64},
    }}
    assert compare_products(base, tmp_path / "p") == {"same": 1, "changed": [], "missing": []}


def test_freeze_must_be_mapping(tmp_path):
    import pytest as _pt
    from open_guji_cv.core.book import load_book
    (tmp_path / "bk.yaml").write_text("id: bk\ntitle: t\nraw_dir: raw\nfreeze: '2026-10-18'\n", encoding="utf-8")
    with _pt.raises(ValueError, match="freeze"):
        load_book("bk", books_dir=tmp_path)


def test_redirect_drops_auth_across_hosts():
    import urllib.request
    from open_guji_cv.ops.archive_fetch import _DropAuthOnCrossHost
    h = _DropAuthOnCrossHost()
    req = urllib.request.Request("https://api.github.com/x", headers={"Authorization": "Bearer t"})
    new = h.redirect_request(req, None, 302, "Found", {}, "https://objects.githubusercontent.com/y")
    assert not any(k.lower() == "authorization" for k in new.headers)
    same = h.redirect_request(req, None, 302, "Found", {}, "https://api.github.com/z")
    assert any(k.lower() == "authorization" for k in same.headers)
