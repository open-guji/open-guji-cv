"""中心库读路径验收（GUJI-606）：篡改的库内容被拒、实验分支事件显式导入、经 Worker 读（假 Worker）
分页与批量签名。拉、推、迁移见 ``test_datastore_workcopy.py``。

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

def _framed(blobs: dict[str, bytes], shas: list[str]) -> bytes:
    out = b""
    for s in shas:
        b = blobs.get(s)
        out += f"{s} {len(b) if b is not None else -1}\n".encode() + (b or b"")
    return out


def _fake_worker(rows: list[dict], blobs: dict[str, bytes], batch: bool, get_batch: bool = False):
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
            if self.path == "/v1/assets/get-batch" and get_batch:
                assert self.headers["authorization"] == "Bearer tok"
                return self._send(200, raw=_framed(blobs, body["sha256s"]))
            if self.path == "/v1/assets/sign-batch" and batch:
                return self._send(200, {"items": [{"sha256": s, "url": base + s} for s in body["sha256s"]]})
            if self.path == "/v1/assets/sign":
                return self._send(200, {"url": base + body["sha256"]})
            self._send(404, {"error": "not_found", "message": "没有这个接口"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, calls


@pytest.mark.parametrize("batch,get_batch", [(True, True), (True, False), (False, False)])
def test_worker_source_paging_and_blobs(monkeypatch, tmp_path, batch, get_batch):
    from open_guji_cv.datastore import client
    from open_guji_cv.datastore.client import BlobCache, WorkerSource

    monkeypatch.setattr(client, "PAGE", 2)
    rows = [{"i": i, "src_path": f"f{i}"} for i in range(5)]
    blobs = {hashlib.sha256(b).hexdigest(): b for b in (b"a", b"b", b"c")}
    srv, calls = _fake_worker(rows, blobs, batch, get_batch)
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
    if get_batch:   # 新版 Worker：一次请求取回三张，不签名、不逐张 GET
        assert signs == ["/v1/assets/get-batch"] and not any(p.startswith("/blob/") for _, p in calls)
    else:           # 旧版 Worker：没有 get-batch 就退回签名直取
        assert signs == ["/v1/assets/get-batch"] + (["/v1/assets/sign-batch"] if batch
                                                     else ["/v1/assets/sign-batch"] + ["/v1/assets/sign"] * 3)


def test_blob_cache_rejects_wrong_bytes(tmp_path):
    from open_guji_cv.datastore.client import BlobCache, CentralError
    with pytest.raises(CentralError):
        BlobCache(tmp_path).put("0" * 64, b"x")


def test_fetch_blobs_reuses_connections_and_retries(monkeypatch):
    """取图每个线程一条长连接（不再一张一握手）；5xx 退避重试。"""
    from open_guji_cv.datastore import client
    from open_guji_cv.datastore.client import WorkerSource

    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    blobs = {hashlib.sha256(bytes([i])).hexdigest(): bytes([i]) for i in range(40)}
    peers, failed = set(), set()

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
            peers.add(self.client_address[1])
            sha = self.path.rsplit("/", 1)[1]
            if sha not in failed:                  # 每张第一次回 503
                failed.add(sha)
                return self._send(503, b"busy")
            self._send(200, blobs[sha])

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            if self.path == "/v1/assets/get-batch":    # 旧版 Worker
                return self._send(404, b'{"error": "not_found", "message": "x"}')
            base = f"http://127.0.0.1:{self.server.server_port}/blob/"
            self._send(200, json.dumps({"items": [{"sha256": s, "url": base + s}
                                                  for s in body["sha256s"]]}).encode())

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        src = WorkerSource(url=f"http://127.0.0.1:{srv.server_port}", token="tok")
        got = dict(src.fetch_blobs(list(blobs), workers=4))
    finally:
        srv.shutdown()
    assert got == blobs
    assert len(peers) <= 4 + 1                     # 4 个取图线程各一条，加签名那一条


def test_get_batch_chunks_splits_and_retries(monkeypatch):
    """批量取图：按 FETCH_BATCH 分批；503（1102）对半拆；回包断在半截整批重取；图确实没有报 missing_blob。"""
    from open_guji_cv.datastore import client
    from open_guji_cv.datastore.client import CentralError, WorkerSource

    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    monkeypatch.setattr(client, "FETCH_BATCH", 50)
    blobs = {hashlib.sha256(b).hexdigest(): b for b in (bytes([i, 10]) * (i + 1) for i in range(120))}
    sizes, truncated = [], set()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, raw):
            self.send_response(code)
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            shas = body["sha256s"]
            sizes.append(len(shas))
            if len(shas) > 30:                             # 超资源
                return self._send(503, b"error code: 1102")
            raw = _framed(blobs, shas)
            if shas[0] not in truncated:                   # 每批第一次只回一半
                truncated.add(shas[0])
                raw = raw[: len(raw) // 2]
            self._send(200, raw)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        src = WorkerSource(url=f"http://127.0.0.1:{srv.server_port}", token="tok")
        got = dict(src.fetch_blobs(list(blobs), workers=3))
        with pytest.raises(CentralError, match="missing_blob"):
            list(src.fetch_blobs(["ee" * 32]))
    finally:
        srv.shutdown()
    assert got == blobs
    assert max(sizes) == 50 and all(n <= 30 for n in sizes if n not in (50, 20))


def test_worker_resource_limit_shrinks_pages(monkeypatch):
    """Worker 超资源回 503（Cloudflare 1102）时：查表页减半、批量签名对半拆，不整次失败。"""
    from open_guji_cv.datastore import client
    from open_guji_cv.datastore.client import WorkerSource

    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    rows = [{"i": i, "src_path": f"f{i}"} for i in range(1200)]
    seen = {"limits": [], "signs": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            raw = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            lim = int(q["limit"])
            seen["limits"].append(lim)
            if lim > 500:
                return self._send(503, {"error": "http", "message": "error code: 1102"})
            start = json.loads(q["after"])[0] if "after" in q else -1
            page = [r for r in rows if r["i"] > start][:lim]
            self._send(200, {"rows": page, "next": json.dumps([page[-1]["i"]]) if len(page) == lim else None})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen["signs"].append(len(body["sha256s"]))
            if len(body["sha256s"]) > 60:
                return self._send(503, {"error": "http", "message": "error code: 1102"})
            self._send(200, {"items": [{"sha256": s, "url": "u" + s} for s in body["sha256s"]]})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        src = WorkerSource(url=f"http://127.0.0.1:{srv.server_port}", token="tok")
        assert [r["i"] for r in src.rows("events", "tws")] == list(range(1200))
        shas = [f"{i:064x}" for i in range(200)]
        assert src._sign_get("main", shas) == {s: "u" + s for s in shas}
    finally:
        srv.shutdown()
    assert max(l for l in seen["limits"] if l <= 500) == 500
    assert max(seen["signs"]) == 200 and max(n for n in seen["signs"] if n <= 60) <= 60
