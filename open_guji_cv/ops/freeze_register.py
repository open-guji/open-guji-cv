# -*- coding: utf-8 -*-
"""`guji freeze register <册>`：一册文本定版（0.1.0／1.0.0）时把冻结登记一次做齐（GUJI-694，GUJI-730 P2-7）。

以前冻结靠人手：工作区 git 的 snap 分支存快照、册 yaml 手填 `freeze:`、tag 另找人打，中心库三张登记表一直空着。
这里一条命令做五件事（缺省只出计划，`--execute` 才动手；打 1.0 标签与冻结要用户明说，见 1.0 发布标准 G8）：

1. 产物存进 R2 冻结包，标签 `freeze-<文本版本>-<UTC>`（包按名字只增不改，就是 pin 住）并标成该册 main；
   包旁边另存 `baseline.json`（guji-snap/1 同形：每个产物文件的 sha256），close-check 1a 照它比，不再要 snap 分支；
2. 中心库登记：数据目录 `feedback/lists/freeze/<册>.jsonl` 追加一行（字段同 schema.sql 的 `freeze_baselines`，
   另带 `pack`、`tag`、`text_commit`）。三张表还没有写入口（guji-data Worker 只读），先记文件、随 `guji db sync` 进库，
   以后有写入口时照这份文件导入即可；
3. 册 yaml：`freeze:` 段换成 `{at, cv_version, cv_commit, pack, tag, registered}`，顶层 `cv_version` 设成同一版本（版本护栏只认顶层）；
4. 打 `freeze/<书>-<册>-<UTC>` tag：给了 `--tag-via <ai-team 目录>` 就经中转站 `process/tag.py` 打，否则把命令打出来；
5. 提醒 `guji db sync`（册 yaml 与登记文件进中心库）。

前提（不满足就拒）：cv 检出干净、HEAD 已在远端某分支上（冻结代码删分支后也要取得到，tag 才有意义）；
本机有这册的产物；文本版本形如 X.Y.Z。只读 book-text（取 HEAD sha 记进登记，`exit-check` E10 另核）。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SNAP_FORMAT = "guji-snap/1"
_VER = re.compile(r"\d+\.\d+\.\d+")


def _git(repo: Path, *a: str) -> str | None:
    p = subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, encoding="utf-8")
    return p.stdout.strip() if p.returncode == 0 else None


def products_baseline(root: Path, book: str, created: str, cv: dict) -> dict:
    """本机 `<产物根>/<册>/` 下每个文件的 sha256，路径写成 `products/<册>/<步>/<文件>`（与 snap manifest 同形）。
    `_prev/`、`*.tmp`、`_manifest.jsonl` 不收（packs 不打 `_prev`；manifest 只追加，比不了）。"""
    files = {}
    base = Path(root) / book
    for f in sorted(base.rglob("*")):
        if not f.is_file() or "_prev" in f.relative_to(base).parts or f.suffix == ".tmp" or f.name == "_manifest.jsonl":
            continue
        rel = f"products/{book}/{f.relative_to(base).as_posix()}"
        files[rel] = {"sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "bytes": f.stat().st_size}
    return {"format": SNAP_FORMAT, "book": book, "created": created, "cv": cv, "files": files}


def cv_state(repo: Path = REPO) -> dict:
    """cv 检出：版本、提交、是否干净、提交在不在远端某分支上。"""
    from ..core import cv_version as CV
    ver, commit = CV.describe(repo)
    dirty = bool(_git(repo, "status", "--porcelain", "-uno"))
    remote = bool(commit and _git(repo, "branch", "-r", "--contains", commit))
    return {"version": ver, "commit": commit, "dirty": dirty, "on_remote": remote}


def plan(book: str, version: str, *, text_id: str, ws_name: str, products_root: Path,
         text_dir: Path | None = None, repo: Path = REPO, now: float | None = None, note: str = "") -> dict:
    """算出要做的事，不动任何东西。问题放进 `problems`（有就不许 execute）。"""
    stamp = time.strftime("%Y%m%dT%H%M", time.gmtime(now))
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    cv = cv_state(repo)
    problems = []
    if not _VER.fullmatch(version or ""):
        problems.append(f"文本版本 {version!r} 不是 X.Y.Z")
    if not cv["commit"]:
        problems.append("取不到 cv 的提交（不是 cv 的 git 检出？）")
    if cv["dirty"]:
        problems.append("cv 检出有没提交的改动：冻结的代码必须是某个提交")
    if cv["commit"] and not cv["on_remote"]:
        problems.append(f"cv 提交 {cv['commit'][:9]} 还不在远端任何分支上：先推上去，tag 才打得上")
    if not (Path(products_root) / book).is_dir():
        problems.append(f"本机没有 {book} 的产物（{Path(products_root) / book}）")
    text_commit = _git(text_dir, "rev-parse", "HEAD") if text_dir else None
    if text_dir and not text_commit:
        problems.append(f"{text_dir} 不是 git 检出，取不到 book-text 提交")
    label = f"freeze-{version}-{stamp}"
    record = {"ws": ws_name, "book": book, "version": version, "cv_version": cv["version"], "cv_commit": cv["commit"],
              "snapshot_id": label, "pack": f"products/{ws_name}/{book}/{label}", "db_branch": "main", "db_rev": None,
              "tag": f"freeze/{text_id}-{book}-{stamp}", "text_commit": text_commit, "frozen_at": created, "note": note}
    yaml_freeze = {"at": version, "cv_version": cv["version"], "cv_commit": cv["commit"], "pack": label,
                   "tag": record["tag"], "registered": created}
    return {"book": book, "label": label, "created": created, "cv": cv, "record": record,
            "yaml_freeze": yaml_freeze, "problems": problems}


def rewrite_yaml(text: str, freeze: dict, cv_version: str) -> str:
    """册 yaml 原文：去掉顶层 `freeze:` 段和顶层 `cv_version:` 行，在末尾写新的。别的行（含注释）一字不动。"""
    out, skip = [], False
    for ln in text.splitlines():
        top = bool(ln) and not ln[0].isspace() and not ln.startswith("#")
        if top:
            skip = ln.startswith("freeze:")
            if ln.startswith("cv_version:"):
                continue
        elif skip and (ln.startswith((" ", "\t")) or not ln.strip()):
            continue
        if not skip:
            out.append(ln)
    while out and not out[-1].strip():
        out.pop()
    out += ["", f"cv_version: {json.dumps(cv_version)}            # 版本护栏只认顶层（freeze register 写）", "freeze:"]
    out += [f"  {k}: {json.dumps(v, ensure_ascii=False)}" for k, v in freeze.items()]
    return "\n".join(out) + "\n"


def registry_path(book: str) -> Path:
    from ..core.workspace import feedback_root
    return feedback_root() / "lists" / "freeze" / f"{book}.jsonl"


def execute(p: dict, *, products_root: Path, yaml_path: Path, vers: dict, tag_via: Path | None = None, src=None) -> dict:
    """照计划做：存包＋baseline、标 main、写登记、改 yaml、打 tag（或给命令）。`vers` 是 `cli_products.book_versions` 算的三样版本。"""
    if p["problems"]:
        raise RuntimeError("计划有问题，不执行：" + "；".join(p["problems"]))
    from ..datastore import packs as PK
    book, label = p["book"], p["label"]
    p["record"]["db_rev"] = vers.get("db_rev")
    man = PK.push_products(book, Path(products_root), label=label, vers=vers,
                           note=f"冻结 {p['record']['version']}（freeze register）")
    base = products_baseline(Path(products_root), book, p["created"], {"version": p["cv"]["version"], "commit": p["cv"]["commit"]})
    src = src or PK._client()
    PK._call(src, "PUT", f"{man['name']}/baseline.json", data=json.dumps(base, ensure_ascii=False).encode("utf-8"),
             content_type="application/json", tries=3)
    PK.promote(book, label, note="冻结基线", src=src)
    reg = registry_path(book)
    reg.parent.mkdir(parents=True, exist_ok=True)
    with open(reg, "a", encoding="utf-8") as f:
        f.write(json.dumps(p["record"], ensure_ascii=False) + "\n")
    yaml_path.write_text(rewrite_yaml(yaml_path.read_text(encoding="utf-8"), p["yaml_freeze"], p["cv"]["version"]),
                         encoding="utf-8")
    tag_cmd = ["python3", "process/tag.py", "open-guji/open-guji-cv", p["cv"]["commit"], p["record"]["tag"],
               f"{book} 文本 {p['record']['version']} 冻结代码"]
    tagged = None
    if tag_via:
        r = subprocess.run(tag_cmd, cwd=str(tag_via), capture_output=True, text=True, encoding="utf-8")
        tagged = r.returncode == 0
        if not tagged:
            print(f"⚠ 打 tag 没成（{(r.stdout + r.stderr).strip()[-300:]}）；稍后在 ai-team 里手动跑：{' '.join(tag_cmd)}")
    return {"pack": man["name"], "files": len(base["files"]), "registry": str(reg), "yaml": str(yaml_path),
            "tag": p["record"]["tag"], "tagged": tagged, "tag_cmd": tag_cmd}


def load_pack_baseline(pack: str, book: str, ws: Path, src=None) -> dict:
    """`freeze.pack` 指的冻结包旁的 baseline.json；取过一次缓存在工作区 `.freeze_cache/`。"""
    cache = Path(ws) / ".freeze_cache" / book / f"{pack}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    from ..datastore import packs as PK
    src = src or PK._client()
    raw = PK._call(src, "GET", f"{PK._prefix(PK._ws_name(), book)}/{pack}/baseline.json", raw=True)
    doc = json.loads(raw)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return doc
