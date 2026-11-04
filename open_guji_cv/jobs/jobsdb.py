"""任务库新服务器（美国机 170.106.66.156）的连接：本进程内起一条本地隧道，转进 wss://…/jobsdb。

启用条件：设了 ``JOBSDB_TOKEN``（rw 或 ro 令牌，决定能以哪个角色登录）。没设就不走这里，任务库仍连 Neon（过渡期）。
环境变量：
  JOBSDB_TOKEN        必填，桥的 Bearer 令牌（不进仓、不进聊天）
  JOBSDB_PASSWORD     必填，Postgres 口令（jobs_rw／jobs_ro 的，与令牌不是同一个）
  JOBSDB_USER         缺省 jobs_rw（ro 令牌须设 jobs_ro）
  JOBSDB_URL          缺省 wss://relay.open-guji.com/jobsdb（Cloudflare，系统 CA 校验）
  JOBSDB_CERT_SHA256  设了指纹才按指纹固定（裸 IP 自签时用）；none 表示不固定

隧道和 ``process/jobsdb_tunnel.py`` 是同一套做法：本地 TCP 字节原样放进 WebSocket 二进制帧。
外层已是 TLS，所以 Postgres 连接用 ``sslmode=disable``。依赖 ``websockets``（懒加载，只在启用时需要）。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import ssl
import sys
import threading

URL = "wss://relay.open-guji.com/jobsdb"   # 云端代理会断裸 IP＋自签证书，走 Cloudflare 域名（正规证书）
PIN = "0D:47:DD:9E:65:97:42:6A:4E:5A:A9:A7:D6:D3:C9:D0:29:E3:FA:84:B3:17:2C:E2:0A:B1:10:5E:1B:9D:33:27"
_lock = threading.Lock()
_port: int | None = None


def enabled() -> bool:
    return bool(os.environ.get("JOBSDB_TOKEN", "").strip())


def _pin() -> str | None:
    v = os.environ.get("JOBSDB_CERT_SHA256")
    if v is not None and v.strip().lower() in ("", "none", "off"):
        return None
    if v:
        return v.replace(":", "").lower()
    # 没指定：只有裸 IP（自签）才固定旧指纹；域名走系统 CA
    url = os.environ.get("JOBSDB_URL", URL)
    return PIN.replace(":", "").lower() if "170.106.66.156" in url else None


def _ctx() -> ssl.SSLContext | None:
    """域名走系统 CA 校验（不固定指纹）；JOBSDB_CERT_SHA256=none 也是这样。自签（裸 IP）时才按指纹固定。"""
    if _pin() is None:
        return ssl.create_default_context()
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE   # 不走 CA；连接后按指纹验
    return c


async def _handle(r: asyncio.StreamReader, w: asyncio.StreamWriter, tok: str) -> None:
    import websockets
    try:
        async with websockets.connect(os.environ.get("JOBSDB_URL", URL), ssl=_ctx(), max_size=2 ** 24, ping_interval=30,
                                      additional_headers={"Authorization": f"Bearer {tok}"}) as ws:
            der = ws.transport.get_extra_info("ssl_object").getpeercert(binary_form=True)
            pin = _pin()
            if pin is not None and hashlib.sha256(der).hexdigest() != pin:
                sys.stderr.write("jobsdb: 证书指纹不符，断开\n")
                return

            async def up() -> None:
                while d := await r.read(65536):
                    await ws.send(d)
                await ws.close()

            async def down() -> None:
                async for m in ws:
                    w.write(m if isinstance(m, bytes) else m.encode())
                    await w.drain()

            tasks = [asyncio.ensure_future(up()), asyncio.ensure_future(down())]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in tasks:
                t.cancel()
    except Exception as e:      # noqa: BLE001
        sys.stderr.write(f"jobsdb 隧道错误：{type(e).__name__} {str(e)[:200]}\n")
    finally:
        w.close()


def _start(port: int, tok: str) -> None:
    loop = asyncio.new_event_loop()

    async def main() -> None:
        async def handler(r, w):
            await _handle(r, w, tok)
        srv = await asyncio.start_server(handler, "127.0.0.1", port)
        async with srv:
            await srv.serve_forever()

    threading.Thread(target=lambda: loop.run_until_complete(main()), daemon=True, name="jobsdb-tunnel").start()


def _tunnel_port(tok: str) -> int:
    """本进程只起一条隧道，后续连接复用。"""
    global _port
    with _lock:
        if _port is None:
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            _port = s.getsockname()[1]
            s.close()
            _start(_port, tok)
    return _port


def connect():
    """开一条到新任务库的 psycopg 连接（调用方自己设 autocommit）。"""
    import time

    import psycopg
    tok = os.environ["JOBSDB_TOKEN"].strip()
    pw = os.environ.get("JOBSDB_PASSWORD")
    if not pw:
        raise SystemExit("要连新任务库：设 JOBSDB_PASSWORD（Postgres 口令，jobs_rw／jobs_ro 的）")
    port = _tunnel_port(tok)
    last: Exception | None = None
    for _ in range(10):        # 隧道线程刚起、或 wss 握手慢，短暂重试
        try:
            return psycopg.connect(host="127.0.0.1", port=port, dbname="jobs",
                                   user=os.environ.get("JOBSDB_USER", "jobs_rw"), password=pw,
                                   sslmode="disable", connect_timeout=20)
        except psycopg.OperationalError as e:
            last = e
            time.sleep(1.5)
    raise last  # type: ignore[misc]
