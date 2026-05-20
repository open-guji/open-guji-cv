"""HTTP 服务器：API 路由、SSE 推送、文件服务。"""

import json
import mimetypes
import os
import platform
import string
import time
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

from .runner import CommandRunner

# index.html 路径（支持 PyInstaller 打包）
_web_dir = os.environ.get('GUJI_CV_WEB_DIR', str(Path(__file__).parent))
HTML_PATH = Path(_web_dir) / "index.html"

# 全局命令运行器
runner = CommandRunner()

# 可用命令定义
COMMANDS = [
    {
        "id": "cut",
        "name": "页面切分",
        "description": "检测切分类型并执行切分",
        "options": [],
    },
    {
        "id": "recognize-profile",
        "name": "版面识别",
        "description": "分析版式特征，生成 profile.json",
        "options": [],
    },
    {
        "id": "preprocess",
        "name": "预处理",
        "description": "图像预处理（裁剪/增强/二值化）",
        "options": [
            {"id": "profile", "type": "file", "label": "Profile 文件", "required": False},
            {"id": "range", "type": "text", "label": "页码范围", "placeholder": "如 1-5 或 1,3,5", "required": False},
        ],
    },
    {
        "id": "extract",
        "name": "信息提取",
        "description": "版面检测 + 字符网格识别",
        "options": [
            {"id": "profile", "type": "file", "label": "Profile 文件", "required": False},
            {"id": "range", "type": "text", "label": "页码范围", "placeholder": "如 1-5", "required": False},
            {"id": "steps", "type": "select", "label": "子步骤",
             "choices": [("all", "全部"), ("layout", "仅版面检测"), ("grid", "仅字符网格")], "default": "all"},
        ],
    },
    {
        "id": "run",
        "name": "完整流程",
        "description": "analyze → preprocess → extract 一键运行",
        "options": [
            {"id": "range", "type": "text", "label": "页码范围", "placeholder": "如 1-5", "required": False},
        ],
    },
]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}


