# -*- coding: utf-8 -*-
"""`guji archive fetch <tag>`：取回 open-guji-dataset Release 上的归档包，核 sha256，解到空目录（GUJI-601）。

归档包是收尾时的冷存储（一册一个未压缩 tar，「留」表：events、anchors、glyph_store、books…），
恢复步骤见 ai-team `team/整理/GUJI-562/恢复演练步骤.md`。以前只能手动下载、手算 sha、手动解，
这里把前三步收成一条命令；之后照旧 `guji glyph-db rebuild -w <目录> --no-replay` 等。

sha256 的来源，按优先级：`--sha256` 显式给的 > Release 资产自带的 `digest`（GitHub 给的
`sha256:…`）。两者都没有就拒绝解包（`--no-verify` 才放行），免得解出一个没核过的包。"""
from __future__ import annotations

import hashlib
import json
import os
import tarfile
import urllib.request
from pathlib import Path
from typing import Callable

DEFAULT_REPO = "open-guji/open-guji-dataset"
API = "https://api.github.com"


class ArchiveError(RuntimeError):
    pass


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               **_auth_header()})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def _auth_header() -> dict:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"Accept": "application/octet-stream", **_auth_header()})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:  # noqa: S310
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pick_asset(release: dict, name: str | None = None) -> dict:
    assets = [a for a in release.get("assets") or [] if a.get("name", "").endswith(".tar")]
    if name:
        assets = [a for a in assets if a.get("name") == name]
    if not assets:
        raise ArchiveError(f"Release {release.get('tag_name')} 里没有 .tar 资产"
                           + (f"（找的是 {name}）" if name else ""))
    if len(assets) > 1:
        raise ArchiveError("Release 里有多个 .tar：" + "、".join(a["name"] for a in assets)
                           + "，用 --asset 指定")
    return assets[0]


def safe_extract(tar_path: Path, out: Path) -> int:
    """解到 `out`。拒绝绝对路径、`..`、链接指出目录外与设备文件。返回成员数。"""
    out = out.resolve()
    with tarfile.open(tar_path) as tf:
        members = tf.getmembers()
        for m in members:
            target = (out / m.name).resolve()
            if not (target == out or str(target).startswith(str(out) + os.sep)):
                raise ArchiveError(f"包里有越界路径：{m.name}")
            if m.isdev():
                raise ArchiveError(f"包里有设备文件：{m.name}")
            if m.issym() or m.islnk():
                link = (target.parent / m.linkname).resolve() if m.issym() else (out / m.linkname).resolve()
                if not str(link).startswith(str(out) + os.sep):
                    raise ArchiveError(f"包里的链接指向目录外：{m.name} → {m.linkname}")
        try:
            tf.extractall(out, members=members, filter="data")
        except TypeError:   # Python < 3.12 没有 filter 参数；上面已逐个查过
            tf.extractall(out, members=members)
    return len(members)


def fetch(tag: str, out: Path, repo: str = DEFAULT_REPO, sha256: str | None = None,
          asset: str | None = None, keep_tar: bool = False, no_verify: bool = False,
          get_json: Callable[[str], dict] = _get_json,
          download: Callable[[str, Path], None] = _download,
          log: Callable[[str], None] = print) -> dict:
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ArchiveError(f"{out} 不是空目录；归档只解到空目录，免得和现有工作区混在一起")
    out.mkdir(parents=True, exist_ok=True)
    try:
        rel = get_json(f"{API}/repos/{repo}/releases/tags/{tag}")
    except OSError as e:     # urllib 的 HTTPError／URLError 都是 OSError
        raise ArchiveError(f"查不到 Release {repo} {tag}：{e}") from e
    a = pick_asset(rel, asset)
    digest = (a.get("digest") or "")
    want = (sha256 or (digest.split(":", 1)[1] if digest.startswith("sha256:") else "")).lower()
    if not want and not no_verify:
        raise ArchiveError("没有可核对的 sha256：Release 资产没带 digest，请用 --sha256 给出"
                           "（或 --no-verify 跳过，不建议）")
    tar_path = out.parent / f".{out.name}.{a['name']}.part"
    log(f"下载 {repo} {tag} / {a['name']}（{a.get('size', 0) / 1e6:.1f} MB）…")
    try:
        download(a.get("url") or a["browser_download_url"], tar_path)
    except OSError as e:
        tar_path.unlink(missing_ok=True)
        raise ArchiveError(f"下载 {a['name']} 失败：{e}") from e
    got = sha256_of(tar_path)
    if want and got != want:
        tar_path.unlink(missing_ok=True)
        raise ArchiveError(f"sha256 不符：应为 {want}，实为 {got}；已删掉下载的包")
    log(f"sha256 {got}" + ("（已核对）" if want else "（未核对）"))
    n = safe_extract(tar_path, out)
    kept = None
    if keep_tar:
        kept = out.parent / a["name"]
        tar_path.replace(kept)
    else:
        tar_path.unlink(missing_ok=True)
    log(f"已解到 {out}：{n} 个成员")
    return {"tag": tag, "repo": repo, "asset": a["name"], "sha256": got, "verified": bool(want),
            "out": str(out), "members": n, "tar": str(kept) if kept else None}
