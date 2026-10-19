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


def _cv_version() -> str:
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


def verify(ws: Path, version: int) -> dict:
    """拿清单对当前文件：返回 changed／missing／extra（清单之外新出现的）。两级清单连底库一起对。"""
    man = load_manifest(ws, version)
    r = check_files(ws, man)
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
        "built_with": {"cv_version": _cv_version()},
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
