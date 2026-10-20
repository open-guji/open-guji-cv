# -*- coding: utf-8 -*-
"""中心库客户端超时分两档、超时后快速重试（GUJI-707）。

国内节点连 data.open-guji.com 约 15% 卡在 TLS 握手（GUJI-703）。这里用本机 socket 模拟「连上了、一直不回」，
不碰真 Worker。"""
from __future__ import annotations

import hashlib
import io
import json
import socket
import threading
import time

import pytest

from open_guji_cv.datastore import client as C


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(C.time, "sleep", lambda s: None)    # 退避照走，不真等


def test_small_timeout_env(monkeypatch):
    monkeypatch.delenv("GUJI_DATA_TIMEOUT", raising=False)
    assert C.default_small_timeout() == C.SMALL_TIMEOUT
    assert 20 <= C.SMALL_TIMEOUT <= 30 and C.BIG_TIMEOUT == 120
    monkeypatch.setenv("GUJI_DATA_TIMEOUT", "7.5")
    assert C.default_small_timeout() == 7.5
    assert C.WorkerSource(url="http://x", token="t").small_timeout == 7.5
    for bad in ("abc", "0", "-3"):
        monkeypatch.setenv("GUJI_DATA_TIMEOUT", bad)
        assert C.default_small_timeout() == C.SMALL_TIMEOUT


class _Hanging:
    """本机 HTTP：前 `hang` 个连接收下请求却一直不回（模拟握手／首字节卡住），之后正常回 JSON。"""

    def __init__(self, hang: int, body: dict):
        self.hang, self.body, self.conns = hang, body, 0
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.held: list[socket.socket] = []
        self.stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self.stop:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            self.conns += 1
            if self.conns <= self.hang:
                self.held.append(c)                     # 不回，也不关
                continue
            c.recv(65536)
            data = json.dumps(self.body).encode()
            c.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: "
                      + str(len(data)).encode() + b"\r\nconnection: close\r\n\r\n" + data)
            c.close()

    def close(self):
        self.stop = True
        self.sock.close()
        for c in self.held:
            c.close()


def test_small_request_times_out_fast_and_retries():
    srv = _Hanging(hang=2, body={"rev": 42})
    try:
        w = C.WorkerSource(url=f"http://127.0.0.1:{srv.port}", token="t", small_timeout=0.3)
        t0 = time.time()
        assert w.status() == 42                         # 前两次超时，第三次拿到
        assert srv.conns == 3 and w.requests == 3
        assert time.time() - t0 < 5                     # 0.3 秒一档，而不是 120 秒
    finally:
        srv.close()


def test_small_request_net_retry_floor():
    """`_rows` 等传 tries=2（给 503 拆页留的）：网络超时仍至少试 NET_TRIES 次，之后才报错。"""
    srv = _Hanging(hang=99, body={})
    try:
        w = C.WorkerSource(url=f"http://127.0.0.1:{srv.port}", token="t", small_timeout=0.2)
        with pytest.raises(OSError):                    # socket.timeout／URLError 都是 OSError
            w._call("GET", "/v1/tables/x", tries=2)
        assert srv.conns == C.NET_TRIES
    finally:
        srv.close()


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_timeout_tier_by_request(monkeypatch):
    """小 JSON 用短超时；回原始字节、发大块字节的维持 120 秒。"""
    seen: list[tuple[str, float]] = []

    def urlopen(req, context=None, timeout=None):
        seen.append((req.full_url.split("?")[0].rsplit("/v1/", 1)[1], timeout))
        return _Resp(json.dumps({"rev": 1, "rows": [], "branches": []}).encode())

    monkeypatch.setattr(C.urllib.request, "urlopen", urlopen)
    w = C.WorkerSource(url="https://x", token="t", small_timeout=20)
    w.whoami()
    w.status()
    w.changes_since("ws", 3)
    w.branches()
    w.append_events("ws", "feedback/events/a.jsonl", ["{}"])
    w.put_snapshot("ws", 3, b"\x1f\x8b" + b"0" * 100)
    w.get_backup("2026-10-20", "x.tar.gz")
    w._call("GET", "/v1/whoami", timeout=5)             # 显式给了就用给的
    assert seen == [("whoami", 20), ("status", 20), ("tables/changes", 20), ("branches", 20),
                    ("events", 20), ("snapshots/ws", C.BIG_TIMEOUT),
                    ("backups/2026-10-20/x.tar.gz", C.BIG_TIMEOUT), ("whoami", 5)]


def test_big_request_keeps_old_retry_count(monkeypatch):
    """大块字节的请求不加重试下限：tries=2 就只试两次（产物包、快照上传不该多传）。"""
    n = []

    def urlopen(req, context=None, timeout=None):
        n.append(timeout)
        raise socket.timeout("timed out")

    monkeypatch.setattr(C.urllib.request, "urlopen", urlopen)
    w = C.WorkerSource(url="https://x", token="t")
    with pytest.raises(OSError):
        w.put_snapshot("ws", 1, b"x")
    assert n == [C.BIG_TIMEOUT, C.BIG_TIMEOUT]


def test_r2_upload_signs_with_small_timeout(monkeypatch):
    from open_guji_cv.datastore import r2
    from open_guji_cv.datastore.scope import r2_key

    data = b"img"
    sha = hashlib.sha256(data).hexdigest()
    seen = []

    def urlopen(req, context=None, timeout=None):
        path = req.full_url.split("://", 1)[1].split("/", 1)[1]
        seen.append((req.get_method(), path, timeout))
        if path == "v1/assets/sign-batch":
            if len(seen) == 1:
                raise socket.timeout("handshake")      # 第一次签名超时：重试
            return _Resp(json.dumps({"items": [{"sha256": sha, "key": r2_key(sha), "url": "https://r2/put"}]}).encode())
        return _Resp(b"")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setenv("GUJI_DATA_TOKEN", "t")
    monkeypatch.setenv("GUJI_DATA_TIMEOUT", "21")
    out = r2.upload_via_worker(None, {sha: r2.Obj(sha, len(data), "x")}, read=lambda o: data, workers=1)
    assert out == {"uploaded": 1}
    assert seen == [("POST", "v1/assets/sign-batch", 21.0), ("POST", "v1/assets/sign-batch", 21.0),
                    ("PUT", "put", 60)]
