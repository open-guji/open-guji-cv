#!/usr/bin/env python3
"""待审单的雪碧图改成「文件名带内容哈希、真源进 R2」（GUJI-675，方案 B）。

之前 `sprite_build.py`／`alt_build.py` 只把雪碧图写在本机 `out/sprites/`，没有任何一步把它传到网站去取的地址，
线上待审单里的 `img.s`（如 `p0003.webp`）一直是 404，网站只能降级显示。现在：

  attach(doc, sprites_dir) → 读 `assets.json`，每张图改名 `<原名>.<sha256 前 8 位>.webp`（内容变名字就变，网站可放心长缓存），
                             改写 doc 里所有指向它们的 `s`（格的 `img.s`、相似字的 `alt[].g.s`），
                             在 doc 顶层写 `sprites: [{name, sha256, md5, bytes}]`，改名后的文件放进 `<sprites_dir>/pub/`
  upload(entries, pub_dir) → 按 sha256 传进 R2 的 main 桶（后缀 webp，已有的跳过），要 `GUJI_DATA_TOKEN`（能写 main 的）

网站这头（kaiyuanguji-web 的 proofing-sync）发布待审单时，读 `sprites[]`，经 Worker 签名链接取回、核 sha256，
传到 COS 的 `proof/<书>/<章>/<name>`，再传待审单本身，最后换 index.json。单和图同一个 rev、同一次发布。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

HASHED = re.compile(r"\.[0-9a-f]{8}\.webp$")


def unhashed(name: str) -> str:
    """去掉 attach 加的内容哈希：`p0003.0123abcd.webp` → `p0003.webp`（没带哈希的原样）。"""
    return HASHED.sub(".webp", name)


def _rewrite(node, names: dict[str, str]):
    """递归改写：任何 `{"s": <旧名>, ...}` 的 s 换成新名。"""
    if isinstance(node, dict):
        return {k: (names[v] if k == "s" and isinstance(v, str) and v in names else _rewrite(v, names))
                for k, v in node.items()}
    if isinstance(node, list):
        return [_rewrite(x, names) for x in node]
    return node


def attach(doc: dict, sprites_dir: Path) -> tuple[dict, list[dict]]:
    """返回（带 `sprites[]`、`s` 已改成哈希名的 doc, 条目列表）。`sprites_dir` 里要有 `assets.json` 和对应 webp。"""
    man = json.loads((sprites_dir / "assets.json").read_text(encoding="utf-8"))
    pub = sprites_dir / "pub"
    pub.mkdir(exist_ok=True)
    names: dict[str, str] = {}
    entries: list[dict] = []
    for f in man["files"]:
        raw = (sprites_dir / f["name"]).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        new = f["name"] if HASHED.search(f["name"]) else f"{f['name'][:-len('.webp')]}.{sha[:8]}.webp"
        names[f["name"]] = new
        (pub / new).write_bytes(raw)
        entries.append({"name": new, "sha256": sha, "md5": hashlib.md5(raw).hexdigest(), "bytes": len(raw)})
    entries.sort(key=lambda e: e["name"])
    out = _rewrite(doc, names)
    out["sprites"] = entries
    return out, entries


def refs(doc: dict) -> set[str]:
    """单子引用的全部图名：格的 `img.s`、相似字的 `alt[].g.s`。"""
    out: set[str] = set()
    for c in doc.get("cells") or ():
        if isinstance(c.get("img"), dict) and c["img"].get("s"):
            out.add(c["img"]["s"])
        for x in c.get("alt") or ():
            if isinstance(x.get("g"), dict) and x["g"].get("s"):
                out.add(x["g"]["s"])
    return out


def missing(doc: dict) -> list[str]:
    """引用了、却没登记进 `sprites[]` 的图（网站 proofing-sync 只传 sprites[] 里的，缺了就是 404）。"""
    have = {e["name"] for e in doc.get("sprites") or ()}
    return sorted(refs(doc) - have)


def upload(entries: list[dict], pub_dir: Path, bucket: str = "main") -> dict:
    """传进 R2。任何一张没传成（也不是已有）就抛 RuntimeError，不让单子在图缺着的情况下上线。"""
    from open_guji_cv.datastore.r2 import upload_files
    stats = upload_files({e["sha256"]: pub_dir / e["name"] for e in entries}, bucket=bucket, ext="webp")
    bad = {k: v for k, v in stats.items() if k not in ("uploaded", "exists")}
    if bad:
        raise RuntimeError(f"雪碧图没传完：{bad}")
    return stats


def copy_to(entries: list[dict], pub_dir: Path, dest: Path) -> None:
    """演练或本地核对用：把改名后的图放到某个目录。"""
    dest.mkdir(parents=True, exist_ok=True)
    for e in entries:
        shutil.copyfile(pub_dir / e["name"], dest / e["name"])
