"""``guji db pull`` 验收（GUJI-606）：从中心库还原的字形库与 git 里的逐字节相同，
重建出的 glyph.db 与 ``glyph-db rebuild --no-replay`` 在全部表上逐行相同；``--rev`` 钉版本、
实验分支事件显式导入、经 Worker 读（假 Worker）分页与批量签名。

要 ``GUJI_TEST_PG_DSN``（可建删 schema 的 Postgres），不给就跳过；假 Worker 那条不要库。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from test_datastore_pg import DSN, _commit, _git, _line, conn, repo  # noqa: F401  (fixtures)

psycopg = pytest.importorskip("psycopg")
needs_pg = pytest.mark.skipif(not DSN, reason="没有 GUJI_TEST_PG_DSN（测试用 Postgres）")

_spec = importlib.util.spec_from_file_location(
    "_clustering_conftest", Path(__file__).resolve().parents[1] / "clustering" / "conftest.py")
_cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cc)


def _store_files(tmp_path) -> dict[str, bytes]:
    """造一个真字形库（admit → export），返回 {工作区内相对路径: 字节}。"""
    from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
    db = GlyphDB(tmp_path / "seed.sqlite")
    try:
        _cc.seed_glyphs(db, chars=("甲", "乙"), n_each=4)
        cur = db.conn.cursor()
        cur.execute("INSERT INTO events (source_id, batch, seq, ts, op, payload) VALUES (?,?,?,?,?,?)",
                    ("tbook", "b1", 1, "t", "confirm", '{"op": "confirm"}'))
        db.conn.commit()
        store = tmp_path / "seed_store"
        export_store(db, store)
    finally:
        db.close()
    return {f"output/glyph_store/{p.relative_to(store).as_posix()}": p.read_bytes()
            for p in sorted(store.rglob("*")) if p.is_file()}


def _workspace(tmp_path) -> dict[str, bytes]:
    files = {"W/workspace.yaml": b"id: tws\n", "W/books/vol03.yaml": b"id: vol03\n"}
    files.update({f"W/{k}": v for k, v in _store_files(tmp_path).items()})
    files["W/feedback/events/b.jsonl"] = (_line(id="evt_b_1", batch="b", seq=1, kind="confirm") + "\n").encode()
    return files


class _Cache:
    """预先灌好的图缓存（PgSource 拿不到 R2）。"""

    def __init__(self, root: Path, files: dict[str, bytes]):
        from open_guji_cv.datastore.client import BlobCache
        self.c = BlobCache(root)
        for rel, b in files.items():
            if rel.endswith(".png"):
                self.c.put(hashlib.sha256(b).hexdigest(), b)

    def __getattr__(self, k):
        return getattr(self.c, k)


def _tables(db_path: Path) -> dict[str, list]:
    c = sqlite3.connect(db_path)
    try:
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                         "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: sorted(map(repr, c.execute(f"SELECT * FROM {n}").fetchall())) for n in names}
    finally:
        c.close()


@needs_pg
def test_pull_matches_git_store_and_rebuild(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.clustering.glyph_db import rebuild_from_store
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import import_commit
    from open_guji_cv.datastore.pull import pull, read_meta

    files = _workspace(tmp_path)
    c1 = _commit(repo, files, "c1")
    import_commit(conn, repo, c1)
    src = PgSource(conn, branch="main")

    ws = tmp_path / "local-ws"
    ws.mkdir()
    (ws / "workspace.yaml").write_bytes(files["W/workspace.yaml"])
    db_path = ws / "output" / "glyph.db"
    res = pull(src, ws, db_path, with_feedback=True,
               cache=_Cache(tmp_path / "cache", {k[2:]: v for k, v in files.items()}))
    assert res["rev"] == src.status() and res["ws"] == "tws"

    # 1. 还原的文件与提交里逐字节相同（字形库全部文件、图，外加 feedback/）
    got = Path(res["store"]).parent.parent
    for rel, b in files.items():
        rel = rel[2:]
        if rel.startswith(("output/glyph_store/", "feedback/")):
            assert (got / rel).read_bytes() == b, rel
    n_local = sum(1 for p in (got / "output" / "glyph_store").rglob("*") if p.is_file())
    assert n_local == sum(1 for k in files if k.startswith("W/output/glyph_store/"))

    # 2. 重建的库与直接从 git 里的字形库 rebuild（不补放、不借库）全部表逐行相同
    git_store = tmp_path / "git-ws"
    _git(repo, "worktree", "add", "-q", str(git_store), c1)
    ref = tmp_path / "ref.sqlite"
    rebuild_from_store(git_store / "W" / "output" / "glyph_store", ref)
    assert _tables(db_path) == _tables(ref)
    assert read_meta(db_path)["rev"] == res["rev"]

    # 3. 钉版本：没变就能按旧 rev 拉；该工作区有新写入后再钉旧 rev 就报错
    r_old = res["rev"]
    assert pull(src, ws, db_path, rev=r_old, cache=_Cache(tmp_path / "cache", {}))["rev"] == r_old
    files["W/feedback/events/b.jsonl"] += (_line(id="evt_b_2", batch="b", seq=2) + "\n").encode()
    import_commit(conn, repo, _commit(repo, files, "c2"))
    with pytest.raises(SystemExit, match="之后已有变更"):
        pull(src, ws, db_path, rev=r_old, cache=_Cache(tmp_path / "cache", {}))


@needs_pg
def test_materialize_refuses_tampered_db(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import import_commit
    from open_guji_cv.datastore.materialize import MaterializeError, materialize

    files = _workspace(tmp_path)
    import_commit(conn, repo, _commit(repo, files, "c1"))
    conn.execute("UPDATE glyphs SET raw = raw || ' '")
    out = tmp_path / "out"
    with pytest.raises(MaterializeError, match="sha 不符"):
        materialize(PgSource(conn), "tws", out, cache=_Cache(tmp_path / "cache", files))
    assert not (out / "output").exists()            # 不留半成品


class _FakeDst:
    branch = "main"

    def __init__(self, have):
        self.have, self.calls = have, []

    def rows(self, table, ws):
        return iter([{"id": i} for i in self.have])

    def append_events(self, ws, src_path, lines, branch=None):
        self.calls.append((ws, src_path, lines, branch))
        return {"inserted": [json.loads(x)["id"] for x in lines], "duplicates": [], "import_id": 9, "rev_to": 99}


@needs_pg
def test_import_events_from_exp_branch(repo, conn, tmp_path):  # noqa: F811
    from open_guji_cv.datastore.client import PgSource
    from open_guji_cv.datastore.importer import import_commit
    from open_guji_cv.datastore.pull import import_events

    files = _workspace(tmp_path)
    files["W/feedback/events/b.jsonl"] += (_line(id="evt_b_2", batch="b", seq=2) + "\n").encode()
    import_commit(conn, repo, _commit(repo, files, "c1"))
    exp = PgSource(conn, branch="exp/GUJI-606-t")

    dst = _FakeDst(have={"evt_b_1"})
    plan = import_events(exp, dst, "tws", None, dst_branch="main", dry_run=True)
    assert plan["plan"] == {"feedback/events/b.jsonl": 1} and not dst.calls
    res = import_events(exp, dst, "tws", None, dst_branch="main")
    assert res["results"][0]["inserted"] == 1
    assert json.loads(dst.calls[0][2][0])["id"] == "evt_b_2" and dst.calls[0][3] == "main"
    with pytest.raises(SystemExit, match="找不到"):
        import_events(exp, _FakeDst(set()), "tws", {"evt_nope"}, dst_branch="main")


# ---- 经 Worker 读：假 Worker，验证分页、批量签名、旧版 Worker 退回逐张签 ----

def _fake_worker(rows: list[dict], blobs: dict[str, bytes], batch: bool):
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj=None, raw=None):
            body = raw if raw is not None else json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            calls.append(("GET", u.path))
            if u.path.startswith("/blob/"):
                return self._send(200, raw=blobs[u.path.rsplit("/", 1)[1]])
            assert self.headers["authorization"] == "Bearer tok"
            if u.path == "/v1/status":
                return self._send(200, {"rev": 7})
            if u.path == "/v1/tables/source_files":
                lim = int(q["limit"])
                start = json.loads(q["after"])[0] if "after" in q else -1
                page = [r for r in rows if r["i"] > start][:lim]
                nxt = json.dumps([page[-1]["i"]]) if len(page) == lim else None
                return self._send(200, {"rows": page, "next": nxt})
            self._send(404, {"error": "not_found", "message": "x"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            calls.append(("POST", self.path))
            base = f"http://127.0.0.1:{self.server.server_port}/blob/"
            if self.path == "/v1/assets/sign-batch" and batch:
                return self._send(200, {"items": [{"sha256": s, "url": base + s} for s in body["sha256s"]]})
            if self.path == "/v1/assets/sign":
                return self._send(200, {"url": base + body["sha256"]})
            self._send(404, {"error": "not_found", "message": "没有这个接口"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, calls


@pytest.mark.parametrize("batch", [True, False])
def test_worker_source_paging_and_blobs(monkeypatch, tmp_path, batch):
    from open_guji_cv.datastore import client
    from open_guji_cv.datastore.client import BlobCache, WorkerSource

    monkeypatch.setattr(client, "PAGE", 2)
    rows = [{"i": i, "src_path": f"f{i}"} for i in range(5)]
    blobs = {hashlib.sha256(b).hexdigest(): b for b in (b"a", b"b", b"c")}
    srv, calls = _fake_worker(rows, blobs, batch)
    try:
        src = WorkerSource(url=f"http://127.0.0.1:{srv.server_port}", token="tok", branch="ci")
        assert src.status() == 7
        assert [r["i"] for r in src.rows("source_files", "tws")] == list(range(5))
        cache = BlobCache(tmp_path / "c")
        assert cache.ensure(src, list(blobs) * 2) == {"have": 0, "fetched": 3}
        assert cache.ensure(src, list(blobs)) == {"have": 3, "fetched": 0}   # 再拉不发请求
        assert all(cache.path(s).read_bytes() == b for s, b in blobs.items())
    finally:
        srv.shutdown()
    signs = [p for m, p in calls if m == "POST"]
    assert signs == (["/v1/assets/sign-batch"] if batch else ["/v1/assets/sign-batch"] + ["/v1/assets/sign"] * 3)


def test_blob_cache_rejects_wrong_bytes(tmp_path):
    from open_guji_cv.datastore.client import BlobCache, CentralError
    with pytest.raises(CentralError):
        BlobCache(tmp_path).put("0" * 64, b"x")