class Handler(BaseHTTPRequestHandler):
    """HTTP 请求处理器。"""

    def log_message(self, format, *args):
        pass  # 静默日志

    # ────────────────── 响应工具 ──────────────────

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        mime, _ = mimetypes.guess_type(str(path))
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", len(data))
        if mime and mime.startswith("image/"):
            self.send_header("Cache-Control", "max-age=60")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, path: Path):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def _get_params(self) -> dict:
        parsed = urlparse(self.path)
        return {k: v[0] for k, v in parse_qs(parsed.query).items()}

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8")) if body else {}

    # ────────────────── GET 路由 ──────────────────

    def do_GET(self):
        path = unquote(urlparse(self.path).path)

        if path == "/" or path == "/index.html":
            self._send_html(HTML_PATH)
        elif path == "/api/defaults":
            self._handle_defaults()
        elif path == "/api/browse":
            self._handle_browse()
        elif path == "/api/jobs":
            self._send_json(runner.list_jobs())
        elif path.startswith("/api/progress/"):
            job_id = path.split("/")[-1]
            self._handle_sse(job_id)
        elif path == "/api/files":
            self._handle_files()
        elif path == "/api/file":
            self._handle_file()
        else:
            self.send_error(404)

    # ────────────────── POST 路由 ──────────────────

    def do_POST(self):
        path = unquote(urlparse(self.path).path)

        if path == "/api/run":
            self._handle_run()
        elif path.startswith("/api/jobs/") and path.endswith("/cancel"):
            job_id = path.split("/")[-2]
            ok = runner.cancel(job_id)
            self._send_json({"ok": ok})
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ────────────────── API 处理 ──────────────────

    def _handle_defaults(self):
        self._send_json({
            "commands": COMMANDS,
            "default_output": str(Path.cwd() / "output"),
        })

    def _handle_browse(self):
        params = self._get_params()
        req_path = params.get("path", "")

        # Windows 盘符列表
        drives = []
        if platform.system() == "Windows":
            drives = [f"{d}:/" for d in string.ascii_uppercase
                      if Path(f"{d}:/").exists()]

        if not req_path:
            # 返回盘符列表 (Windows) 或根目录
            if drives:
                self._send_json({
                    "current": "",
                    "parent": "",
                    "entries": [{"name": d, "type": "drive"} for d in drives],
                    "drives": drives,
                })
            else:
                self._send_json({
                    "current": "/",
                    "parent": "/",
                    "entries": self._list_dir(Path("/")),
                    "drives": [],
                })
            return

        p = Path(req_path).resolve()
        if not p.exists():
            self._send_json({"error": f"路径不存在: {req_path}"}, 404)
            return

        parent = str(p.parent) if str(p) != str(p.parent) else ""

        self._send_json({
            "current": str(p),
            "parent": parent,
            "entries": self._list_dir(p) if p.is_dir() else [],
            "drives": drives,
        })

    def _list_dir(self, p: Path) -> list:
        entries = []
        try:
            for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    if item.name.startswith("."):
                        continue
                    entry = {"name": item.name}
                    if item.is_dir():
                        entry["type"] = "dir"
                    else:
                        entry["type"] = "file"
                        entry["size"] = item.stat().st_size
                        entry["ext"] = item.suffix.lower()
                    entries.append(entry)
                except (PermissionError, OSError):
                    continue
        except PermissionError:
            pass
        return entries

    def _handle_run(self):
        data = self._read_body()
        command = data.get("command")
        input_path = data.get("input_path")
        output_path = data.get("output_path", "output")
        options = data.get("options", {})

        if not command or not input_path:
            self._send_json({"error": "缺少 command 或 input_path"}, 400)
            return

        job_id = runner.start(command, input_path, output_path, options)
        self._send_json({"job_id": job_id, "status": "started"})

    def _handle_sse(self, job_id: str):
        """Server-Sent Events 流式推送任务进度。"""
        job = runner.get_job(job_id)
        if not job:
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        last_index = 0
        heartbeat_interval = 15  # 秒
        last_heartbeat = time.time()

        try:
            while True:
                # 发送新日志行
                new_lines = job.lines[last_index:]
                for entry in new_lines:
                    self.wfile.write(f"data: {json.dumps(entry, ensure_ascii=False)}\n\n".encode())
                last_index += len(new_lines)

                # 发送进度
                if job.progress:
                    prog = {"type": "progress", **job.progress}
                    self.wfile.write(f"data: {json.dumps(prog, ensure_ascii=False)}\n\n".encode())

                self.wfile.flush()

                # 任务结束
                if job.status in ("completed", "failed", "cancelled"):
                    final = {
                        "type": "complete",
                        "status": job.status,
                        "exit_code": job.exit_code,
                        "duration": round(job.finished_at - job.started_at, 1) if job.finished_at else 0,
                        "output_dir": job.output_path,
                    }
                    self.wfile.write(f"data: {json.dumps(final, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
                    break

                # 心跳防超时
                now = time.time()
                if now - last_heartbeat > heartbeat_interval:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    last_heartbeat = now

                time.sleep(0.3)

        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_files(self):
        params = self._get_params()
        req_path = params.get("path", "")
        if not req_path:
            self._send_json({"error": "缺少 path"}, 400)
            return

        p = Path(req_path).resolve()
        if not p.exists():
            self._send_json({"error": f"路径不存在"}, 404)
            return

        if p.is_file():
            self._send_json({
                "type": "file",
                "path": str(p),
                "name": p.name,
                "size": p.stat().st_size,
                "ext": p.suffix.lower(),
            })
        else:
            entries = self._list_dir(p)
            # 统计图片数量
            image_count = sum(1 for e in entries if e.get("ext") in IMAGE_EXTS)
            self._send_json({
                "type": "dir",
                "path": str(p),
                "name": p.name,
                "entries": entries,
                "image_count": image_count,
            })

    def _handle_file(self):
        params = self._get_params()
        req_path = params.get("path", "")
        if not req_path:
            self.send_error(400)
            return

        p = Path(req_path).resolve()
        if not p.exists() or not p.is_file():
            self.send_error(404)
            return

        # JSON 文件直接返回 JSON
        if p.suffix.lower() == ".json":
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                self._send_json(data)
            except Exception:
                self._send_file(p)
        else:
            self._send_file(p)


def start_server(port: int = 8632, open_browser: bool = True):
    """启动 Web 服务器。"""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}"
    print(f"古籍 CV 工具台已启动: {url}")
    print("按 Ctrl+C 停止")

    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()
