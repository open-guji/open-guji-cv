"""本地 TCP ↔ Neon WebSocket 桥：在只通 443 的环境（云会话）里让 psycopg 连 Neon。

Neon 的每个计算端点都在 ``wss://<端点 host>/v2`` 上收 Postgres 线协议（serverless 驱动用的就是它），
TLS 在 wss 这一层。桥把本地端口收到的字节原样转进 WebSocket，所以导入、核对的代码一行不改，
事务、COPY、临时表都照常。

    python -m open_guji_cv.datastore.wsbridge ep-xxxx.c-3.us-west-2.aws.neon.tech --port 15432 &
    export GUJI_DATA_PG_DSN="host=127.0.0.1 port=15432 dbname=neondb user=… password=… \\
        sslmode=disable options=endpoint=ep-xxxx"

连本地端口要 ``sslmode=disable``（加密已由 wss 负责）、不能要 channel_binding；
``options=endpoint=<端点 id>`` 照 Neon 的约定带上。能直连 5432 的机器（服务器）不需要这个桥。
只监听 127.0.0.1。依赖 ``websockets``（extra ``datastore``）。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import ssl
import sys


def _ssl_ctx() -> ssl.SSLContext:
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    return ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()


async def _serve(host: str, port: int) -> None:
    import websockets
    ctx = _ssl_ctx()

    async def handle(reader, writer):
        try:
            async with websockets.connect(f"wss://{host}/v2", ssl=ctx, max_size=None,
                                          compression=None, ping_interval=20) as ws:
                async def up():
                    while data := await reader.read(65536):
                        await ws.send(data)
                    await ws.close()

                async def down():
                    async for msg in ws:
                        writer.write(msg if isinstance(msg, bytes) else msg.encode())
                        await writer.drain()

                await asyncio.gather(up(), down())
        except Exception as e:  # 单个连接出错不影响别的连接
            print(f"wsbridge: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        finally:
            writer.close()

    srv = await asyncio.start_server(handle, "127.0.0.1", port)
    print(f"wsbridge: 127.0.0.1:{port} → wss://{host}/v2", file=sys.stderr, flush=True)
    async with srv:
        await srv.serve_forever()


def start_in_thread(host: str) -> int:
    """在后台线程起一个桥，返回本地端口（``guji db push`` 在只通 443 的会话里自动用）。"""
    import socket
    import threading
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    ready = threading.Event()

    def run():
        async def go():
            srv_task = asyncio.ensure_future(_serve(host, port))
            await asyncio.sleep(0.2)
            ready.set()
            await srv_task
        asyncio.run(go())

    threading.Thread(target=run, daemon=True, name="wsbridge").start()
    ready.wait(10)
    return port


def neon_dsn_via_bridge(url: str) -> str:
    """把 ``NEON_DATABASE_URL`` 换成经本地桥的 DSN（口令只在内存里）。"""
    import urllib.parse as u
    p = u.urlparse(url)
    host = p.hostname
    endpoint = host.split(".")[0].removesuffix("-pooler")
    port = start_in_thread(host.replace("-pooler", ""))
    db = (p.path or "/neondb").lstrip("/") or "neondb"
    from psycopg.conninfo import make_conninfo
    return make_conninfo(host="127.0.0.1", port=port, dbname=db, user=u.unquote(p.username or ""),
                         password=u.unquote(p.password or ""), sslmode="disable",
                         options=f"endpoint={endpoint}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m open_guji_cv.datastore.wsbridge")
    ap.add_argument("host", help="Neon 端点 host（不含口令）")
    ap.add_argument("--port", type=int, default=15432)
    a = ap.parse_args(argv)
    asyncio.run(_serve(a.host, a.port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
