"""中心库实验分支：GUJI_DATA_BRANCH 换数据目录、glyph.db、products；push／sync 连该分支；diff；图回落实验桶。"""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from test_datastore_pg import conn, repo  # noqa: F401  (fixtures)

EXP = "exp/GUJI-612-try"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home"))
    for k in ("GUJI_WORKSPACE", "GUJI_GLYPH_DB", "GUJI_PRODUCTS_DIR", "GUJI_DATA_BRANCH", "GUJI_GLYPH_STORE"):
        monkeypatch.delenv(k, raising=False)


def _ws(tmp_path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".central.json").write_text('{"ws": "tws", "branch": "main"}')
    (ws / "workspace.yaml").write_text("id: tws\n")
    return ws


def test_branch_env_moves_data_dir_glyph_db_and_products(tmp_path, monkeypatch):
    from open_guji_cv.core import workspace as W
    ws = _ws(tmp_path)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    assert W.data_root() == W.central_data_dir("tws")
    assert W.glyph_db_path() == ws / "output" / "glyph.db"
    assert W.products_root() == ws / "products"

    monkeypatch.setenv("GUJI_DATA_BRANCH", EXP)
    exp = W.central_data_dir("tws", EXP)
    assert exp.parent.name == "exp__GUJI-612-try"
    assert W.active_branch() == EXP
    assert W.data_root() == exp and W.books_dir() == exp / "books"
    assert W.glyph_db_path() == exp / "output" / "glyph.db"
    assert W.products_root() == exp / "products"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(tmp_path / "p"))          # 显式指定仍然优先
    assert W.products_root() == tmp_path / "p"
    # 标记文件不动
    assert json.loads((ws / ".central.json").read_text())["branch"] == "main"


def test_write_branch_rules_and_endpoint_lookup(monkeypatch):
    from open_guji_cv import cli_db
    from open_guji_cv.datastore import connect, neonapi
    with pytest.raises(SystemExit, match="不能写 ci"):
        cli_db._check_write_branch("ci")
    with pytest.raises(SystemExit, match="不能写"):
        cli_db._check_write_branch("exp/foo")
    cli_db._check_write_branch(EXP)
    assert cli_db._bucket("main") == "main" and cli_db._bucket(EXP) == "exp"

    calls = []
    monkeypatch.setattr(neonapi, "_get", lambda path: {
        "branches": [{"name": "main", "id": "br-m"}, {"name": EXP, "id": "br-x"}],
        "endpoints": [{"id": "ep-m", "branch_id": "br-m", "type": "read_write"},
                      {"id": "ep-x", "branch_id": "br-x", "type": "read_write"}],
    })
    monkeypatch.setattr(connect, "connect", lambda endpoint=None: calls.append(endpoint) or "conn")
    assert cli_db._pg_conn(EXP) == "conn" and calls == ["ep-x"]
    monkeypatch.setenv("GUJI_DATA_BRANCH", EXP)
    cli_db._pg_conn()
    assert calls[-1] == "ep-x"
    with pytest.raises(SystemExit, match="没有分支"):
        neonapi.branch_endpoint("exp/GUJI-1-none")


class _Src:
    def __init__(self, branch, files, events, rev):
        self.branch, self._files, self._events, self._rev = branch, files, events, rev

    def status(self):
        return self._rev

    def rows(self, table, ws=None, **kw):
        if table == "source_files":
            return iter([{"src_path": p, "sha256": s, "n_lines": n} for p, (s, n) in self._files.items()])
        if table == "events":
            return iter([{"id": i} for i in self._events])
        return iter([])


def test_diff_branches():
    from open_guji_cv.datastore.pull import diff_branches
    main = _Src("main", {"books/a.yaml": ("1", 3), "feedback/events/b.jsonl": ("2", 10),
                         "config/x.json": ("3", 1)}, ["e1", "e2"], 1500)
    exp = _Src(EXP, {"books/a.yaml": ("1", 3), "feedback/events/b.jsonl": ("9", 12),
                     "feedback/events/new.jsonl": ("4", 2)}, ["e1", "e2", "e3", "e4"], 1502)
    d = diff_branches(exp, main, "tws")
    assert d["same"] == 1 and d["rev"] == 1502 and d["against_rev"] == 1500
    assert d["changed"]["items"] == [{"path": "feedback/events/b.jsonl", "lines": 12, "against_lines": 10}]
    assert d["only_in_branch"]["items"] == ["feedback/events/new.jsonl"]
    assert d["only_in_against"]["by_dir"] == {"config/x.json": 1}
    assert d["events_only_in_branch"] == {"n": 2, "ids": ["e3", "e4"]}


