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


def test_queue_low_conf_sort(synth_book):
    """低置信排序：候选首选置信度升序（先审最没把握的簇）。"""
    s = ReviewSession(synth_book)
    q = s.queue(sort="low_conf")
    assert q, "应有可疑簇"
    ps = [e["top_p"] for e in q]
    assert ps == sorted(ps)
    assert all("top_p" in e and "candidates" in e for e in q)


def test_context_compact_seven_chars(synth_book):
    """简略模式：目标字上下各 3，最多 7 字，自上而下有序。"""
    s = ReviewSession(synth_book)
    iid = next(i for i in s.instances if i.endswith(":1:3"))
    ctx = s.context(iid, mode="compact", window=3)
    assert ctx["mode"] == "compact"
    assert len(ctx["neighbors"]) <= 7
    assert sum(n["is_target"] for n in ctx["neighbors"]) == 1
    idxs = [n["idx"] for n in ctx["neighbors"]]
    assert idxs == sorted(idxs)


def test_context_full_three_cols_each_side(synth_book):
    """完整模式：目标列 + 前后各 3 列的完整内容，列号升序（=从右到左）。"""
    s = ReviewSession(synth_book)
    # 中间列（合成书 3 列，取第 2 列保证两侧都有列）
    iid = next(i for i in s.instances if ":2:" in i)
    ctx = s.context(iid, mode="full", col_window=3)
    assert ctx["mode"] == "full"
    cols = ctx["columns"]
    assert [c["col"] for c in cols] == sorted(c["col"] for c in cols)
    assert sum(c["is_target_col"] for c in cols) == 1
    target_col = next(c for c in cols if c["is_target_col"])
    # 完整列：包含该列全部实例
    n_col = sum(1 for i in s.instances.values()
                if i.page == s.instances[iid].page
                and i.col == s.instances[iid].col)
    assert len(target_col["chars"]) == n_col
    assert sum(n["is_target"] for n in target_col["chars"]) == 1


def test_user_review_interaction_flow(synth_book):
    """端到端用户交互流（HTTP）：低置信队列 → 簇详情（候选可见）→
    简略上下文 → 完整上下文 → 确认 → 队列移除该簇。"""
    session = ReviewSession(synth_book)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(session))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        def get(path):
            with urllib.request.urlopen(base + path, timeout=5) as r:
                return json.loads(r.read())

        # 1. 用户选"按置信度"排序拉队列
        queue = get("/api/queue?sort=low_conf&limit=10")["queue"]
        assert queue
        target = queue[0]
        assert "candidates" in target          # 队列项直接可见候选

        # 2. 打开簇：看到全部候选与成员
        detail = get(f"/api/cluster/{target['cluster_id']}")
        assert detail["candidates"] is not None
        iid = detail["members"][0]["id"]

        # 3. 简略上下文（±3 字）
        ctx = get(f"/api/context/{urllib.request.quote(iid)}?mode=compact")
        assert ctx["mode"] == "compact" and len(ctx["neighbors"]) <= 7

        # 4. 完整上下文（±3 列）
        ctx = get(f"/api/context/{urllib.request.quote(iid)}?mode=full")
        assert ctx["mode"] == "full" and ctx["columns"]

        # 5. 确认标签
        req = urllib.request.Request(
            base + "/api/event", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"op": "confirm",
                             "cluster": target["cluster_id"],
                             "char": "丁"}).encode())
        with urllib.request.urlopen(req, timeout=5) as r:
            assert json.loads(r.read())["ok"]

        # 6. 已确认簇从队列消失
        queue2 = get("/api/queue?sort=low_conf&limit=50")["queue"]
        assert all(e["cluster_id"] != target["cluster_id"] for e in queue2)
    finally:
        server.shutdown()


def test_flag_cluster_lifecycle(synth_book):
    """簇级问题标记：入队排除 → 详情可见 → clear 恢复。"""
    s = ReviewSession(synth_book)
    cid = s.queue()[0]["cluster_id"]
    s.post_event({"op": "flag", "cluster": cid, "flag": "truncated"})
    assert s.cluster_detail(cid)["flag"] == "truncated"
    assert all(e["cluster_id"] != cid for e in s.queue())
    assert s.summary()["flagged_clusters"] == 1
    # 清除后重新入队
    s.post_event({"op": "flag", "cluster": cid, "flag": "clear"})
    assert s.cluster_detail(cid)["flag"] is None
    assert any(e["cluster_id"] == cid for e in s.queue())
    # 非法取值/未知簇
    with pytest.raises(ValueError):
        s.post_event({"op": "flag", "cluster": cid, "flag": "nope"})
    with pytest.raises(ValueError):
        s.post_event({"op": "flag", "cluster": "c99999", "flag": "impure"})
