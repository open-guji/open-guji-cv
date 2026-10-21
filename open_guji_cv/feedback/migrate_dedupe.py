"""人裁事件：删整轮重发的副本（规范 §9 O-8，2026-10-21 用户定「不留历史包袱」）。

2026-09-16 之前定字台每次提交都把整轮已有裁决重写一遍：同一格、同一 `client_ts`（同一次点击）的同一裁决，
隔一两个小时又落一条新 `ts`。重放取最新时取到的是副本，它的 `ts` 不是判断时刻——没有锚的老裁决绑定时按
`ts` 判「裁于现行切分之前／之后」，副本会让一条其实裁在旧切分上的裁决被当成裁在新切分上。

**副本**＝与本格（`kind, target.unit, target.key`）按 `replay_key` 的上一条相比，`kind`、`actor`、`target`
（含锚）、`payload`（含非空的 `client_ts`）全同，只有 `id/batch/seq/ts` 不同。删掉它，上一条成为最新，重放出来的
裁决内容一字不差。引用跟着改：

- `consumed/<消费者>.jsonl`：删副本的记账行（原件自己有记账；副本的内容与原件相同，消费结果不变）；
- `verdicts/**/items.jsonl` 的 `source_events`：副本 id 换成原件 id（去重保序）；
- `anchors/<册>.jsonl`：删副本的补锚行（原件有自己的）。

核对（`verify`）：删掉的每条在剩下的事件里都有内容全同、时间更早的原件；剩下的事件逐字节不变；
`gold rebuild` 结果只差 `source_events` 的换名；再跑一遍是空操作。

`python -m open_guji_cv.feedback.migrate_dedupe --ws <工作区> [--apply]`。不带 `--apply` 只报计划、不写库。
"""
from __future__ import annotations

import json
from collections import Counter

from .migrate_v1 import (
    ANCHORS_DIR,
    CONSUMED_DIR,
    EVENT_DIRS,
    VERDICTS_DIR,
    Migration,
    _events,
    _is_event,
    _join,
    _lines,
    _replay_key,
    dumps,
)

#: 判副本时不比的字段
_FREE = ("id", "batch", "seq", "ts")


def _body(d: dict) -> str:
    return dumps({k: v for k, v in d.items() if k not in _FREE})


def find_copies(files: dict[str, bytes]) -> dict[str, str]:
    """副本 id → 原件 id（原件取同格最早那条同内容的）。"""
    evs = sorted((d for _, d in _events(files)), key=_replay_key)
    last: dict[tuple, dict] = {}
    root: dict[str, str] = {}
    out: dict[str, str] = {}
    for d in evs:
        t = d.get("target") or {}
        k = (d.get("kind"), t.get("unit"), t.get("key"))
        p = last.get(k)
        if (p is not None and (d.get("payload") or {}).get("client_ts") is not None
                and _body(p) == _body(d)):
            out[d["id"]] = root.get(p["id"], p["id"])
            continue                       # 副本不顶替上一条：同格再来一条副本仍对到原件
        last[k] = d
    return out


def migrate(files: dict[str, bytes]) -> Migration:
    m = Migration(files=dict(files))
    copies = find_copies(files)
    if not copies:
        return m
    for path in sorted(files):
        if not (path.endswith(".jsonl") and any(path.startswith(d) for d in EVENT_DIRS)):
            continue
        keep, n = [], 0
        for line in _lines(files[path]):
            d = json.loads(line)
            if _is_event(d) and d.get("id") in copies:
                n += 1
                continue
            keep.append(line)
        if n:
            m.files[path] = _join(keep)
            m.note("O-8 删整轮重发副本", f"{path} {n} 条")
    for path in sorted(files):
        if path.startswith(CONSUMED_DIR) and path.endswith(".jsonl"):
            ls = _lines(files[path])
            keep = [x for x in ls if json.loads(x).get("event") not in copies]
            if len(keep) != len(ls):
                m.files[path] = _join(keep)
                m.note("O-8 删副本的记账", f"{path} {len(ls) - len(keep)} 行")
        elif path.startswith(ANCHORS_DIR) and path.endswith(".jsonl"):
            ls = _lines(files[path])
            keep = [x for x in ls if json.loads(x).get("event") not in copies]
            if len(keep) != len(ls):
                m.files[path] = _join(keep)
                m.note("O-8 删副本的补锚", f"{path} {len(ls) - len(keep)} 行")
        elif path.startswith(VERDICTS_DIR) and path.endswith("items.jsonl"):
            out, changed = [], False
            for x in _lines(files[path]):
                d = json.loads(x)
                se = d.get("source_events")
                if isinstance(se, list) and any(i in copies for i in se):
                    new = list(dict.fromkeys(copies.get(i, i) for i in se))
                    d["source_events"] = new
                    out.append(dumps(d))
                    changed = True
                else:
                    out.append(x)
            if changed:
                m.files[path] = _join(out)
                m.note("O-8 金标 source_events 换成原件", path)
    m.counts["copies"] = len(copies)
    return m


