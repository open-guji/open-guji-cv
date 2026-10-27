"""读中心库的两种来源：经 guji-data Worker（HTTPS），或直连 Postgres（GUJI-606，设计第五节）。

两者给出同一组只读方法，``materialize`` / ``pull`` 只认这组方法：

- ``status()``：当前分支的全局 ``rev``；
- ``rows(table, ws, cols=None, **filters)``：一张表里某工作区的行（dict）；``cols`` 只取这几列（Worker 另带主键），
  过滤值给列表表示「取其一」（每次最多 ``MAX_IN`` 个值）；
- ``changes_since(ws, rev)``：该工作区在 ``rev`` 之后还有几条变更（``limit`` 封顶）；
- ``fetch_blobs(shas, bucket)``：按 sha 取图字节（不经本地缓存，缓存在 ``BlobCache``）。

云会话只通 443，用 ``WorkerSource``（环境变量 ``GUJI_DATA_URL``、``GUJI_DATA_TOKEN``、
``GUJI_DATA_BRANCH``）。服务器能直连 5432，也可以用 ``PgSource``（``GUJI_DATA_PG_DSN``）。
令牌只从环境变量读，不打印、不落盘。

**超时分两档**（GUJI-707）：国内节点连 data.open-guji.com 约 15% 卡在 TLS 握手（GUJI-703），原先一律 120 秒，
一次卡住就白等两分钟。现在小 JSON 请求（查表、签名、状态、whoami、分支、追加事件等：回 JSON、请求体不是大块字节）
缺省 ``SMALL_TIMEOUT`` = 25 秒（``GUJI_DATA_TIMEOUT`` 可改），超时照常走退避重试，且网络错至少重试到
``NET_TRIES`` 次；收发大块字节的（快照、备份、产物包、R2 直取图）维持 120 秒。超时是每次 socket 操作的上限，
不是整次传输的上限，大页慢慢流也不会被掐断。
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

DEFAULT_URL = "https://data.open-guji.com"
PAGE = 2000              # /v1/tables 每页条数（Worker 上限 5000；整页 events 约 7.6 MB，免费档偶尔超资源回 503/1102）
MAX_IN = 200            # 同列多值过滤一次最多几个值（Worker tables.ts 的 MAX_IN）
SIGN_BATCH = 250         # /v1/assets/sign-batch 下载每批张数（Worker 上限 1000；批大了偶尔超 CPU 回 503/1102）
BIG_TIMEOUT = 120.0      # 大块字节（快照、备份、产物包、R2 图）每次 socket 操作的超时（秒）
SMALL_TIMEOUT = 25.0     # 小 JSON 请求的缺省超时（秒），环境变量 GUJI_DATA_TIMEOUT 可改（GUJI-707）
NET_TRIES = 4            # 小请求遇到网络错（含超时）至少试这么多次，不受调用方 tries=2 限（那是给 503 拆批留的）


def default_small_timeout() -> float:
    """小 JSON 请求的超时：``GUJI_DATA_TIMEOUT``（秒，正数）或 ``SMALL_TIMEOUT``。"""
    v = os.environ.get("GUJI_DATA_TIMEOUT")
    try:
        t = float(v) if v else SMALL_TIMEOUT
    except ValueError:
        t = SMALL_TIMEOUT
    return t if t > 0 else SMALL_TIMEOUT


class CentralError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, detail=None):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.detail = status, code, detail


from ..core.workspace import EXP_BRANCH_RE, is_exp_branch  # noqa: E402,F401  搬到 core（拆分 M3）


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class WorkerSource:
    """经 guji-data Worker 读写。分支用 ``?branch=``；写接口按令牌角色由 Worker 把关。"""

    def __init__(self, url: str | None = None, token: str | None = None,
                 branch: str | None = None, timeout: float = BIG_TIMEOUT,
                 small_timeout: float | None = None):
        self.url = (url or os.environ.get("GUJI_DATA_URL") or DEFAULT_URL).rstrip("/")
        self.token = token if token is not None else os.environ.get("GUJI_DATA_TOKEN")
        if not self.token:
            raise SystemExit("缺环境变量 GUJI_DATA_TOKEN（中心库令牌；会话里一般用读令牌）")
        self.branch = branch or os.environ.get("GUJI_DATA_BRANCH") or "main"
        self.timeout = timeout                 # 大块字节
        self.small_timeout = small_timeout or default_small_timeout()   # 小 JSON（GUJI-707）
        ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
        self._ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
        self.requests = 0                      # 本进程发了几次 Worker 请求（免费档每天 10 万次）

    def describe(self) -> str:
        return f"{self.url} 分支 {self.branch}"

    # ---- HTTP ----
    def _call(self, method: str, path: str, *, query: dict | None = None, body=None,
              auth: bool = True, raw: bool = False, data: bytes | None = None,
              content_type: str = "application/octet-stream", tries: int = 5,
              timeout: float | None = None):
        """``timeout`` 不给按请求分档（见模块头）：回原始字节（``raw``）或发大块字节（``data``）的用
        ``self.timeout``，其余小 JSON 请求用 ``self.small_timeout``，网络错（含超时）至少试 ``NET_TRIES`` 次。"""
        big = raw or data is not None
        if timeout is None:
            timeout = self.timeout if big else self.small_timeout
        net_tries = tries if big else max(tries, NET_TRIES)
        url = path if path.startswith("http") else self.url + path
        if query:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query, doseq=True)
        headers = {"user-agent": "open-guji-cv-datastore"}  # Cloudflare 拦默认的 Python-urllib UA
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["content-type"] = "application/json"
        elif data is not None:
            headers["content-type"] = content_type
        if auth:
            headers["authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        last = None
        n_http = n_net = 0
        for attempt in range(max(tries, net_tries)):   # 网络抖动、429、5xx 退避重试；本模块的请求都幂等
            if n_http >= tries or n_net >= net_tries:
                break
            self.requests += 1
            try:
                with urllib.request.urlopen(req, context=self._ctx, timeout=timeout) as r:
                    payload = r.read()
                    return payload if raw else json.loads(payload or b"null")
            except urllib.error.HTTPError as e:
                payload = e.read()
                if e.code != 429 and e.code < 500:
                    try:
                        j = json.loads(payload)
                    except ValueError:
                        j = {}
                    raise CentralError(e.code, j.get("error", "http"), j.get("message", payload[:200].decode("utf-8", "replace")),
                                       j.get("detail")) from None
                last = CentralError(e.code, "http", payload[:200].decode("utf-8", "replace"))
                n_http += 1
            except (urllib.error.URLError, OSError, http.client.HTTPException) as e:  # 含 IncompleteRead（断流）、超时
                last = e
                n_net += 1
            if n_http >= tries or n_net >= net_tries:
                break
            time.sleep(min(2 ** attempt, 20))
        raise last  # type: ignore[misc]

    def _q(self, **kw) -> dict:
        return {"branch": self.branch, **kw}

    # ---- 读 ----
    def whoami(self) -> dict:
        return self._call("GET", "/v1/whoami")

    def status(self) -> int:
        return int(self._call("GET", "/v1/status", query=self._q())["rev"])

    def _tables_v2(self) -> bool:
        """Worker 认不认 ``cols`` 与同列多值（10-19 起）。旧 Worker 把多值当「同时等于」，静默回空，所以先探一次。"""
        if not hasattr(self, "_v2"):
            try:
                self._call("GET", "/v1/tables/workspaces", query=self._q(limit=1, cols="ws"), tries=2)
                self._v2 = True
            except CentralError as e:
                if e.status != 400:
                    raise
                self._v2 = False
        return self._v2

    def rows(self, table: str, ws: str | None = None, cols: Iterable[str] | None = None,
             **filters) -> Iterator[dict]:
        multi = {k: sorted({str(x) for x in v}) for k, v in filters.items() if isinstance(v, (list, tuple, set, frozenset))}
        if len(multi) > 1:
            raise ValueError(f"多值过滤一次只能一列：{sorted(multi)}")
        if multi or cols is not None:
            v2 = self._tables_v2()
            if not v2:
                cols = None                        # 旧 Worker：整行取，多值逐个查
            (k, vs), = multi.items() if multi else ((None, None),)
            if k is not None:
                if not vs:
                    return
                step = MAX_IN if v2 else 1
                for i in range(0, len(vs), step):
                    chunk = vs[i:i + step]
                    yield from self._rows(table, ws, cols, {**filters, k: chunk if v2 else chunk[0]})
                return
        yield from self._rows(table, ws, cols, filters)

    def _rows(self, table: str, ws: str | None, cols, filters: dict) -> Iterator[dict]:
        q = self._q(limit=PAGE, **filters)
        if ws is not None:
            q["ws"] = ws
        if cols is not None:
            q["cols"] = ",".join(cols)
        while True:
            try:
                page = self._call("GET", f"/v1/tables/{table}", query=q, tries=2)
            except CentralError as e:
                if e.status != 503 or q["limit"] <= 100:
                    raise
                q["limit"] //= 2                   # Worker 超资源（1102）：页减半再试
                continue
            yield from page["rows"]
            if not page.get("next"):
                return
            q["after"] = page["next"]

    def changes_since(self, ws: str, rev: int, limit: int = 1) -> int:
        page = self._call("GET", "/v1/tables/changes",
                          query=self._q(ws=ws, since_rev=int(rev), limit=limit))
        return len(page["rows"])

    def fetch_blobs(self, shas: Iterable[str], bucket: str = "main",
                    workers: int | None = None, ext: str = "png",
                    skip_missing: bool = False) -> Iterator[tuple[str, bytes | None]]:
        """每 1000 张批量签一次，再并发直取 R2。

        每个线程留着自己的 HTTPS 长连接（keep-alive），不再一张图一次握手；并发缺省 32
        （``GUJI_DATA_FETCH_WORKERS`` 可改）。正式桶的签名直链是公开域名 blob.open-guji.com（10-19 起），下载不算 Worker 请求；实验桶仍指向 Worker 的 /v1/blob，每张图算一次。
        10-19 实测（云端，2KB 小图）：旧法 8 线程无长连接约 30 张/秒，长连接 32 线程约 150 张/秒。

        ``skip_missing``：R2 里确实没有（404）的图不报错，回 ``(sha, None)`` 由调用方记下。"""
        shas = sorted(set(shas))
        workers = workers or int(os.environ.get("GUJI_DATA_FETCH_WORKERS") or 32)
        getter = _KeepAliveGetter(self._ctx)
        # 实验分支：库是从 main 分出来的，老图在正式桶，实验里新传的图在实验桶。正式桶 404 的再去实验桶取。
        fallback = "exp" if bucket == "main" and self.branch.startswith("exp/") else None

        def one(urls: dict, sha: str) -> tuple[str, bytes]:
            try:
                return sha, getter.get(urls[sha])
            except CentralError as e:
                if e.status not in (403, 404):
                    raise
                if fallback is None:
                    if skip_missing and e.status == 404:
                        return sha, None
                    raise
                try:
                    return sha, getter.get(self._sign_get(fallback, [sha], ext)[sha])
                except CentralError as e2:
                    if skip_missing and e2.status == 404:
                        return sha, None
                    raise

        with ThreadPoolExecutor(workers) as ex:
            for i in range(0, len(shas), SIGN_BATCH):
                chunk = shas[i:i + SIGN_BATCH]
                urls = self._sign_get(bucket, chunk, ext)
                yield from ex.map(partial(one, urls), chunk)

    def _sign_get(self, bucket: str, shas: list[str], ext: str = "png") -> dict[str, str]:
        if not getattr(self, "_no_batch", False):
            try:
                signed = self._call("POST", "/v1/assets/sign-batch", tries=2,
                                    body={"bucket": bucket, "op": "get", "ext": ext, "sha256s": shas})
                return {it["sha256"]: it["url"] for it in signed["items"]}
            except CentralError as e:
                if e.status == 503 and len(shas) > 25:  # Worker 超资源（1102）：对半拆开再签
                    h = len(shas) // 2
                    return {**self._sign_get(bucket, shas[:h], ext), **self._sign_get(bucket, shas[h:], ext)}
                if e.status != 404 or e.code != "not_found":
                    raise
                self._no_batch = True          # 旧版 Worker 没有批量签名：退回逐张签
        return {s: self._call("POST", "/v1/assets/sign",
                              body={"bucket": bucket, "op": "get", "ext": ext, "sha256": s})["url"] for s in shas}

    # ---- 工作区快照（R2，省 Neon 流量；只当缓存，用的人逐文件核 sha）----
    def get_snapshot(self, ws: str) -> tuple[int, bytes] | None:
        """该分支上工作区 ``ws`` 最新的快照 (rev, tar.gz 字节)；没有或 Worker 不支持返回 None。"""
        url = f"{self.url}/v1/snapshots/{urllib.parse.quote(ws)}?" + urllib.parse.urlencode({"branch": self.branch})
        req = urllib.request.Request(url, headers={"user-agent": "open-guji-cv-datastore",
                                                   "authorization": f"Bearer {self.token}"})
        self.requests += 1
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=self.timeout) as r:
                return int(r.headers.get("x-guji-rev") or 0), r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404):
                return None
            raise

    def put_snapshot(self, ws: str, rev: int, data: bytes) -> dict:
        return self._call("PUT", f"/v1/snapshots/{urllib.parse.quote(ws)}",
                          query=self._q(rev=int(rev)), data=data, content_type="application/gzip", tries=2)

    # ---- 分支与写 ----
    def branches(self) -> list[dict]:
        return self._call("GET", "/v1/branches")["branches"]

    def create_branch(self, name: str, from_rev: int | None = None) -> dict:
        body = {"name": name, **({"from_rev": int(from_rev)} if from_rev is not None else {})}
        return self._call("POST", "/v1/branches", body=body)

    def delete_branch(self, name: str) -> dict:
        return self._call("DELETE", "/v1/branches", query={"name": name})

    def append_events(self, ws: str, src_path: str, lines: list[str], branch: str | None = None) -> dict:
        return self._call("POST", "/v1/events", query={"branch": branch or self.branch},
                          body={"ws": ws, "src_path": src_path, "lines": lines})


    # ---- 备份（GUJI-611，正式令牌）----
    def put_backup(self, day: str, name: str, data: bytes, content_type: str) -> dict:
        return self._call("PUT", f"/v1/backups/{day}/{name}", data=data, content_type=content_type)

    def list_backups(self) -> list[dict]:
        return self._call("GET", "/v1/backups")["dates"]

    def get_backup(self, day: str, name: str) -> bytes:
        return self._call("GET", f"/v1/backups/{day}/{name}", raw=True)

    def delete_backup(self, day: str) -> dict:
        return self._call("DELETE", f"/v1/backups/{day}")


class _KeepAliveGetter:
    """多线程 GET：每个线程按主机留一条 HTTPS 长连接，断了就重连；走系统代理（CONNECT 隧道）。

    重试同 ``WorkerSource._call``：网络错、429、5xx 退避重试，最多 5 次；别的状态码直接报错。"""

    def __init__(self, ctx: ssl.SSLContext, timeout: float = 120):
        self.ctx, self.timeout = ctx, timeout
        self.local = threading.local()

    def _conn(self, scheme: str, host: str, port: int) -> http.client.HTTPConnection:
        conns = self.local.__dict__.setdefault("conns", {})
        c = conns.get((scheme, host, port))
        if c is None and scheme == "http":             # 只有本机测试用 http
            c = http.client.HTTPConnection(host, port, timeout=self.timeout)
            conns[(scheme, host, port)] = c
        elif c is None:
            px = urllib.request.getproxies().get("https")
            if px and not urllib.request.proxy_bypass(host):
                pu = urllib.parse.urlsplit(px if "//" in px else "http://" + px)
                c = http.client.HTTPSConnection(pu.hostname, pu.port or 80, context=self.ctx, timeout=self.timeout)
                hdrs = {}
                if pu.username:
                    cred = f"{urllib.parse.unquote(pu.username)}:{urllib.parse.unquote(pu.password or '')}"
                    hdrs["Proxy-Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
                c.set_tunnel(host, port, headers=hdrs)
            else:
                c = http.client.HTTPSConnection(host, port, context=self.ctx, timeout=self.timeout)
            conns[(scheme, host, port)] = c
        return c

    def _drop(self, key: tuple) -> None:
        c = self.local.__dict__.get("conns", {}).pop(key, None)
        if c is not None:
            c.close()

    def get(self, url: str) -> bytes:
        u = urllib.parse.urlsplit(url)
        key = (u.scheme, u.hostname, u.port or (80 if u.scheme == "http" else 443))
        path = u.path + ("?" + u.query if u.query else "")
        last: Exception | None = None
        for attempt in range(5):
            try:
                c = self._conn(*key)
                c.request("GET", path, headers={"user-agent": "open-guji-cv-datastore"})
                r = c.getresponse()
                data = r.read()
                if r.will_close:
                    self._drop(key)
                if r.status == 200:
                    return data
                if r.status != 429 and r.status < 500:
                    raise CentralError(r.status, "http", data[:200].decode("utf-8", "replace"))
                last = CentralError(r.status, "http", data[:200].decode("utf-8", "replace"))
            except (OSError, http.client.HTTPException) as e:   # 连接断了：丢掉重连
                self._drop(key)
                last = e
                if attempt == 0 and isinstance(e, (http.client.RemoteDisconnected, ConnectionResetError,
                                                   BrokenPipeError)):
                    continue                           # 闲置长连接被对端关了：立刻重连，不等
            time.sleep(min(2 ** attempt, 20))
        raise last  # type: ignore[misc]


class PgSource:
    """直连 Postgres（服务器、测试用）。只读；``search_path`` 由连接决定。"""

    def __init__(self, conn, branch: str = "main"):
        self.conn = conn
        self.branch = branch

    def describe(self) -> str:
        return f"Postgres（{self.branch}）"

    def status(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT to_regclass('changes')::text")
        if not cur.fetchone()[0]:
            return 0
        cur.execute("SELECT coalesce(max(rev), 0) FROM changes")
        return int(cur.fetchone()[0])

    def rows(self, table: str, ws: str | None = None, cols: Iterable[str] | None = None,
             **filters) -> Iterator[dict]:
        from psycopg import sql
        conds, args = [], []
        if ws is not None:
            filters = {"ws": ws, **filters}
        for k, v in filters.items():
            if isinstance(v, (list, tuple, set, frozenset)):
                conds.append(sql.SQL("{}::text = ANY(%s)").format(sql.Identifier(k)))
                args.append([str(x) for x in v])
            else:
                conds.append(sql.SQL("{}::text = %s").format(sql.Identifier(k)))
                args.append(str(v))
        what = sql.SQL("*") if cols is None else sql.SQL(", ").join(map(sql.Identifier, cols))
        q = sql.SQL("SELECT {} FROM {}").format(what, sql.Identifier(table))
        if conds:
            q += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conds)
        cur = self.conn.cursor()
        cur.execute(q, args)
        names = [d.name for d in cur.description]
        for r in cur.fetchall():
            yield dict(zip(names, r))

    def changes_since(self, ws: str, rev: int, limit: int = 1) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT count(*) FROM (SELECT 1 FROM changes WHERE ws = %s AND rev > %s LIMIT %s) t",
                    (ws, int(rev), limit))
        return int(cur.fetchone()[0])

    def fetch_blobs(self, shas, bucket: str = "main", workers: int = 8, ext: str = "png",
                    skip_missing: bool = False):
        raise CentralError(0, "no_blobs", "直连 Postgres 拿不到图：图在 R2，请经 Worker（GUJI_DATA_TOKEN）或预先填好本地缓存")


class BlobCache:
    """本地图缓存：``<根>/sha256/<前两位>/<sha>.png``，按 sha 去重，取回时核 sha。

    根目录：``GUJI_DATA_CACHE``，缺省 ``~/.cache/guji-data``。
    """

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("GUJI_DATA_CACHE") or Path.home() / ".cache" / "guji-data")

    def path(self, sha: str) -> Path:
        return self.root / "sha256" / sha[:2] / f"{sha}.png"

    def has(self, sha: str) -> bool:
        return self.path(sha).exists()

    def put(self, sha: str, data: bytes) -> Path:
        if _sha(data) != sha:
            raise CentralError(0, "sha_mismatch", f"下载的图 sha 不符：{sha}")
        p = self.path(sha)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".tmp{os.getpid()}")
        tmp.write_bytes(data)
        tmp.replace(p)
        return p

    def ensure(self, src, shas: Iterable[str], bucket: str = "main", ext: str = "png") -> dict:
        """把缺的图（``ext`` 是 R2 键后缀：图 png，整理本 txt）拉进缓存。返回 {have, fetched, missing}。

        R2 里没有的图（库引用了、桶里 404）缺省跳过并报告：``missing`` 是它们的 sha 列表，并在 stderr 打一行。
        ``GUJI_DATA_MISSING_BLOBS=error`` 恢复成遇到就停。
        缓存只按 sha 存，文件名一律 ``.png``（内容相同 sha 就相同，与后缀无关）。"""
        want = sorted(set(shas))
        missing = [s for s in want if not self.has(s)]
        t0 = time.time()
        strict = os.environ.get("GUJI_DATA_MISSING_BLOBS", "").lower() == "error"
        absent: list[str] = []
        for n, (sha, data) in enumerate(
                src.fetch_blobs(missing, bucket=bucket, ext=ext, skip_missing=not strict) if missing else (), 1):
            if data is None:
                absent.append(sha)
                continue
            self.put(sha, data)
            if n % 2000 == 0 or (n == len(missing) and n >= 2000):   # 大批量时报进度，免得像卡住
                print(f"  取图 {n}/{len(missing)}（{n / max(time.time() - t0, 1e-6):.0f} 张/秒）",
                      file=sys.stderr, flush=True)
        if absent:
            print(f"  ！R2 上找不到 {len(absent)} 张图（已跳过，本地缺这些文件）：{', '.join(absent[:5])}…",
                  file=sys.stderr, flush=True)
        return {"have": len(want) - len(missing), "fetched": len(missing) - len(absent), "missing": absent}
