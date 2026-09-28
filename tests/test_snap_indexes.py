# -*- coding: utf-8 -*-
"""模板索引随快照分发（`open_guji_cv/snap/indexes.py`，overview#246）：真 git、假 origin。

一张表 = 一条 `idx/<kind>/<key>` 孤儿分支；包 manifest 只写引用。验：
打包按 key 去重（远端已有不重推、包内重复只留一条）、大文件不进 snap 包也不进 main、
导入按 key 去重（已在就不拉）、分块拼回、sha 不对不落位、产物包与纯附件包都能带。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from open_guji_cv.snap import importer as imp, indexes as idx, manifest as mf, pack as sp
from tests.test_snap_autoimport import (BOOK, WS_DIR, fake_fresh, git, make_pack, run_watch,  # noqa: F401
                                        world, write_products)


def _npz(tmp: Path, name: str, n: int = 2600) -> Path:
    p = tmp / name
    p.write_bytes(bytes((i * 7) % 256 for i in range(n)))
    return p


def _rare(tmp: Path, key: str) -> idx.IndexFile:
    return idx.IndexFile("rare_emb", key, _npz(tmp, f"emb_{key}.npz"), f"models/r5/emb_{key}.npz", f"t {key}")


def _remote_heads(w, pattern: str) -> dict[str, str]:
    out = git(w["cloud"], "ls-remote", "origin", f"refs/heads/{pattern}")
    return {ln.split("\t")[1][len("refs/heads/"):]: ln.split("\t")[0] for ln in out.splitlines() if ln}


def _attach_only(w, entries, stamp="20260928T2000"):
    spec = sp.PackSpec(book=BOOK, products_root=w["tmp"] / "none", ws_dir=w["cloud"] / WS_DIR,
                       mode="attach-only", cv_commit=w["A"], indexes=entries, stamp=stamp,
                       glyph_fingerprint="fp", session="t")
    tree = w["tmp"] / f"tree-{stamp}"
    m = sp.build_tree(spec, tree)
    sp.commit_and_push(w["cloud"], tree, m)
    return m, tree


def test_publish_pushes_one_orphan_branch_per_key_and_dedupes(world, monkeypatch):
    monkeypatch.setattr(idx, "CHUNK_BYTES", 1000)
    a, b = _rare(world["tmp"], "aaaaaaaaaaaaaaaa"), _rare(world["tmp"], "bbbbbbbbbbbbbbbb")
    dup = idx.IndexFile(a.kind, a.key, a.src, a.dest, "另一本书也用这张")
    entries = idx.publish(world["cloud"], [a, b, dup], cv_commit=world["A"])
    assert [e["key"] for e in entries] == [a.key, b.key]            # 包内重复只留一条
    assert "另一本书也用这张" in entries[0]["label"]
    assert not any(e["reused"] for e in entries)
    heads = _remote_heads(world, "idx/*")
    assert set(heads) == {"idx/rare_emb/" + a.key, "idx/rare_emb/" + b.key}
    br = "idx/rare_emb/" + a.key
    # 孤儿：无父提交；里面只有 index.json + 分块
    assert git(world["cloud"], "rev-list", "--count", heads[br]) == "1"
    files = git(world["cloud"], "ls-tree", "--name-only", heads[br]).splitlines()
    assert files == ["data.part000", "data.part001", "data.part002", "index.json"]
    meta = json.loads(git(world["cloud"], "show", f"{heads[br]}:index.json"))
    assert meta["sha256"] == mf.sha256_file(a.src) and meta["dest"] == a.dest

    # 第二次：远端已有同 key → 直接引用，不重推（分支提交不变）
    again = idx.publish(world["cloud"], [a], cv_commit=world["B"])
    assert again[0]["reused"] and again[0]["sha256"] == meta["sha256"]
    assert _remote_heads(world, "idx/*")[br] == heads[br]


def test_index_pack_carries_only_references_and_import_dedupes_by_key(world):
    a, b = _rare(world["tmp"], "aaaaaaaaaaaaaaaa"), _rare(world["tmp"], "bbbbbbbbbbbbbbbb")
    entries = idx.publish(world["cloud"], [a, b], cv_commit=world["A"])
    m, tree = _attach_only(world, entries)
    assert [e["key"] for e in m["indexes"]] == [a.key, b.key]
    # 包本身不带 npz：只有 manifest.json
    packed = git(world["origin"], "ls-tree", "-r", "--name-only", f"refs/heads/{m['branch']}")
    assert packed.splitlines() == ["manifest.json"]
    # main 历史里没有任何 npz
    assert "npz" not in git(world["origin"], "log", "--format=", "--name-only", "main")

    # 服务器已有 b（按 key 去重：已在就跳过、不拉、不覆盖）
    have_b = world["cv"] / b.dest
    have_b.parent.mkdir(parents=True)
    have_b.write_bytes(b"server-built-same-key")
    out = run_watch(world)
    r = out["results"][0]
    assert r["status"] == imp.IMPORTED, r
    assert r["indexes_placed"] == [f"rare_emb/{a.key}"] and r["indexes_present"] == [f"rare_emb/{b.key}"]
    assert (world["cv"] / a.dest).read_bytes() == a.src.read_bytes()
    assert have_b.read_bytes() == b"server-built-same-key"
    assert not list((world["cv"] / "models/r5").glob("*.snap-tmp"))
    # 服务器上没拉 b 的 idx 分支
    assert subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/remotes/origin/idx/rare_emb/{b.key}"],
                          cwd=world["server"], capture_output=True).returncode != 0
    rec = next((world["overview"]).rglob("*-import.md")).read_text(encoding="utf-8")
    assert "模板索引落位" in rec and a.key in rec


def test_second_pack_sharing_key_reuses_branch(world):
    """全唐文 v007–v009 共用一张 escalate：三个包都引用同一条 idx 分支，只推一次。"""
    shared = _rare(world["tmp"], "5fb2b08b71b8a796")
    e1 = idx.publish(world["cloud"], [shared], cv_commit=world["A"])
    e2 = idx.publish(world["cloud"], [shared], cv_commit=world["A"])
    assert not e1[0]["reused"] and e2[0]["reused"]
    _attach_only(world, e1, stamp="20260928T2001")
    _attach_only(world, e2, stamp="20260928T2002")
    out = run_watch(world)
    st = sorted((r["status"], tuple(r.get("indexes_placed", [])), tuple(r.get("indexes_present", [])))
                for r in out["results"])
    assert st == [(imp.IMPORTED, (), (f"rare_emb/{shared.key}",)),
                  (imp.IMPORTED, (f"rare_emb/{shared.key}",), ())]


def test_index_sha_mismatch_is_retryable_and_places_nothing(world):
    a = _rare(world["tmp"], "aaaaaaaaaaaaaaaa")
    entries = idx.publish(world["cloud"], [a], cv_commit=world["A"])
    entries[0]["sha256"] = "f" * 64                                  # 包里写的与 idx 分支对不上
    _attach_only(world, entries)
    r = run_watch(world)["results"][0]
    assert r["status"] == imp.FETCH_FAILED and "对不上" in r["error"]
    assert imp.FETCH_FAILED in imp.RETRYABLE
    assert not (world["cv"] / a.dest).exists()


def test_products_pack_with_font_index_into_workspace(world):
    """产物包也能带索引；font_hog 落书工作区 `cache/font_index/`。"""
    f = idx.IndexFile("font_hog", "cccccccccccccccc", _npz(world["tmp"], "c.npz"),
                      "cache/font_index/cccccccccccccccc.npz")
    entries = idx.publish(world["cloud"], [f], cv_commit=world["A"])
    prod = world["tmp"] / "cloudprod"
    write_products(prod, "new")
    spec = sp.PackSpec(book=BOOK, products_root=prod, ws_dir=world["cloud"] / WS_DIR, cv_commit=world["A"],
                       indexes=entries, stamp="20260928T2003", glyph_fingerprint="fp", session="t")
    tree = world["tmp"] / "tree-p"
    m = sp.build_tree(spec, tree)
    sp.commit_and_push(world["cloud"], tree, m)
    dry = imp.import_pack(m["branch"], ws_repo=world["server"], ws_roots=[world["server"]], cv_repo=world["cv"],
                          dry_run=True, freshness_fn=fake_fresh())
    assert dry.status == imp.WOULD_IMPORT and dry.detail["indexes"][0]["status"] == idx.WOULD_PLACE
    r = run_watch(world)["results"][0]
    assert r["status"] == imp.IMPORTED and r["indexes_placed"] == ["font_hog/cccccccccccccccc"]
    assert (world["server"] / WS_DIR / f.dest).read_bytes() == f.src.read_bytes()


@pytest.mark.parametrize("bad", [
    {"kind": "other"},
    {"root": "ws"},                                           # rare_emb 只许落 cv
    {"dest": "open_guji_cv/core/engine.py"},
    {"dest": "models/r5/emb_0000000000000000.npz"},           # dest 与 key 不符
    {"branch": "snap/x"},
    {"key": "../../etc"},
])
def test_index_entry_shape_is_validated(bad):
    e = {"kind": "rare_emb", "key": "aaaaaaaaaaaaaaaa", "root": "cv",
         "dest": "models/r5/emb_aaaaaaaaaaaaaaaa.npz", "branch": "idx/rare_emb/aaaaaaaaaaaaaaaa",
         "sha256": "0" * 64}
    idx.check_entry(e)
    with pytest.raises(mf.ManifestError):
        idx.check_entry({**e, **bad})


def test_rare_index_files_uses_production_key(monkeypatch, tmp_path):
    """打包端算 key 与 `guji cache build-rare-index`/产线同一个函数；表没建就报错、不替人现建。"""
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.clustering import rare_panel

    repo = tmp_path / "cv"
    (repo / "models/r5").mkdir(parents=True)
    ckpt = repo / "models/r5/best.pt"
    ckpt.write_bytes(b"x")
    monkeypatch.setattr(cc, "DEFAULT_CKPT", ckpt)
    monkeypatch.setattr(rare_panel, "book_charsets",
                        lambda book, corpus: (("一", "二"), ("丄",), {"base": "b", "escalate": "e"}))
    monkeypatch.setattr("open_guji_cv.steps.align_ref.book_corpus", lambda book: None)
    monkeypatch.setattr(cc.CnnCandidates, "emb_index_key",
                        lambda self, cs: (("k%015d" % len(cs)).replace("k", "a"),
                                          ckpt.parent / f"emb_{('k%015d' % len(cs)).replace('k', 'a')}.npz", {}))
    with pytest.raises(FileNotFoundError, match="build-rare-index"):
        idx.rare_index_files("b1", cv_repo=repo)
    # 远端已有这两条 idx 分支：本地没文件也行（src=None，只引用）
    refs = idx.rare_index_files("b1", cv_repo=repo, remote_have={"idx/rare_emb/a000000000000002",
                                                                  "idx/rare_emb/a000000000000001"})
    assert [f.src for f in refs] == [None, None]
    for n in (1, 2):
        (ckpt.parent / f"emb_a{n:015d}.npz").write_bytes(b"z")
    got = idx.rare_index_files("b1", cv_repo=repo)
    assert [(f.key, f.dest) for f in got] == [("a000000000000002", "models/r5/emb_a000000000000002.npz"),
                                              ("a000000000000001", "models/r5/emb_a000000000000001.npz")]
    assert [f.key for f in idx.rare_index_files("b1", "escalate", cv_repo=repo)] == ["a000000000000001"]


def test_index_hosted_on_cv_repo(world):
    """`--index-repo cv`：idx 分支挂在 cv 仓的 origin，导入端到 cv 仓去拉（首批表只能这么放，
    见 indexes.HOSTS）。snap 包本身照旧在 guji-workspace。"""
    cv_origin = world["tmp"] / "cv-origin.git"
    git(world["tmp"], "clone", "-q", "--bare", str(world["cv"]), str(cv_origin))
    git(world["cv"], "remote", "add", "origin", str(cv_origin))
    cloud_cv = world["tmp"] / "cloud-cv"
    git(world["tmp"], "clone", "-q", str(cv_origin), str(cloud_cv))
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        git(cloud_cv, "config", k, v)
    a = _rare(world["tmp"], "dddddddddddddddd")
    entries = idx.publish(cloud_cv, [a], host="cv", cv_commit=world["A"])
    assert entries[0]["repo"] == "cv"
    assert "idx/rare_emb/" + a.key in git(cv_origin, "for-each-ref", "--format=%(refname)")
    assert "idx/" not in git(world["origin"], "for-each-ref", "--format=%(refname)")
    _attach_only(world, entries)
    r = run_watch(world)["results"][0]
    assert r["status"] == imp.IMPORTED and r["indexes_placed"] == [f"rare_emb/{a.key}"], r
    assert (world["cv"] / a.dest).read_bytes() == a.src.read_bytes()


def test_reference_existing_remote_index_without_local_file(world):
    """本地没建过、远端已有同 key：只引用，不要求本地有文件；远端也没有就报错。"""
    a = _rare(world["tmp"], "eeeeeeeeeeeeeeee")
    first = idx.publish(world["cloud"], [a], cv_commit=world["A"])
    ref = idx.IndexFile(a.kind, a.key, None, a.dest, "别的会话")
    again = idx.publish(world["cloud"], [ref], cv_commit=world["A"])
    assert again[0]["reused"] and again[0]["sha256"] == first[0]["sha256"]
    with pytest.raises(mf.ManifestError, match="本地也没有"):
        idx.publish(world["cloud"], [idx.IndexFile("rare_emb", "ffffffffffffffff", None,
                                                   "models/r5/emb_ffffffffffffffff.npz")])
