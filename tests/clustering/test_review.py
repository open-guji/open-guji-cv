"""review 会话状态 + HTTP 服务集成测试（无浏览器）。"""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from open_guji_cv.clustering.review.server import make_handler
from open_guji_cv.clustering.review.state import ReviewSession


def _biggest_cluster(session):
    return max(session.clusters.values(), key=lambda c: c["size"])


def test_summary_and_queue(synth_book):
    s = ReviewSession(synth_book)
    summary = s.summary()
    assert summary["n_instances"] == 36
    assert summary["labeled_clusters"] == 0
    queue = s.queue()
    assert queue, "合成书应有可疑项（单例簇等）"
    # 队列按预期收益降序
    gains = [e["expected_gain"] for e in queue]
    assert gains == sorted(gains, reverse=True)


def test_confirm_updates_state_and_queue(synth_book):
    s = ReviewSession(synth_book)
    big = _biggest_cluster(s)
    cid = big["cluster_id"]
    s.post_event({"op": "confirm", "cluster": cid, "char": "甲"})
    detail = s.cluster_detail(cid)
    assert detail["label"] == "甲"
    assert all(m["label"] == "甲" for m in detail["members"])
    # 已确认簇不再进队列
    assert all(e["cluster_id"] != cid for e in s.queue())
    # 重新加载会话（重放事件流）状态一致
    s2 = ReviewSession(synth_book)
    assert s2.cluster_detail(cid)["label"] == "甲"


def test_split_and_relabel(synth_book):
    s = ReviewSession(synth_book)
    big = _biggest_cluster(s)
    cid = big["cluster_id"]
    victim = big["members"][0]
    s.post_event({"op": "split", "cluster": cid, "moved": [victim]})
    detail = s.cluster_detail(cid)
    by_id = {m["id"]: m for m in detail["members"]}
    assert by_id[victim]["removed"] is True
    assert by_id[victim]["label"] is None
    s.post_event({"op": "relabel", "instance": victim, "char": "乙"})
    assert {m["id"]: m for m in s.cluster_detail(cid)["members"]
            }[victim]["label"] == "乙"


def test_post_event_validation(synth_book):
    s = ReviewSession(synth_book)
    with pytest.raises(ValueError):
        s.post_event({"op": "confirm", "cluster": "c99999", "char": "甲"})
    with pytest.raises(ValueError):
        s.post_event({"op": "confirm",
                      "cluster": next(iter(s.clusters))})   # 缺 char
    with pytest.raises(ValueError):
        s.post_event({"op": "nope"})


def test_context_window(synth_book):
    s = ReviewSession(synth_book)
    iid = next(i for i in s.instances if i.endswith(":1:2"))  # 列中间的字
    ctx = s.context(iid, window=2)
    assert any(n["is_target"] for n in ctx["neighbors"])
    idxs = [n["idx"] for n in ctx["neighbors"]]
    assert idxs == sorted(idxs)          # 自上而下
    assert len(ctx["neighbors"]) >= 3


def test_http_roundtrip(synth_book):
    """端口起真实服务：GET 队列/簇/图块，POST 事件。"""
    session = ReviewSession(synth_book)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(session))
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    try:
        def get(path):
            with urllib.request.urlopen(base + path, timeout=5) as r:
                return r.status, r.read()

        status, body = get("/")
        assert status == 200 and b"<html" in body.lower()

        status, body = get("/api/summary")
        assert json.loads(body)["n_instances"] == 36

        status, body = get("/api/queue?limit=5")
        queue = json.loads(body)["queue"]
        assert len(queue) <= 5

        cid = queue[0]["cluster_id"]
        status, body = get(f"/api/cluster/{cid}")
        detail = json.loads(body)
        assert detail["cluster_id"] == cid

        iid = detail["members"][0]["id"]
        status, body = get(f"/img/patch/{urllib.request.quote(iid)}")
        assert status == 200 and body[:4] == b"\x89PNG"

        # POST 确认事件
        req = urllib.request.Request(
            base + "/api/event", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"op": "confirm", "cluster": cid,
                             "char": "丙"}).encode())
        with urllib.request.urlopen(req, timeout=5) as r:
            assert json.loads(r.read())["ok"] is True
        assert session.cluster_detail(cid)["label"] == "丙"

        # 非法事件 → 400
        req = urllib.request.Request(
            base + "/api/event", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"op": "confirm", "cluster": "cXXXXX",
                             "char": "丙"}).encode())
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 400
    finally:
        server.shutdown()
