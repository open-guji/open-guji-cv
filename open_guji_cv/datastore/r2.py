"""刻例图与锚图上 R2，按 sha256 内容寻址（GUJI-605，设计 3.2 节）。

对象键 ``sha256/<前两位>/<sha>.png``：只增不改，同一张图不论来自哪个工作区、哪个实例都只存一份。

默认只出计划（dry-run）：从 guji-workspace 某个提交里列出要传的图、去重、算总数与总字节，
可选再和中心库里的 ``glyph_instances.patch_sha`` / ``anchor_patches_meta`` 对一遍。
真上传要 ``--execute`` 且环境里有 R2 凭据；先 HEAD，已有就跳过，所以重复上传不产生新对象。

凭据只从环境变量读：``R2_ACCOUNT_ID``、``R2_ACCESS_KEY_ID``、``R2_SECRET_ACCESS_KEY``；
桶名 ``R2_BUCKET``（正式 guji-assets，实验 guji-assets-exp）。不进仓、不打印。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import gitsource
from .scope import GS, classify, r2_key, sha256


@dataclass
class Obj:
    sha: str
    bytes: int
    oid: str                                   # 任取一个来源的 blob id（内容相同）
    sources: list[str] = field(default_factory=list)   # ws:相对路径


def plan_commit(repo, commit: str = "HEAD") -> tuple[str, dict[str, Obj], dict]:
    """返回（提交, {sha: Obj}, 统计）。只收被实例引用的刻例图（与导入口径相同）和全部锚图。"""
    commit = gitsource.resolve(repo, commit)
    tree = gitsource.list_tree(repo, commit)
    reader = gitsource.BlobReader(repo)
    objs: dict[str, Obj] = {}
    stats = Counter()
    try:
        for d, files in gitsource.workspaces_in_tree(tree).items():
            blobs = {rel: oid for rel, oid in files if oid}
            referenced = _referenced_patches(reader, blobs)
            for rel, oid in sorted(blobs.items()):
                kind = classify(rel)
                if kind == "patch":
                    if rel not in referenced:
                        stats["patch_unreferenced"] += 1
                        continue
                    stats["glyph_patches"] += 1
                elif kind == "anchor_patches_meta":
                    stats["anchor_patches"] += 1
                else:
                    continue
                data = reader.read(oid)
                sha = sha256(data)
                stats["source_files"] += 1
                stats["source_bytes"] += len(data)
                o = objs.setdefault(sha, Obj(sha, len(data), oid))
                o.sources.append(f"{d}:{rel}")
    finally:
        reader.close()
    stats["objects"] = len(objs)
    stats["object_bytes"] = sum(o.bytes for o in objs.values())
    return commit, objs, dict(stats)


def _referenced_patches(reader, blobs: dict[str, str]) -> set[str]:
    out = set()
    for rel, oid in blobs.items():
        if classify(rel) != "glyph_instances":
            continue
        for line in reader.read(oid).decode("utf-8").splitlines():
            if line.strip():
                iid = json.loads(line)["instance_id"]
                out.add(f"{GS}patches/{iid.replace(':', '_')}.png")
    return out


def check_against_db(conn, objs: dict[str, Obj]) -> dict:
    """计划里的 sha 与库里记的 sha 是否同一集合。"""
    cur = conn.cursor()
    cur.execute("SELECT patch_sha FROM glyph_instances WHERE patch_sha IS NOT NULL "
                "UNION SELECT sha256 FROM anchor_patches_meta")
    db = {r[0] for r in cur.fetchall()}
    plan = set(objs)
    return {"db_distinct_sha": len(db), "plan_objects": len(plan),
            "in_db_not_plan": sorted(db - plan)[:20], "in_plan_not_db": sorted(plan - db)[:20],
            "match": db == plan}


def write_manifest(objs: dict[str, Obj], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps({"key": r2_key(o.sha), "sha256": o.sha, "bytes": o.bytes,
                                "sources": o.sources}, ensure_ascii=False) + "\n" for o in sorted(objs.values(), key=lambda o: o.sha))


def _client():
    need = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    miss = [k for k in need if not os.environ.get(k)]
    if miss:
        raise SystemExit(f"缺环境变量 {', '.join(miss)}，不能上传（dry-run 不需要）")
    import boto3  # 只有真上传才要
    s3 = boto3.client(
        "s3", region_name="auto",
        endpoint_url=os.environ.get("R2_ENDPOINT")       # 只给本地 S3 模拟器测试用
        or f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"])
    return s3, os.environ["R2_BUCKET"]


def upload_via_worker(repo, objs: dict[str, Obj], bucket: str = "exp", workers: int = 8,
                      limit: int | None = None) -> dict:
    """经 guji-data Worker 传：POST /v1/assets/sign → 已有就跳过，否则 PUT 到返回的 url。

    要 ``GUJI_DATA_TOKEN``（exp 令牌只能传 exp 桶，main 桶要正式令牌）；地址默认
    https://data.open-guji.com（``GUJI_DATA_URL`` 可改）。Worker 端核 sha256，不符回 400。
    先用 ``/v1/assets/sign-batch`` 每 200 张签一次（已有的跳过），再逐张 PUT；
    旧版 Worker 没有批量接口就退回逐张签。``limit`` 用来分批。
    """
    import ssl
    import time
    import urllib.error
    import urllib.request
    token = os.environ.get("GUJI_DATA_TOKEN")
    if not token:
        raise SystemExit("缺环境变量 GUJI_DATA_TOKEN，不能上传（dry-run 不需要）")
    base = os.environ.get("GUJI_DATA_URL", "https://data.open-guji.com").rstrip("/")
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
    stats = Counter()
    local = threading.local()
    readers: list = []

    def call(url, data, method, headers):
        # Cloudflare 拦默认的 Python-urllib UA（error 1010），带自己的 UA
        headers = {"user-agent": "open-guji-cv-datastore", **headers}
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        for attempt in range(5):           # 网络抖动、429、5xx 退避重试；签名和 PUT 都幂等
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                if e.code != 429 and e.code < 500:
                    return e.code, e.read()
                err = e.code
            except (urllib.error.URLError, OSError) as e:
                err = type(e).__name__
            time.sleep(2 ** attempt)
        return err, b""

    def put(o: Obj, sig: dict) -> str:
        if sig.get("exists"):
            return "exists"
        if sig.get("key") != r2_key(o.sha):
            return "key_mismatch"
        if not hasattr(local, "reader"):
            local.reader = gitsource.BlobReader(repo)
            readers.append(local.reader)
        data = local.reader.read(o.oid)
        if sha256(data) != o.sha:
            return "sha_mismatch"
        st, _ = call(sig["url"], data, "PUT", {"content-type": "image/png"})
        return "uploaded" if st in (200, 201) else f"put_{st}"

    def one(o: Obj) -> str:
        st, body = call(f"{base}/v1/assets/sign", json.dumps(
            {"bucket": bucket, "op": "put", "sha256": o.sha, "ext": "png"}).encode(), "POST",
            {"authorization": f"Bearer {token}", "content-type": "application/json"})
        return put(o, json.loads(body)) if st == 200 else f"sign_{st}"

    def batch(chunk: list[Obj]) -> list[str] | None:
        """一次签 200 张（/v1/assets/sign-batch，已有的直接判 exists）；旧版 Worker 回 None。"""
        st, body = call(f"{base}/v1/assets/sign-batch", json.dumps(
            {"bucket": bucket, "op": "put", "ext": "png", "sha256s": [o.sha for o in chunk]}).encode(),
            "POST", {"authorization": f"Bearer {token}", "content-type": "application/json"})
        if st == 404:
            return None
        if st != 200:
            return [f"sign_{st}"] * len(chunk)
        sigs = {it["sha256"]: it for it in json.loads(body)["items"]}
        with ThreadPoolExecutor(workers) as ex:
            return list(ex.map(lambda o: put(o, sigs[o.sha]), chunk))

    todo = sorted(objs.values(), key=lambda o: o.sha)[:limit]
    try:
        rest = todo
        for i in range(0, len(todo), 200):
            res = batch(todo[i:i + 200])
            if res is None:                     # 旧版 Worker：退回逐张签
                rest = todo[i:]
                break
            for r in res:
                stats[r] += 1
        else:
            rest = []
        if rest:
            with ThreadPoolExecutor(workers) as ex:
                for res in ex.map(one, rest):
                    stats[res] += 1
    finally:
        for r in readers:
            r.close()
    return dict(stats)


def upload(repo, objs: dict[str, Obj], workers: int = 8) -> dict:
    """HEAD → 没有才 PUT；PUT 后核 ETag（单段上传的 ETag 是 MD5）。返回计数。"""
    s3, bucket = _client()
    from botocore.exceptions import ClientError
    stats = Counter()
    local = threading.local()
    readers: list = []

    def read(oid: str) -> bytes:
        if not hasattr(local, "reader"):
            local.reader = gitsource.BlobReader(repo)
            readers.append(local.reader)
        return local.reader.read(oid)

    def one(o: Obj) -> str:
        key = r2_key(o.sha)
        try:
            s3.head_object(Bucket=bucket, Key=key)
            return "exists"
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
                raise
        data = read(o.oid)
        if sha256(data) != o.sha:
            return "sha_mismatch"
        md5 = hashlib.md5(data).digest()
        resp = s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="image/png",
                             ContentMD5=base64.b64encode(md5).decode(),
                             Metadata={"sha256": o.sha})
        if resp.get("ETag", "").strip('"') != md5.hex():
            return "etag_mismatch"
        return "uploaded"

    try:
        with ThreadPoolExecutor(workers) as ex:
            for res in ex.map(one, objs.values()):
                stats[res] += 1
    finally:
        for r in readers:
            r.close()
    return dict(stats)