def test_exp_branch_fetch_falls_back_to_exp_bucket():
    """实验分支上：正式桶没有的图（实验里新传的）去实验桶取；main 分支不回落。"""
    from open_guji_cv.datastore.client import CentralError, WorkerSource
    old = hashlib.sha256(b"old").hexdigest()
    new = hashlib.sha256(b"new").hexdigest()
    store = {"main": {old: b"old"}, "exp": {new: b"new"}}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, raw):
            self.send_response(code)
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            _, bucket, sha = self.path.rsplit("/", 2)
            b = store[bucket].get(sha)
            self._send(200, b) if b is not None else self._send(404, b"no")

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            base = f"http://127.0.0.1:{self.server.server_port}/blob/{body['bucket']}/"
            self._send(200, json.dumps({"items": [{"sha256": s, "url": base + s}
                                                  for s in body["sha256s"]]}).encode())

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    try:
        got = dict(WorkerSource(url=url, token="t", branch=EXP).fetch_blobs([old, new], workers=2))
        assert got == {old: b"old", new: b"new"}
        with pytest.raises(CentralError):
            dict(WorkerSource(url=url, token="t", branch="main").fetch_blobs([old, new], workers=2))
    finally:
        srv.shutdown()


def test_cli_branch_flag_sets_env(tmp_path, monkeypatch):
    import argparse

    from open_guji_cv import cli_db
    ws = _ws(tmp_path)
    seen = {}
    monkeypatch.setattr(cli_db, "push_workspace", lambda d, **kw: seen.update(
        branch=__import__("os").environ.get("GUJI_DATA_BRANCH")) or {})
    sub = argparse.ArgumentParser().add_subparsers(dest="cmd")
    cli_db.add_parser(sub)
    args = sub.choices["db"].parse_args(["push", "-w", str(ws), "--branch", EXP])
    monkeypatch.setenv("GUJI_DATA_TOKEN", "t")
    monkeypatch.setenv("GUJI_DATA_BRANCH", "")              # cmd_db 会改它；让 monkeypatch 收尾时还原
    cli_db.cmd_db(args)
    assert seen["branch"] == EXP


def test_pull_push_on_exp_branch_keeps_main_copy_apart(repo, conn, tmp_path, monkeypatch):  # noqa: F811
    """同一工作区：main 的数据目录与实验分支的各管各的；在实验分支上改了推上去，main 的副本不动。"""
    from test_datastore_pg import DSN
    if not DSN:
        pytest.skip("没有 GUJI_TEST_PG_DSN（测试用 Postgres）")
    from test_datastore_workcopy import _data_files, _fresh, _setup

    from open_guji_cv.core import workspace as W
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.workcopy import (
        data_dir,
        local_changes,
        pull,
        push,
        read_state,
    )
    src, files, cache, _ = _setup(repo, conn, tmp_path)
    ws = _fresh(files, tmp_path / "w", src, cache)
    main_dir = data_dir(ws)
    before = _data_files(main_dir)

    monkeypatch.setenv("GUJI_DATA_BRANCH", EXP)
    exp_src = PgSource(conn, branch=EXP)                       # 测试里同一个库充当分出来的实验分支
    pull(exp_src, ws, cache=cache)
    exp_dir = data_dir(ws)
    assert exp_dir == W.central_data_dir("tws", EXP) != main_dir
    assert read_state(exp_dir)["branch"] == EXP
    (exp_dir / "books" / "vol09.yaml").write_bytes(b"id: vol09\n")
    assert local_changes(ws) == ["books/vol09.yaml"]
    out = push(conn, ws, actor="exp")
    assert out["rev_to"] > out["rev_from"] and local_changes(ws) == []

    monkeypatch.delenv("GUJI_DATA_BRANCH")
    assert data_dir(ws) == main_dir and _data_files(main_dir) == before
    assert read_state(main_dir)["branch"] == "main"
