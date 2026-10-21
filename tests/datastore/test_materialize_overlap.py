"""`db pull` 提速（2026-10-21，GUJI-647 第 7 项）：取图与向库要文本行同时跑；读令牌不打快照包。

不连库：数据源、图缓存都是内存里的假货。"""

from __future__ import annotations

import hashlib
import threading

from open_guji_cv.datastore import materialize as M
from open_guji_cv.datastore import workcopy as W
from open_guji_cv.datastore.scope import GS

TEXT = b"a\nb\n"
PNG = b"\x89PNG fake"


class _Src:
    """一个文本文件（逐行表）＋一张刻例图。要文本行时等取图那边先开始，证明两边是同时跑的。"""

    def __init__(self, started: threading.Event):
        self.started = started
        self.waited = None

    def rows(self, table, ws, cols=None, **filters):
        if table == "source_files":
            return [{"src_path": GS + "admissions.jsonl", "tbl": "lines", "sha256": hashlib.sha256(TEXT).hexdigest(),
                     "bytes": len(TEXT), "n_lines": 2, "final_newline": True}]
        if table == "glyph_instances":
            return [{"instance_id": "b:1:1:1", "patch_sha": hashlib.sha256(PNG).hexdigest()}]
        if table == "lines":
            self.waited = self.started.wait(10)
            return [{"src_path": GS + "admissions.jsonl", "src_line": 0, "raw": "a"},
                    {"src_path": GS + "admissions.jsonl", "src_line": 1, "raw": "b"}]
        return []


class _Cache:
    def __init__(self, root, started: threading.Event):
        from open_guji_cv.datastore.client import BlobCache
        self.c, self.started, self.thread = BlobCache(root), started, None

    def ensure(self, src, shas, bucket="main", ext="png"):
        self.thread = threading.current_thread().name
        self.started.set()
        for s in shas:
            self.c.put(s, PNG)
        return {"have": 0, "fetched": len(shas)}

    def path(self, sha):
        return self.c.path(sha)


def test_images_fetched_while_text_rows_load(tmp_path):
    started = threading.Event()
    src, cache = _Src(started), _Cache(tmp_path / "blobs", started)
    st = M.materialize(src, "w", tmp_path / "out", cache=cache)
    assert src.waited is True and cache.thread == "materialize-images"
    assert (tmp_path / "out" / GS / "admissions.jsonl").read_bytes() == TEXT
    assert (tmp_path / "out" / GS / "patches" / "b_1_1_1.png").read_bytes() == PNG
    assert (st["files"], st["images"], st["image_cache"]) == (1, 1, {"have": 0, "fetched": 1})


def test_image_error_surfaces_after_text(tmp_path):
    started = threading.Event()
    started.set()
    src = _Src(started)

    class Bad(_Cache):
        def ensure(self, *a, **k):
            raise RuntimeError("R2 断了")
    try:
        M.materialize(src, "w", tmp_path / "out", cache=Bad(tmp_path / "blobs", started))
    except RuntimeError as e:
        assert "R2" in str(e)
    else:
        raise AssertionError("取图出错要抛出来")
    assert not (tmp_path / "out").exists()


def test_read_token_skips_snapshot(tmp_path):
    put = []

    class S:
        def __init__(self, role):
            self.role = role

        def whoami(self):
            return {"name": self.role, "role": self.role}

        def put_snapshot(self, ws, rev, data):
            put.append(rev)
            return {}
    data = tmp_path / "data"
    (data / "x").mkdir(parents=True)
    (data / "x" / "a.txt").write_bytes(b"hi")
    base = {"x/a.txt": hashlib.sha256(b"hi").hexdigest()}
    assert W._publish_snapshot(S("read"), "w", 3, tmp_path, data, base) is None and put == []
    assert W._publish_snapshot(S("write"), "w", 4, tmp_path, data, base) > 0 and put == [4]
