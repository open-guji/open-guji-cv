"""``guji db status / import`` 的实现（GUJI-606）；拉、推、迁移见 ``workcopy.py``（GUJI-608）。"""

from __future__ import annotations

from pathlib import Path


def workspace_id(ws_dir: Path) -> str:
    import yaml
    y = Path(ws_dir) / "workspace.yaml"
    if not y.exists():
        raise SystemExit(f"{ws_dir} 不是工作区（没有 workspace.yaml）")
    return str((yaml.safe_load(y.read_text(encoding="utf-8")) or {}).get("id") or Path(ws_dir).name)


def status(src, ws_dir: Path | None) -> dict:
    """分支、rev、令牌角色；给了已迁移的工作区再报本地副本落后几条、有几个文件没推。"""
    out: dict = {"source": src.describe(), "rev": src.status()}
    if hasattr(src, "whoami"):
        out["token"] = src.whoami()
    if ws_dir is None:
        return out
    from ..core.workspace import central_marker
    from .workcopy import data_dir, local_changes, read_state
    m = central_marker(Path(ws_dir))
    out["ws"] = workspace_id(ws_dir)
    if not m:
        out["local"] = "未迁移（数据还在工作区里）：guji db migrate -w <工作区>"
        return out
    data = data_dir(ws_dir)
    st = read_state(data)
    out["data_dir"] = str(data)
    if st is None:
        out["local"] = "数据目录还没拉：guji db pull -w <工作区>"
        return out
    out["local_rev"] = st["rev"]
    if m.get("branch", "main") != getattr(src, "branch", None):
        out["behind"] = f"本地副本来自分支 {m.get('branch')}，与当前分支不同"
    else:
        n = src.changes_since(str(m["ws"]), int(st["rev"]), limit=1000)
        out["behind"] = n if n < 1000 else "≥1000"
    out["unpushed"] = local_changes(ws_dir)
    return out


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


def diff_branches(a, b, ws: str, show: int = 20) -> dict:
    """``guji db diff``：工作区 ``ws`` 在分支 ``a``（一般是实验分支）与 ``b``（一般是 main）上逐文件比。

    只读 ``source_files``（文本文件的 sha、行数）与图表的清单，不下载内容。两边分开以后各自都可能有新写入，
    所以报的是「现在不一样的」，不分谁改的；人裁事件另按 id 列出只在 ``a`` 上有的（即 ``guji db import`` 会导入的）。"""
    from .materialize import blob_rows
    from .scope import BLOB_TABLES

    def files(src) -> dict[str, tuple[str, int | None]]:
        out = {r["src_path"]: (r["sha256"], r.get("n_lines")) for r in src.rows("source_files", ws)}
        for tbl in BLOB_TABLES:
            out.update({r["src_path"]: (r["sha256"], None) for r in blob_rows(src, tbl, ws)})
        return out

    fa, fb = files(a), files(b)
    only_a = sorted(set(fa) - set(fb))
    only_b = sorted(set(fb) - set(fa))
    changed = sorted(p for p in set(fa) & set(fb) if fa[p][0] != fb[p][0])

    def group(paths: list[str]) -> dict[str, int]:
        g: dict[str, int] = {}
        for p in paths:
            k = "/".join(p.split("/")[:2])
            g[k] = g.get(k, 0) + 1
        return dict(sorted(g.items()))

    ev_b = {r["id"] for r in b.rows("events", ws)}
    ev_only_a = sorted({r["id"] for r in a.rows("events", ws)} - ev_b)
    return {
        "ws": ws, "branch": a.branch, "against": b.branch, "rev": a.status(), "against_rev": b.status(),
        "same": len(set(fa) & set(fb)) - len(changed),
        "changed": {"n": len(changed), "by_dir": group(changed),
                    "items": [{"path": p, "lines": fa[p][1], "against_lines": fb[p][1]} for p in changed[:show]]},
        "only_in_branch": {"n": len(only_a), "by_dir": group(only_a), "items": only_a[:show]},
        "only_in_against": {"n": len(only_b), "by_dir": group(only_b), "items": only_b[:show]},
        "events_only_in_branch": {"n": len(ev_only_a), "ids": ev_only_a[:show]},
    }
