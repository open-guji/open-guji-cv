"""审查界面本地 HTTP 服务。

路由：
    GET  /                          前端单页
    GET  /api/summary               进度概览
    GET  /api/queue?reason=&limit=  审查队列（簇级聚合）
    GET  /api/cluster/<id>          簇详情
    GET  /api/context/<instance>    实例上下文（同列前后字）
    GET  /img/patch/<instance>      单字图块 PNG
    GET  /img/montage/<cluster>     簇蒙太奇 PNG
    POST /api/event                 追加标签事件（confirm/relabel/split/merge/mark）
"""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .state import ReviewSession

HTML_PATH = Path(__file__).parent / "static" / "index.html"


def make_handler(session: ReviewSession):
    class ReviewHandler(BaseHTTPRequestHandler):
        # ── 基础 ─────────────────────────────────────────

        def log_message(self, fmt, *args):   # 静默访问日志
            pass

        def _send_json(self, obj, status: int = 200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str):
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _not_found(self, msg: str = "not found"):
            self._send_json({"error": msg}, status=404)

        # ── GET ─────────────────────────────────────────

        def do_GET(self):
            url = urlparse(self.path)
            parts = [unquote(p) for p in url.path.split("/") if p]
            try:
                if not parts:
                    return self._send_file(HTML_PATH, "text/html; charset=utf-8")
                if parts[0] == "api":
                    return self._api_get(parts[1:], parse_qs(url.query))
                if parts[0] == "img":
                    return self._img(parts[1:])
                self._not_found()
            except KeyError as e:
                self._not_found(str(e))
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)

        def _api_get(self, parts: list[str], query: dict):
            if parts == ["summary"]:
                return self._send_json(session.summary())
            if parts == ["queue"]:
                reason = query.get("reason", [None])[0]
                limit = int(query.get("limit", ["50"])[0])
                return self._send_json(
                    {"queue": session.queue(reason=reason, limit=limit)})
            if len(parts) == 2 and parts[0] == "cluster":
                return self._send_json(session.cluster_detail(parts[1]))
            if len(parts) == 2 and parts[0] == "context":
                return self._send_json(session.context(parts[1]))
            self._not_found()

        def _img(self, parts: list[str]):
            if len(parts) != 2:
                return self._not_found()
            kind, key = parts
            path = (session.patch_file(key) if kind == "patch"
                    else session.montage_file(key) if kind == "montage"
                    else None)
            if path is None:
                return self._not_found(f"{kind}/{key}")
            self._send_file(path, "image/png")

        # ── POST ────────────────────────────────────────

        def do_POST(self):
            url = urlparse(self.path)
            if url.path != "/api/event":
                return self._not_found()
            try:
                length = int(self.headers.get("Content-Length", "0"))
                event = json.loads(self.rfile.read(length) or b"{}")
                written = session.post_event(event)
                self._send_json({"ok": True, "event": written})
            except ValueError as e:
                self._send_json({"error": str(e)}, status=400)
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)

    return ReviewHandler


def start_review_server(book_out_dir: str | Path, port: int = 8633,
                        open_browser: bool = True) -> None:
    session = ReviewSession(book_out_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(session))
    url = f"http://127.0.0.1:{port}/"
    print(f"审查界面: {url}")
    print(f"标签事件写入: {session.labels_path}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
