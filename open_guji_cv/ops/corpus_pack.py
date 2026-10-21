"""`guji corpus build|verify|list`：语料库（corpus-vN）的清单与校验（设计见 doc/design/语料库版本化方案.md）。

清单读取、文件扫描、册钉子在 `core/corpus_pin.py`；这里加「出新版」和代码常量（NEVER_MATCH_FAMILIES）校验。

P0 只做清单：把流程里读的语料类文件登记进 `<工作区>/corpus-pack/vN/manifest.json`，记每个文件的 sha256。
**不搬文件**——Step 仍读原位置；`verify` 用来发现「清单之后文件又被改了」，那就该出 vN+1。
P1 起册 yaml 可以 `corpus: N` 钉版本，指纹只认版本号（见 core/corpus_pin.py）。

版本号是递增整数；已存在的 vN 不覆盖。不自动运行，定期手动跑。人裁累积（crop_exclusions）、字形库、
图像模型不属于语料库，不登记。

**两级清单（共享方案 2.1 节，S2）**：引擎仓里的文件（字表、IDS、异体、形近、规则……）登记在**底库**
``b<M>``，放中心库只读工作区 ``corpus-base`` 的 ``config/corpus-base/b<M>/manifest.json``（``build-base`` 出、
记 ``repo_commit`` 好还原）；书库 ``v<N>`` 写 ``base: M``，只登记工作区里的文件（整理本、字频、L2、工作区异体）。
旧的单级清单（殿本 v1）照旧能读。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
from pathlib import Path

from ..core.corpus_pin import (BASE_DIR, BASE_WS, ITEMS, PACK_DIR, REPO_ROOT,  # noqa: F401
                               base_manifest_path, base_versions, check_files, collect, load_manifest,
                               manifest_path, pack_root, versions)


def _never_match_hash() -> str:
    """写死在 `clustering.match` 里的 NEVER_MATCH_FAMILIES：代码常量，也算语料。"""
    from ..clustering.match import NEVER_MATCH_FAMILIES
    items = sorted("".join(sorted(map(str, f))) if not isinstance(f, str) else f for f in NEVER_MATCH_FAMILIES)
    return hashlib.sha256(json.dumps(items, ensure_ascii=False).encode()).hexdigest()


def _git_head() -> str:
    try:
        r = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _cv_version(repo: Path = REPO_ROOT) -> str:
    """引擎仓 ``pyproject.toml`` 里的版本号。装包元数据（``importlib.metadata``）只在重装时更新，
    可编辑安装后升了版本号它还是旧的（底库 b1 就因此记成 0.4.4，实为 v0.4.6），只在读不到仓时兜底。"""
    try:
        import tomllib
        return str(tomllib.loads((Path(repo) / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
    except Exception:
        pass
    try:
        from importlib.metadata import version
        return version("open-guji-cv")
    except Exception:
        return ""


def _resolve_base(ws: Path, base) -> int | None:
    """``--base``：None → 单级清单（旧做法）；``latest`` → 本机已有的最新底库；数字 → 那一版（本机要有）。"""
    if base is None:
        return None
    have = base_versions(ws)
    if str(base).lower() == "latest":
        if not have:
            raise FileNotFoundError(f"本机没有底库清单（{BASE_WS}）：先 guji db pull -w {ws}，"
                                    f"或还没出过底库就先 guji corpus build-base")
        return have[-1]
    b = int(str(base).lstrip("bB"))
    if b not in have:
        raise FileNotFoundError(f"本机没有底库 b{b}（有 {have}）：先 guji db pull -w {ws}")
    return b


def build(ws: Path, version: int | None = None, note: str = "", base=None) -> Path:
    """出新版清单。已存在的版本号拒绝覆盖；缺省取现有最大号 + 1。

    ``base``（``latest`` 或底库号）：两级清单，只登记工作区里的文件，引擎仓的文件归底库。"""
    have = versions(ws)
    v = version if version is not None else (have[-1] + 1 if have else 1)
    out = manifest_path(ws, v)
    if out.exists():
        raise FileExistsError(f"语料库 v{v} 已存在（{out}），不覆盖；要新版请不给 --version")
    b = _resolve_base(ws, base)
    items = collect(ws)
    man = {
        "corpus_version": v,
        "created": datetime.date.today().isoformat(),
        "built_with": {"cv_version": _cv_version(), "cv_commit": _git_head()},
        "note": note,
    }
    if b is None:
        man.update(code_tables={"NEVER_MATCH_FAMILIES": _never_match_hash()}, items=items)
    else:
        bm = json.loads(base_manifest_path(ws, b).read_text(encoding="utf-8"))
        drift = check_files(ws, bm)
        if drift["changed"] or drift["missing"]:
            raise ValueError(f"本机引擎仓的文件与底库 b{b} 不符（{(drift['changed'] + drift['missing'])[:5]}）："
                             f"先出新底库（guji corpus build-base），或切到 b{b} 的提交 {bm.get('repo_commit')}")
        man.update(base=b, items=[i for i in items if i["root"] == "ws"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def build_vol(ws: Path, vol: str, note: str = "") -> Path:
    """出册层新版清单（``config/corpus-vol/<册>/**`` 下的文件）。缺省取最大号 + 1；
    没有文件、或内容与最新一版完全相同都拒绝（不空升）。"""
    from ..core.corpus_pin import collect_vol, vol_manifest_path, vol_versions
    items = collect_vol(ws, vol)
    if not items:
        raise FileNotFoundError(f"册 {vol} 的册层目录 config/corpus-vol/{vol}/ 下没有文件")
    have = vol_versions(ws, vol)
    if have:
        last = json.loads(vol_manifest_path(ws, vol, have[-1]).read_text(encoding="utf-8"))
        if [(i["path"], i["sha256"]) for i in last["items"]] == [(i["path"], i["sha256"]) for i in items]:
            raise ValueError(f"册 {vol} 的册层内容与 v{have[-1]} 相同，不空升")
    v = (have[-1] + 1) if have else 1
    out = vol_manifest_path(ws, vol, v)
    man = {"vol": vol, "vol_version": v, "created": datetime.date.today().isoformat(),
           "built_with": {"cv_version": _cv_version(), "cv_commit": _git_head()}, "note": note, "items": items}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def verify(ws: Path, version: int, vol: str | None = None) -> dict:
    """拿清单对当前文件：返回 changed／missing／extra（清单之外新出现的）。两级清单连底库一起对；
    给了 ``vol`` 按该册的钉子账把总号 ``version`` 解成三层一起对。"""
    man = load_manifest(ws, version, vol)
    r = check_files(ws, man)
    if vol is not None:                           # 册层目录不在 ITEMS 里，新增的册层文件单独扫
        from ..core.corpus_pin import collect_vol
        listed = {i["path"] for i in man["items"]}
        r = {**r, "extra": r["extra"] + [f'ws:{i["path"]}' for i in collect_vol(ws, vol) if i["path"] not in listed]}
    code_ok = man.get("code_tables", {}).get("NEVER_MATCH_FAMILIES") == _never_match_hash()
    out = {"version": version, **r, "never_match_families_same": code_ok,
           "clean": not (r["changed"] or r["missing"] or r["extra"]) and code_ok}
    if man.get("base") is not None:
        out["base"] = man["base"]
    return out


def summary(ws: Path) -> list[dict]:
    out = []
    for v in versions(ws):
        m = json.loads(manifest_path(ws, v).read_text(encoding="utf-8"))
        row = {"version": v, "created": m.get("created"), "files": len(m["items"]),
               "built_with": m.get("built_with"), "note": m.get("note", "")}
        if m.get("base") is not None:
            row["base"] = m["base"]
        out.append(row)
    return out


# ── 底库 ────────────────────────────────────────────────────────────────────────

def _repo_dirty(paths: list[str], repo: Path = REPO_ROOT) -> list[str]:
    """这些引擎仓文件里没提交的（改了、没进 git 的）。底库靠 ``repo_commit`` 还原，必须都已提交。"""
    if not paths:
        return []
    r = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all", "--", *paths],
                       capture_output=True, text=True, timeout=60, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git status 失败：{r.stderr.strip()}")
    return [ln[3:] for ln in r.stdout.splitlines() if ln.strip()]


def _repo_commit(repo: Path = REPO_ROOT) -> str:
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30,
                       check=False)
    if r.returncode != 0:
        raise RuntimeError("拿不到引擎仓的提交号（底库要记 repo_commit）")
    return r.stdout.strip()


def build_base(base_ws: Path, note: str = "", *, repo: Path = REPO_ROOT) -> Path:
    """出新版底库清单 ``b<M>``（M＝本机已有最大号 + 1），写进 ``corpus-base`` 工作区的数据目录。

    只登记引擎仓的文件；它们必须都已提交（``repo_commit`` 能还原）。写完由调用方
    ``push(..., shared_writer=True)`` 推进中心库。已有的版本不覆盖。"""
    from ..core.workspace import central_marker
    base_ws = Path(base_ws)
    if (central_marker(base_ws) or {}).get("ws") != BASE_WS:
        raise SystemExit(f"{base_ws} 不是 {BASE_WS} 工作区")
    items = [i for i in collect(base_ws) if i["root"] == "repo"]
    dirty = _repo_dirty([i["path"] for i in items], repo)
    if dirty:
        raise SystemExit(f"引擎仓有 {len(dirty)} 个语料文件没提交（如 {dirty[:5]}）：底库靠 repo_commit 还原，先提交")
    have = base_versions(base_ws)
    b = have[-1] + 1 if have else 1
    out = base_manifest_path(base_ws, b)
    if out.exists():
        raise FileExistsError(f"底库 b{b} 已存在（{out}）")
    man = {
        "base_version": b,
        "created": datetime.date.today().isoformat(),
        "repo_commit": _repo_commit(repo),
        "built_with": {"cv_version": _cv_version(repo)},
        "note": note,
        "code_tables": {"NEVER_MATCH_FAMILIES": _never_match_hash()},
        "items": items,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def base_workdir(branch: str = "main") -> Path:
    """升级脚本用的 ``corpus-base`` 工作区目录（只有 ``workspace.yaml`` 和标记；数据在数据目录）。"""
    from ..core.workspace import data_home
    d = data_home() / branch.replace("/", "__") / ".shared" / BASE_WS
    d.mkdir(parents=True, exist_ok=True)
    (d / "workspace.yaml").write_text(f"id: {BASE_WS}\n", encoding="utf-8")
    (d / ".central.json").write_text(json.dumps({"ws": BASE_WS, "branch": branch}) + "\n", encoding="utf-8")
    return d


def publish_base(src, conn, *, note: str = "", actor: str | None = None, repo: Path = REPO_ROOT,
                 dry_run: bool = False) -> dict:
    """``guji corpus build-base``：拉 ``corpus-base``（库里还没有就新开）→ 出 ``b<M>`` → 推（升级脚本才能写共享层）。"""
    from ..datastore.workcopy import _db_manifest, pull, push
    branch = getattr(src, "branch", "main") or "main"
    ws = base_workdir(branch)
    if _db_manifest(src, BASE_WS):
        pull(src, ws, force=True)
    out = build_base(ws, note, repo=repo)
    man = json.loads(out.read_text(encoding="utf-8"))
    try:
        rep = push(conn, ws, actor=actor, shared_writer=True, dry_run=dry_run)
    except BaseException:
        out.unlink()                                   # 没推上去：别留一份本地独有的版本
        raise
    if dry_run:
        out.unlink()
    return {"base_version": man.get("base_version"), "repo_commit": man.get("repo_commit"),
            "files": len(man.get("items", [])), "manifest": str(out), "push": rep}


# ── 大文件进 R2（分层版本 P2）────────────────────────────────────────────────────

def _blob_files(ws: Path, man: dict) -> dict[str, Path]:
    """清单里标了 ``store: r2`` 的条目 → {sha256: 本机文件路径}（文件不在本机就缺席）。"""
    from ..core.corpus_pin import _base
    out = {}
    for it in man["items"]:
        if it.get("store") == "r2":
            p = _base(it["root"], it["path"], ws) / it["path"]
            if p.is_file():
                out[it["sha256"]] = p
    return out


def upload_blobs(ws: Path, version: int, vol: str | None = None, execute: bool = False) -> dict:
    """``guji corpus upload``：把这版清单里的大文件传进 R2（按 sha256 内容寻址，已有跳过）。
    缺省只演练（列要传的文件和字节数）；``--execute`` 才真传，要 ``GUJI_DATA_TOKEN``。
    本机文件的 sha 和清单不符的拒绝上传（先 verify）。"""
    man = load_manifest(ws, version, vol)
    want = {it["sha256"]: it for it in man["items"] if it.get("store") == "r2"}
    have = _blob_files(ws, man)
    stale = [sha for sha, p in have.items() if _sha256_file(p) != sha]
    if stale:
        raise ValueError(f"本机文件内容与清单不符，不上传：{[str(have[s]) for s in stale][:3]}（先 guji corpus verify）")
    plan = {"version": version, "blobs": len(want), "bytes": sum(it["size"] for it in want.values()),
            "local": len(have), "missing_local": sorted(want[s]["path"] for s in want if s not in have),
            "executed": False}
    if execute:
        from ..datastore.r2 import upload_files
        plan["upload"] = upload_files(have, bucket="main", ext="txt")
        plan["executed"] = True
    return plan


def fetch_blobs(ws: Path, version: int, vol: str | None = None) -> dict:
    """``guji corpus fetch``：把这版清单里本机缺的大文件从 R2 取回、放到清单登记的位置。
    本机已有且内容一致的跳过；已有但内容不同的**不覆盖**，报出来。"""
    import shutil

    from ..core.corpus_pin import _base
    from ..datastore.client import BlobCache, WorkerSource
    man = load_manifest(ws, version, vol)
    todo, differ, ok = [], [], 0
    for it in man["items"]:
        if it.get("store") != "r2":
            continue
        p = _base(it["root"], it["path"], ws) / it["path"]
        if not p.exists():
            todo.append((it, p))
        elif _sha256_file(p) == it["sha256"]:
            ok += 1
        else:
            differ.append(it["path"])
    cache = BlobCache()
    got = cache.ensure(WorkerSource(), [it["sha256"] for it, _ in todo], ext="txt") if todo else {"missing": []}
    placed = 0
    for it, p in todo:
        if cache.has(it["sha256"]):
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cache.path(it["sha256"]), p)
            placed += 1
    return {"version": version, "already_ok": ok, "placed": placed, "differ_not_overwritten": differ,
            "not_in_r2": got["missing"]}


def _sha256_file(p: Path) -> str:
    from ..core.corpus_pin import _sha256
    return _sha256(p)
