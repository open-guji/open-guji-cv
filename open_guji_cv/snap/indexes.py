# -*- coding: utf-8 -*-
"""大模板索引随快照分发（2026-09-28，K 道，overview#246，用户定方案 1）。

## 为什么

控制台一侧（cv e3fcfdf）已经改成**只读盘、不现建**大模板索引：Step5-b 的 CNN embedding 表
`models/<ckpt>/emb_<key>.npz`（`guji cache build-rare-index`）与控制台的 HOG 字体表
`<ws>/cache/font_index/<key>.npz`（`guji cache build-font-index`）。表都在云端预建，
这里管的是「怎么把它们运到服务器」。

此前的做法是 `guji snap pack … --mode attach-only --attach models/…/emb_<key>.npz=cv:…`：
每个包把几十 MB 的 npz 整个塞进自己的孤儿分支。两个毛病：

- **不按 key 去重**。同一张表被好几本书共用（四庫 vol09/vol10 的 escalate 同为
  `bec61ba15252b3bc`；全唐文 v007–v009 的 base 同为 `a014a239f3e1f9e8`、escalate 同为
  `5fb2b08b71b8a796`），每个包都重传一遍，服务器每个包都重落一遍；
- **包里看不出是哪张表**。manifest 只有 `dest` 路径，key 要从文件名里抠，也不知道是
  rare 还是 font、是不是已经在服务器上了。

## 做法：一张表 = 一条 `idx/<kind>/<key>` 孤儿分支

- 大文件只进 `idx/<kind>/<key>`（无父单提交：`index.json` + 45 MB 一块的分块），
  **永远不进任何分支的主干历史**，也不进 `snap/…` 包本身；
- `snap/…` 包的 manifest 新增 `indexes: [{kind, key, root, dest, sha256, size, branch, repo}]`，
  只写**引用**；`repo` 是 idx 分支挂在哪个仓（缺省 `ws` = guji-workspace；`cv` = open-guji-cv）；
- **打包时按 key 去重**：远端已有 `idx/<kind>/<key>` 就直接引用它（用远端那份的 sha），
  不重推；同一个包里重复的 key 也只留一条；
- **导入时按 key 去重**：服务器上目标文件已经在（同名 = 同 key = 同一组输入）就跳过，
  连 idx 分支都不拉；不在才浅拉那条分支、逐块拼起来、校 sha256、原子落位。

key 的算法与产线同一个函数（`CnnCandidates.emb_index_key` / `font_candidates._index_key`），
2026-09-28 起都按**内容**算（checkpoint、字体档、字表），换机器照样命中——这是整套分发
成立的前提（此前 key 里带 mtime，云端预建的表到服务器全 miss，见 overview#51）。

⚠️ 同一个 key 在不同机器上建出来的 npz 字节不一定逐位相同（浮点累加顺序），但内容等价。
所以导入端「目标已在就跳过」只看文件在不在，不看 sha 是否等于包里写的那份。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import gitio
from .manifest import CHUNK_BYTES, ManifestError, sha256_file

BRANCH_PREFIX = "idx/"
META = "index.json"
FORMAT = "guji-index/1"

#: kind → (落在哪个根, 目标路径的正则)。`{key}` 处会换成这条的 key。
KINDS: dict[str, tuple[str, str]] = {
    # Step5-b CNN embedding 模板表：cv 仓 `models/<ckpt 目录>/emb_<key>.npz`（checkpoint 旁边）
    "rare_emb": ("cv", r"models/[0-9A-Za-z._-]+/emb_{key}\.npz"),
    # 控制台 HOG 字体模板表：书工作区 `cache/font_index/<key>.npz`（`core.workspace.cache_root()`）
    "font_hog": ("ws", r"cache/font_index/{key}\.npz"),
}
_KEY = re.compile(r"^[0-9a-f]{8,40}$")
#: idx 分支挂在哪个仓的 origin 上：缺省 guji-workspace（与 snap 包同仓）；`cv` = open-guji-cv
#: （2026-09-28 首批表由一个只有 cv 推送权的云端会话建，只能挂 cv 仓，见 overview#246 交单）。
HOSTS = ("ws", "cv")

#: 导入端的结果
PRESENT = "present"          # 目标已在（按 key 去重），没拉
PLACED = "placed"            # 拉下来、校验过、落位了
WOULD_PLACE = "would_place"  # 演练


@dataclass
class IndexFile:
    """打包端：一张表。`src=None` = 本地没有这份文件、但远端已有同 key 的 idx 分支，只引用。"""
    kind: str
    key: str
    src: Path | None
    dest: str
    label: str = ""          # 人看的：`bxgb base unicode-cjk-a 29360 字`


def branch_of(kind: str, key: str) -> str:
    return f"{BRANCH_PREFIX}{kind}/{key}"


def check_entry(e: dict) -> None:
    """manifest 里一条 `indexes` 的形状；不合法抛 ManifestError。"""
    kind, key = e.get("kind"), str(e.get("key", ""))
    if kind not in KINDS:
        raise ManifestError(f"索引 kind 只能是 {'/'.join(KINDS)}：{e}")
    if not _KEY.match(key):
        raise ManifestError(f"索引 key 不合法：{key!r}")
    root, pat = KINDS[kind]
    if e.get("root") != root:
        raise ManifestError(f"{kind} 索引只能落 {root}：{e}")
    if not re.fullmatch(pat.format(key=re.escape(key)), str(e.get("dest", ""))):
        raise ManifestError(f"{kind} 索引的 dest 与 key 对不上：{e.get('dest')!r}")
    if e.get("branch") != branch_of(kind, key):
        raise ManifestError(f"索引分支必须是 {branch_of(kind, key)}：{e.get('branch')!r}")
    if len(str(e.get("sha256", ""))) != 64:
        raise ManifestError(f"索引缺 sha256：{kind}/{key}")
    if e.get("repo", "ws") not in HOSTS:
        raise ManifestError(f"索引 repo 只能是 {'/'.join(HOSTS)}：{e.get('repo')!r}")


def dedupe(files: list[IndexFile]) -> list[IndexFile]:
    """同一个包里同一 (kind, key) 只留一条（label 合并）。"""
    out: dict[tuple[str, str], IndexFile] = {}
    for f in files:
        k = (f.kind, f.key)
        if k in out:
            if f.label and f.label not in out[k].label:
                out[k].label = f"{out[k].label}; {f.label}" if out[k].label else f.label
        else:
            out[k] = IndexFile(f.kind, f.key, f.src, f.dest, f.label)
    return list(out.values())


# ── 打包端：按书算出该带哪几张表 ──────────────────────────────────────
def rare_index_files(book: str, which: str = "all", cv_repo: Path | None = None,
                     remote_have: set[str] | frozenset = frozenset()) -> list[IndexFile]:
    """`guji cache build-rare-index --book <book>` 建的那两张表（base / escalate）。

    与产线 `rare_for_batch` 同一组函数算 key（`book_charsets` + `emb_index_key`），调用前
    `GUJI_WORKSPACE` 必须已指向这本书的工作区（字表里叠加了整理本语料）。表没建会报错并
    提示先建——打包不替人现建（那是几十分钟、GB 级内存的活，不该藏在打包命令里）。
    `remote_have`（远端已有的 idx 分支名）里有的 key，本地没文件也行：只引用，不重推。"""
    from ..clustering import cnn_candidates as cc
    from ..clustering.rare_panel import book_charsets
    from ..steps.align_ref import book_corpus

    cs_base, cs_esc, spec = book_charsets(book, book_corpus(book))
    inst = cc.CnnCandidates(ckpt=cc.DEFAULT_CKPT)
    repo = Path(cv_repo or Path(__file__).resolve().parents[2]).resolve()
    out, missing = [], []
    for name, cs, tag in (("base", cs_base, spec["base"]), ("escalate", cs_esc, spec["escalate"])):
        if which not in ("all", name) or not cs:
            continue
        key, f, _extra = inst.emb_index_key(cs)
        f = Path(f).resolve()
        try:
            dest = f.relative_to(repo).as_posix()
        except ValueError as e:
            raise ManifestError(f"checkpoint 不在 cv 仓里（{f}），没法按相对路径分发") from e
        label = f"{book} {name} {tag} {len(cs)} 字"
        if f.is_file():
            out.append(IndexFile("rare_emb", key, f, dest, label))
        elif branch_of("rare_emb", key) in remote_have:
            out.append(IndexFile("rare_emb", key, None, dest, label))
        else:
            missing.append(f"{name} key={key}（{f}）")
    if missing:
        raise FileNotFoundError(f"{book} 的 rare 索引还没建：{'; '.join(missing)}——"
                                f"先跑 `guji cache build-rare-index --book {book} -w <工作区>`")
    return out


def font_index_files(book: str | None,
                     remote_have: set[str] | frozenset = frozenset()) -> list[IndexFile]:
    """`guji cache build-font-index [--book <book>]` 建的那几张表（small ⊆ big 时只有 big）。
    `book=None` = 控制台启动预热用的 DEFAULT_CORPUS 那组。"""
    from ..clustering import font_candidates as fc
    from ..clustering.rare_panel import _rare_charsets
    from ..steps.align_ref import book_corpus

    corpus = book_corpus(book) if book else None
    uniq = sorted({tuple(cs) for cs in _rare_charsets(corpus)}, key=len, reverse=True)
    kept: list[frozenset] = []
    out, missing = [], []
    for cs in uniq:                       # 与 font_candidates.warm() 同一套包含去重
        s = frozenset(cs)
        if any(s <= p for p in kept):
            continue
        kept.append(s)
        key = fc._index_key(cs, "fonts", "hog")
        f = fc._index_dir() / f"{key}.npz"
        src = f if f.is_file() else (None if branch_of("font_hog", key) in remote_have else False)
        if src is False:
            missing.append(f"key={key}（{f}）")
            continue
        out.append(IndexFile("font_hog", key, src, f"cache/font_index/{key}.npz",
                             f"{book or '(默认语料)'} font {len(cs)} 字"))
    if missing:
        raise FileNotFoundError(f"字体索引还没建：{'; '.join(missing)}——先跑 `guji cache build-font-index"
                                + (f" --book {book} -w <工作区>`" if book else "`"))
    return out


# ── 打包端：推 idx 分支 / 复用已有 ───────────────────────────────────
def remote_index_branches(ws_repo: Path, remote: str = "origin",
                          git: gitio.GitRunner = gitio.default_git) -> dict[str, str]:
    """远端全部 `idx/*` 分支 → 提交。"""
    return gitio.ls_remote_heads(ws_repo, f"{BRANCH_PREFIX}*", remote, git)


def _read_remote_meta(ws_repo: Path, branch: str, remote: str, git: gitio.GitRunner) -> dict:
    gitio.fetch_branches(ws_repo, [branch], remote, git)
    return json.loads(gitio.show_file(ws_repo, gitio.remote_ref(branch, remote), META, git))


def _build_index_tree(f: IndexFile, tree: Path, cv_commit: str | None) -> dict:
    tree.mkdir(parents=True, exist_ok=True)
    size = f.src.stat().st_size
    parts = []
    with open(f.src, "rb") as fh:
        i = 0
        while True:
            buf = fh.read(CHUNK_BYTES)
            if not buf:
                break
            name = f"data.part{i:03d}"
            (tree / name).write_bytes(buf)
            parts.append(name)
            i += 1
    meta = {"format": FORMAT, "kind": f.kind, "key": f.key, "root": KINDS[f.kind][0], "dest": f.dest,
            "sha256": sha256_file(f.src), "size": size, "parts": parts, "label": f.label,
            "cv": cv_commit}
    (tree / META).write_text(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")
    return meta


def publish(host_repo: Path, files: list[IndexFile], *, host: str = "ws", cv_commit: str | None = None,
            remote: str = "origin", push: bool = True, dry_run: bool = False,
            git: gitio.GitRunner = gitio.default_git) -> list[dict]:
    """每张表确保 `host_repo` 的远端有一条 `idx/<kind>/<key>`，返回 manifest 的 `indexes` 条目。
    `host` 写进条目（`repo`），导入端据此到 guji-workspace 还是 cv 仓的 origin 去拉。

    远端已有 → 复用（`reused: true`，sha/size 取远端那份，不重推）；没有 → 建孤儿提交推上去
    （`push=False` 只建本地分支，`dry_run` 什么都不建）。"""
    if host not in HOSTS:
        raise ManifestError(f"host 只能是 {'/'.join(HOSTS)}")
    ws_repo = host_repo
    have = remote_index_branches(ws_repo, remote, git)
    out = []
    for f in dedupe(files):
        br = branch_of(f.kind, f.key)
        root = KINDS[f.kind][0]
        if br in have:
            meta = _read_remote_meta(ws_repo, br, remote, git)
            if meta.get("kind") != f.kind or meta.get("key") != f.key or meta.get("dest") != f.dest:
                raise ManifestError(f"远端 {br} 的 index.json 与本地这张表对不上：{meta}")
            entry = {"sha256": meta["sha256"], "size": meta.get("size"), "reused": True}
        elif f.src is None:
            raise ManifestError(f"{br} 远端没有、本地也没有文件（{f.label}）")
        elif dry_run:
            entry = {"sha256": sha256_file(f.src), "size": f.src.stat().st_size, "reused": False}
        else:
            with tempfile.TemporaryDirectory(prefix="guji-idx-") as td:
                tree = Path(td) / "tree"
                meta = _build_index_tree(f, tree, cv_commit)
                commit = gitio.commit_tree_from_dir(
                    ws_repo, tree, f"模板索引 {f.kind}/{f.key}：{f.label}\n\n"
                                   f"guji snap pack 生成（{len(meta['parts'])} 块，{meta['size']} 字节）；"
                                   f"落位 {root}:{f.dest}。内容见 {META}。", git=git)
            if push:
                gitio.push_commit(ws_repo, commit, br, remote=remote, git=git)
            else:
                cp = git(ws_repo, ["update-ref", f"refs/heads/{br}", commit, ""])
                if cp.returncode != 0:
                    raise gitio.GitError(f"本地分支已存在：{br}")
            entry = {"sha256": meta["sha256"], "size": meta["size"], "reused": False}
        out.append({"kind": f.kind, "key": f.key, "root": root, "dest": f.dest, "branch": br,
                    "repo": host, "label": f.label, **entry})
    return out


# ── 导入端 ───────────────────────────────────────────────────────────
def _target(e: dict, cv_repo: Path, ws_dir: Path | None) -> Path:
    base = cv_repo if e["root"] == "cv" else ws_dir
    if base is None:
        raise ManifestError(f"{e['kind']}/{e['key']} 要落工作区，但找不到工作区")
    return Path(base) / e["dest"]


def plan(entries: list[dict], cv_repo: Path, ws_dir: Path | None) -> list[dict]:
    """不拉、不写：每条是已在（按 key 去重跳过）还是要拉。"""
    return [{"kind": e["kind"], "key": e["key"], "dest": f"{e['root']}:{e['dest']}",
             "status": PRESENT if _target(e, cv_repo, ws_dir).is_file() else WOULD_PLACE}
            for e in entries]


def place(entries: list[dict], *, ws_repo: Path, cv_repo: Path, ws_dir: Path | None,
          remote: str = "origin", fetch: bool = True,
          git: gitio.GitRunner = gitio.default_git) -> list[dict]:
    """逐条落位；已在就跳过（不拉）。拉不到、校验不过抛异常（调用方记成可重试的失败）。"""
    out = []
    for e in entries:
        dest = _target(e, cv_repo, ws_dir)
        row = {"kind": e["kind"], "key": e["key"], "dest": f"{e['root']}:{e['dest']}"}
        if dest.is_file():
            out.append({**row, "status": PRESENT})
            continue
        br = e["branch"]
        repo = cv_repo if e.get("repo", "ws") == "cv" else ws_repo
        if fetch:
            gitio.fetch_branches(repo, [br], remote, git)
        ref = gitio.remote_ref(br, remote)
        tar = gitio.archive_tar(repo, ref, git)
        with tarfile.open(fileobj=io.BytesIO(tar), mode="r:") as tf:
            meta = json.load(tf.extractfile(META))
            if (meta.get("kind"), meta.get("key"), meta.get("dest"), meta.get("sha256")) != \
                    (e["kind"], e["key"], e["dest"], e["sha256"]):
                raise ManifestError(f"{br} 的 index.json 与包里的引用对不上")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".snap-tmp")
            try:
                with open(tmp, "wb") as fh:
                    for p in meta["parts"]:
                        if "/" in p or p in (".", ".."):
                            raise ManifestError(f"{br} 分块名不合法：{p!r}")
                        shutil.copyfileobj(tf.extractfile(p), fh, 1 << 20)
                got = sha256_file(tmp)
                if got != e["sha256"]:
                    raise ManifestError(f"{br} 拼起来 sha256 对不上（{got[:12]} ≠ {e['sha256'][:12]}）")
                os.replace(tmp, dest)
            finally:
                if tmp.exists():
                    tmp.unlink()
        out.append({**row, "status": PLACED})
    return out


def import_branch(branch: str, *, host: str, ws_repo: Path | None, cv_repo: Path, ws_dir: Path | None = None,
                  remote: str = "origin", dry_run: bool = False,
                  git: gitio.GitRunner = gitio.default_git) -> dict:
    """不经 snap 包、直接按 idx 分支名落位一张表（`guji snap import-index`，值守手动用）。
    条目从分支自己的 `index.json` 来，照样校 sha、已在就跳过。"""
    if not branch.startswith(BRANCH_PREFIX):
        raise ManifestError(f"不是 idx 分支：{branch}")
    repo = cv_repo if host == "cv" else ws_repo
    if repo is None:
        raise ManifestError("--index-repo ws 要给 --ws-repo")
    meta = _read_remote_meta(Path(repo), branch, remote, git)
    e = {k: meta.get(k) for k in ("kind", "key", "root", "dest", "sha256", "size")}
    e.update(branch=branch, repo=host)
    check_entry(e)
    if dry_run:
        return plan([e], cv_repo, ws_dir)[0]
    return place([e], ws_repo=Path(ws_repo or repo), cv_repo=cv_repo, ws_dir=ws_dir, remote=remote,
                 fetch=False, git=git)[0]