def verify(before: dict[str, bytes], m: Migration) -> dict:
    b, a = _events(before), _events(m.files)
    copies = find_copies(before)
    after = {d["id"]: d for _, d in a}
    if len(a) != len(b) - len(copies):
        raise AssertionError(f"事件条数 {len(b)} → {len(a)}，应少 {len(copies)}")
    raw_b = {d["id"]: d for _, d in b}
    for c, orig in copies.items():
        if orig not in after:
            raise AssertionError(f"副本 {c} 的原件 {orig} 不在了")
        if _body(raw_b[c]) != _body(after[orig]) or _replay_key(after[orig]) >= _replay_key(raw_b[c]):
            raise AssertionError(f"{c} 与原件 {orig} 内容不同或原件不更早")
    for i, d in after.items():
        if dumps(d) != dumps(raw_b[i]):
            raise AssertionError(f"留下的事件 {i} 变了")
    if migrate(m.files).changed(m.files):
        raise AssertionError("再跑一遍还有改动")
    return {"events": len(a), "dropped": len(copies)}


def gold_rebuild_check(before: dict[str, bytes], m: Migration) -> dict:
    """改前、改后各 `gold rebuild` 一遍；改前结果的 `source_events` 换成原件后须与改后相同（`source_events` 按集合比）。"""
    import tempfile
    from pathlib import Path

    from ..gold.store import GoldStore
    from ..gold.transfer import rebuild_verdicts
    from .events import EventLog
    copies = find_copies(before)

    def run(files: dict[str, bytes], root: Path) -> dict[str, list[dict]]:
        for p, data in files.items():
            if any(p.startswith(d) for d in EVENT_DIRS) or p == "feedback/routes.yaml":
                f = root / p
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
        rebuild_verdicts(EventLog(root / "feedback"), GoldStore(root / "gold"))
        out = {}
        for f in sorted((root / "gold").rglob("items.jsonl")):
            rows = []
            for line in _lines(f.read_bytes()):
                d = json.loads(line)
                d.pop("history", None)
                rows.append(d)
            out[f.relative_to(root / "gold").as_posix()] = rows
        return out

    with tempfile.TemporaryDirectory() as t0, tempfile.TemporaryDirectory() as t1:
        gb, ga = run(before, Path(t0)), run(m.files, Path(t1))
    diff: Counter = Counter()
    for p in set(gb) | set(ga):
        xb = {d["id"]: d for d in gb.get(p, [])}
        xa = {d["id"]: d for d in ga.get(p, [])}
        if set(xb) != set(xa):
            raise AssertionError(f"{p} 条目集合不同：{sorted(set(xb) ^ set(xa))[:5]}")
        for i, d in xb.items():
            d = dict(d)
            # source_events 是并集，顺序随重放先后，不算内容：按集合比
            if isinstance(d.get("source_events"), list):
                d["source_events"] = sorted({copies.get(x, x) for x in d["source_events"]})
            a_ = dict(xa[i])
            if isinstance(a_.get("source_events"), list):
                a_["source_events"] = sorted(a_["source_events"])
            if dumps(d) != dumps(a_):
                ka = {k for k in set(d) | set(a_) if d.get(k) != a_.get(k)}
                raise AssertionError(f"{p} {i} 不同：{sorted(ka)}  {d.get('source_events')} vs {a_.get('source_events')}")
            diff["same"] += 1
    return {"shards": len(ga), "items": diff["same"]}


def main(argv=None) -> None:
    import argparse
    import sys
    import tempfile
    from pathlib import Path

    from ..datastore.client import PgSource
    from ..datastore.connect import connect
    from ..datastore.importer import import_scans
    from ..datastore.materialize import materialize
    from ..datastore.scope import scan_files

    ap = argparse.ArgumentParser(prog="python -m open_guji_cv.feedback.migrate_dedupe", description=__doc__.splitlines()[0])
    ap.add_argument("--ws", required=True, action="append")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    conn = connect()
    src = PgSource(conn)
    for ws in args.ws:
        rev = src.status()
        with tempfile.TemporaryDirectory() as tmp:
            materialize(src, ws, tmp, prefixes=("workspace.yaml", "feedback/"), with_images=False)
            root = Path(tmp)
            before = {f.relative_to(root).as_posix(): f.read_bytes() for f in root.rglob("*") if f.is_file()}
        m = migrate(before)
        changed = m.changed(before)
        rep = {"ws": ws, "rev": rev, **m.report(), "changed_files": changed}
        if changed:
            rep["verify"] = verify(before, m)
            rep["gold_rebuild"] = gold_rebuild_check(before, m)
            sc = scan_files([(p, (lambda b=m.files[p]: b)) for p in changed if p in m.files]
                            + [("workspace.yaml", (lambda b=before["workspace.yaml"]: b))], ws)
            sc.ws = ws

            def guard(cur, ws=ws, rev=rev):
                cur.execute("SELECT 1 FROM changes WHERE ws = %s AND rev > %s LIMIT 1", (ws, rev))
                if cur.fetchone():
                    raise SystemExit(f"{ws} 在 rev {rev} 之后有新写入；重跑本脚本")

            conn.commit()                    # 见 migrate_v1.main：读过之后要先结束隐式事务
            ir = import_scans(conn, [sc], label=f"migrate_dedupe:{ws}@{rev}", actor="migrate_dedupe",
                              dry_run=not args.apply, source="migrate", guard=guard,
                              allow_delete=True, only_paths=set(changed))
            rep["import"] = ir.as_dict()
            if args.apply and not src.changes_since(ws, rev, limit=1):
                raise SystemExit(f"{ws}：写完库里没有新变更，写入没生效")
        json.dump(rep, sys.stdout, ensure_ascii=False, indent=1)
        print()


if __name__ == "__main__":
    main()
