"""``guji db status / pull / import`` 的实现（GUJI-606，设计第五节）。

``pull``：按中心库某分支的当前版本把字形库账本还原到
``<工作区>/output/central/<分支>/glyph_store/``，再用它重建本地 ``glyph.db``，等价于
``guji glyph-db rebuild --no-replay --no-borrow --store <还原目录>``。工作区里 git 管着的
``output/glyph_store/`` 不动。拉完在库旁写 ``glyph.db.central.json``，记分支、rev、时间。

``--rev N``：中心库不存历史内容，只能判断「该工作区在 N 之后有没有变」。没变就照当前拉，
内容与 N 时一致；变了就报错，提示从 N 开实验分支再拉。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .materialize import materialize
from .scope import GS

META_SUFFIX = ".central.json"


def workspace_id(ws_dir: Path) -> str:
    import yaml
    y = Path(ws_dir) / "workspace.yaml"
    if not y.exists():
        raise SystemExit(f"{ws_dir} 不是工作区（没有 workspace.yaml）")
    return str((yaml.safe_load(y.read_text(encoding="utf-8")) or {}).get("id") or Path(ws_dir).name)


def meta_path(db_path: Path) -> Path:
    return Path(str(db_path) + META_SUFFIX)


def read_meta(db_path: Path) -> dict | None:
    p = meta_path(db_path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def central_dir(ws_dir: Path, branch: str) -> Path:
    return Path(ws_dir) / "output" / "central" / branch.replace("/", "__")


def status(src, ws_dir: Path | None, db_path: Path | None) -> dict:
    out: dict = {"source": src.describe(), "rev": src.status()}
    if hasattr(src, "whoami"):
        out["token"] = src.whoami()
    if ws_dir is not None:
        ws = workspace_id(ws_dir)
        out["ws"] = ws
        meta = read_meta(db_path) if db_path else None
        out["local"] = meta
        if meta and meta.get("ws") == ws:
            if meta.get("branch") != getattr(src, "branch", None):
                out["behind"] = f"本地快照来自分支 {meta.get('branch')}，与当前分支不同"
            else:
                n = src.changes_since(ws, int(meta["rev"]), limit=1000)
                out["behind"] = n if n < 1000 else "≥1000"
    return out


def _check_pin(src, ws: str, rev: int) -> None:
    n = src.changes_since(ws, rev, limit=1)
    if n:
        raise SystemExit(
            f"工作区 {ws} 在 rev {rev} 之后已有变更，中心库不存旧内容，没法按 {rev} 还原。"
            f"要钉旧版本：guji db branch create exp/GUJI-<卡号>-<说明> --from-rev {rev}，"
            f"再加 --branch 那个分支重拉")


def pull(src, ws_dir: Path, db_path: Path, rev: int | None = None, with_feedback: bool = False,
         rebuild: bool = True, cache=None, bucket: str = "main", retries: int = 3) -> dict:
    ws_dir = Path(ws_dir)
    ws = workspace_id(ws_dir)
    branch = getattr(src, "branch", "main")
    dest = central_dir(ws_dir, branch)
    prefixes = (GS,) + (("feedback/",) if with_feedback else ())
    t0 = time.time()
    for _ in range(retries):
        r0 = src.status()
        if rev is not None:
            _check_pin(src, ws, rev)
        stats = materialize(src, ws, dest, prefixes, cache=cache, bucket=bucket)
        r1 = src.status()
        # 读的过程中别人写了本工作区 → 重读，保证拿到的是同一个版本
        if r1 == r0 or not src.changes_since(ws, r0, limit=1):
            break
    else:
        raise SystemExit(f"连续 {retries} 次读的过程中工作区 {ws} 有新写入，稍后再拉")
    if rev is not None:
        _check_pin(src, ws, rev)
    # 本工作区最后一次变更的 rev：拉到的内容就是它
    ws_rev = rev if rev is not None else r0
    out = {"ws": ws, "branch": branch, "rev": ws_rev, "store": str(dest / GS), **stats}
    if rebuild:
        out["glyph_db"] = rebuild_db(ws_dir, dest / GS, db_path)
    meta = {"ws": ws, "branch": branch, "rev": ws_rev, "source": src.describe(),
            "store": str(dest / GS), "pulled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "with_feedback": with_feedback}
    if rebuild:
        meta_path(db_path).write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    out["seconds"] = round(time.time() - t0, 1)
    return out


def rebuild_db(ws_dir: Path, store: Path, db_path: Path) -> dict:
    """同 ``guji glyph-db rebuild --no-replay --no-borrow --store <store>``。"""
    import yaml
    from ..clustering.glyph_db import assert_db_not_silently_empty, rebuild_from_store
    wcfg = yaml.safe_load((Path(ws_dir) / "workspace.yaml").read_text(encoding="utf-8")) or {}
    if ((wcfg.get("glyph_lib") or {}).get("borrow")):
        raise SystemExit("workspace.yaml 配了 glyph_lib.borrow（借库）：db pull 暂不支持借库，"
                         "请先用 guji glyph-db rebuild")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    summary = rebuild_from_store(store, db_path)
    assert_db_not_silently_empty(db_path, store)
    return summary


def import_events(src_from, dst, ws: str, ids: set[str] | None, dst_branch: str,
                  dry_run: bool = False) -> dict:
    """把实验分支上的人裁事件显式导入目标分支（缺省 main），经 Worker /v1/events，按 (ws, id) 幂等。

    ``ids`` 为 None 时导入实验分支上有、目标分支上没有的全部事件。
    """
    want: dict[str, list[tuple[int, str, str]]] = {}
    have = {r["id"] for r in dst.rows("events", ws)} if ids is None else set()
    found = set()
    for r in src_from.rows("events", ws):
        if (ids is not None and r["id"] not in ids) or (ids is None and r["id"] in have):
            continue
        found.add(r["id"])
        want.setdefault(r["src_path"], []).append((int(r["src_line"]), r["id"], r["raw"]))
    missing = sorted(ids - found) if ids is not None else []
    if missing:
        raise SystemExit(f"实验分支上找不到这些事件：{missing[:10]}{'…' if len(missing) > 10 else ''}")
    plan = {p: len(v) for p, v in sorted(want.items())}
    out: dict = {"ws": ws, "from": src_from.branch, "to": dst_branch, "plan": plan,
                 "n": sum(plan.values()), "dry_run": dry_run}
    if dry_run:
        return out
    results = []
    for p, rows in sorted(want.items()):
        lines = [raw for _, _, raw in sorted(rows)]
        for i in range(0, len(lines), 1000):
            res = dst.append_events(ws, p, lines[i:i + 1000], branch=dst_branch)
            results.append({"src_path": p, "inserted": len(res.get("inserted", [])),
                            "duplicates": len(res.get("duplicates", [])),
                            "import_id": res.get("import_id"), "rev_to": res.get("rev_to")})
    out["results"] = results
    return out
