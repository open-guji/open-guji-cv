"""`guji glyphlib build`：从一本书的字形库精选刻例，出共享刻例库的新版本（共享方案 3.2 节，S5）。

共享刻例库每版一个中心库只读工作区 ``glyphlib-<族>-v<N>``，里面只有 ``workspace.yaml``、
``output/glyph_store/`` 和记升格来源的 ``feedback/promote.jsonl``。刻例图逐字节照搬来源书的
（R2 里按 sha 存，同一张图不另存一份）；实例 id、来源 id 加上来源工作区前缀，免得和借它的书撞号。

选哪些刻例（门槛由 sheldon 定，见方案第六节）：
- 来源书人裁过的实例（``label_status='human'``），且在至少 ``min_batches`` 个不同批次被确认过
  （``confirm`` 事件 ``v=confirm`` 且字形与库里一致，或 ``cell_review`` 选了这个字）；
- 体检（``glyph_audit``）没标过异常，不是近似字（``approx_labels``）；
- 每个字最多 ``per_char`` 张，确认批次多的优先，同数按实例 id。

这里只读字形库真源的文本文件（不要 glyph.db），出的库再 ``rebuild_from_store`` 一遍核对能装、
``export_store`` 导出规范格式。推进中心库由 ``publish`` 以升级脚本身份做（``push(shared_writer=True)``）。
"""
from __future__ import annotations

import datetime
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

GS = "output/glyph_store"


def _read(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _safe(iid: str) -> str:
    from ..clustering.glyph_db import _safe as s
    return s(iid)


def cell_key(iid: str) -> str:
    """实例 id → 人裁事件里的格号：``v2:vol01:57:8:2`` → ``vol01:57:8:2``；``vol01:10:4:17`` 原样。"""
    p = iid.split(":")
    return ":".join(p[1:]) if len(p) == 5 else iid


def _confirm_batches(events_dir: Path) -> tuple[dict[tuple[str, str], set[str]], set[str]]:
    """人裁事件 → ({(格号, 字): 确认过的批次}, 体检标过异常的实例 id)。"""
    conf: dict[tuple[str, str], set[str]] = defaultdict(set)
    bad: set[str] = set()
    from ..core.event_files import iter_event_dicts
    for e in iter_event_dicts(Path(events_dir)):          # 换图源的页表 rev 判据在这里一并生效
        p = e.get("payload") or {}
        k = (e.get("target") or {}).get("key")
        kind = e.get("kind")
        if kind == "confirm" and p.get("v") == "confirm" and p.get("shape"):
            conf[(k, p["shape"])].add(str(e.get("batch")))
        elif kind == "cell_review" and p.get("verdict") == "pick" and p.get("picked"):
            conf[(k, p["picked"])].add(str(e.get("batch")))
        elif kind == "glyph_audit":
            iid = p.get("instance_id") or k
            if iid and (p.get("v") != "ok" or p.get("flags")):
                bad.add(str(iid))
    return conf, bad


def select(store: Path, events_dir: Path, *, min_batches: int = 2, per_char: int = 3) -> tuple[list[dict], dict]:
    """按门槛从字形库真源 ``store`` 里挑刻例。返回 (选中的 [{instance_id, char, batches}], 统计)。"""
    store = Path(store)
    conf, bad = _confirm_batches(events_dir)
    approx = {r["instance_id"] for r in _read(store / "approx_labels.jsonl")}
    shape = {r["instance_id"]: r["char"] for r in _read(store / "exemplars.jsonl")}
    stats: Counter = Counter()
    cands: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for f in sorted((store / "instances").glob("*.jsonl")):
        for r in _read(f):
            iid = r["instance_id"]
            if r.get("label_status") != "human":
                continue
            stats["human"] += 1
            ch = shape.get(iid)
            if ch is None:
                stats["no_exemplar"] += 1
                continue
            if iid in bad or iid in approx:
                stats["audit_or_approx"] += 1
                continue
            n = len(conf.get((cell_key(iid), ch), ()))
            if n < min_batches:
                stats["too_few_confirms"] += 1
                continue
            cands[ch].append((n, iid))
    picked = []
    for ch in sorted(cands):
        for n, iid in sorted(cands[ch], key=lambda x: (-x[0], x[1]))[:per_char]:
            picked.append({"instance_id": iid, "char": ch, "batches": n})
    stats.update(passed=sum(len(v) for v in cands.values()), picked=len(picked), chars=len(cands))
    return picked, dict(stats)


def write_store(src_store: Path, picked: list[dict], out_store: Path, *, src_ws: str, edition: str) -> dict:
    """把选中的刻例写成一个字形库真源（未规范化；``build`` 再装库、导出一遍）。"""
    from ..clustering.glyph_db import K_MIN
    src_store, out_store = Path(src_store), Path(out_store)
    sel = {p["instance_id"]: p for p in picked}
    new = lambda iid: f"{src_ws}:{iid}"                       # noqa: E731
    new_src = lambda sid: f"{src_ws}.{sid}"                    # noqa: E731
    if out_store.exists():
        shutil.rmtree(out_store)
    (out_store / "instances").mkdir(parents=True)
    (out_store / "patches").mkdir()
    (out_store / "events").mkdir()
    used_src: set[str] = set()
    for f in sorted((src_store / "instances").glob("*.jsonl")):
        rows = []
        for r in _read(f):
            if r["instance_id"] not in sel:
                continue
            png = src_store / "patches" / f"{_safe(r['instance_id'])}.png"
            if not png.exists():
                raise FileNotFoundError(f"来源库缺刻例图 {png}")
            shutil.copyfile(png, out_store / "patches" / f"{_safe(new(r['instance_id']))}.png")
            used_src.add(r["source_id"])
            rows.append({**r, "instance_id": new(r["instance_id"]), "source_id": new_src(r["source_id"])})
        for sid in {r["source_id"] for r in rows}:
            with open(out_store / "instances" / f"{sid}.jsonl", "a", encoding="utf-8") as fh:
                for r in sorted((x for x in rows if x["source_id"] == sid), key=lambda x: x["instance_id"]):
                    fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    def dump(name: str, recs: list[dict]) -> None:
        with open(out_store / name, "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    dump("sources.jsonl", [{**r, "source_id": new_src(r["source_id"]), "edition_tag": edition,
                            "notes": f"共享刻例库 {edition}：从 {src_ws} 的来源 {r['source_id']} 精选。"
                                     + (f"原注：{r['notes']}" if r.get("notes") else "")}
                           for r in _read(src_store / "sources.jsonl") if r["source_id"] in used_src])
    n_by = Counter(p["char"] for p in picked)
    gl = {r["char"]: r for r in _read(src_store / "glyphs.jsonl")}
    dump("glyphs.jsonl", [{**{k: gl.get(ch, {}).get(k) for k in ("ids", "semantic", "unicode_cp")},
                           "char": ch, "edition_tag": edition, "n_confirmed": n,
                           "status": "stable" if n >= K_MIN else "sparse", "updated_at": now}
                          for ch, n in sorted(n_by.items())])
    dump("exemplars.jsonl", [{"added_at": now, "char": p["char"], "edition_tag": edition,
                              "instance_id": new(p["instance_id"]), "role": "seed"}
                             for p in sorted(picked, key=lambda x: (x["char"], x["instance_id"]))])
    adm = {r["instance_id"]: r for r in _read(src_store / "admissions.jsonl")}
    dump("admissions.jsonl", [{"admitted_at": now, "char": adm.get(p["instance_id"], {}).get("char", p["char"]),
                               "evidence": json.dumps({"promoted_from": {"ws": src_ws, "instance_id": p["instance_id"]},
                                                       "confirm_batches": p["batches"],
                                                       "src_provenance": adm.get(p["instance_id"], {}).get("provenance")},
                                                      ensure_ascii=False, sort_keys=True),
                               "instance_id": new(p["instance_id"]), "provenance": "promote"}
                              for p in sorted(picked, key=lambda x: x["instance_id"])])
    dump("meta.jsonl", [{"key": "book_edition", "value": edition}])
    return {"instances": len(picked), "chars": len(n_by), "sources": sorted(new_src(s) for s in used_src)}


def promote_events(picked: list[dict], *, src_ws: str, lib: str, actor: str | None, note: str,
                   thresholds: dict) -> list[dict]:
    """升格记账（方案 4.1 节）：一条刻例一行，进目标工作区的 ``feedback/promote.jsonl``。"""
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    batch = f"promote-{lib}"
    return [{"id": f"evt_{batch}_{i:06d}", "batch": batch, "seq": i, "kind": "promote", "actor": actor,
             "ts": ts, "payload": {"from_ws": src_ws, "from_instance": p["instance_id"], "char": p["char"],
                                   "confirm_batches": p["batches"], "thresholds": thresholds, "note": note},
             "target": {"book": None, "key": f"{src_ws}:{p['instance_id']}", "unit": "glyph"}}
            for i, p in enumerate(picked, 1)]


def lib_workdir(name: str, branch: str = "main") -> Path:
    """升级脚本用的共享刻例库工作区目录（只有 ``workspace.yaml`` 和标记；数据在数据目录）。"""
    from ..core.workspace import data_home
    from ..datastore.workcopy import SHARED_PREFIX
    if not name.startswith(SHARED_PREFIX):
        raise SystemExit(f"共享刻例库的工作区名要以 {SHARED_PREFIX} 开头（如 glyphlib-qkp-v1），收到 {name}")
    d = data_home() / branch.replace("/", "__") / ".shared" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "workspace.yaml").write_text(f"id: {name}\n", encoding="utf-8")
    (d / ".central.json").write_text(json.dumps({"ws": name, "branch": branch}) + "\n", encoding="utf-8")
    return d


def edition_of(name: str) -> str:
    """``glyphlib-qkp-v1`` → ``glyphlib-qkp``：字体族的 edition，跨版本不变（借哪版都按同一个族匹配）。"""
    base, _, v = name.rpartition("-v")
    return base if base and v.isdigit() else name


def build(src_ws_dir: Path, name: str, *, min_batches: int = 2, per_char: int = 3, actor: str | None = None,
          note: str = "", branch: str = "main") -> dict:
    """出共享刻例库 ``name`` 到本机（``$GUJI_DATA_HOME/<分支>/<name>/``），不推。"""
    from ..clustering.glyph_db import GlyphDB, export_store, rebuild_from_store
    from ..core.workspace import central_data_dir, central_marker, data_root
    src_ws_dir = Path(src_ws_dir)
    m = central_marker(src_ws_dir)
    if not m:
        raise SystemExit(f"{src_ws_dir} 没迁到中心库；先 guji db migrate／pull")
    src_ws = str(m["ws"])
    root = data_root(src_ws_dir) or src_ws_dir
    picked, stats = select(root / GS, root / "feedback" / "events", min_batches=min_batches, per_char=per_char)
    if not picked:
        raise SystemExit(f"按门槛（确认 ≥{min_batches} 个批次）一张刻例都没选出：{stats}")
    ws = lib_workdir(name, branch)
    data = central_data_dir(name, branch)
    tmp = data.parent / f".{name}.build.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    edition = edition_of(name)
    info = write_store(root / GS, picked, tmp / "raw", src_ws=src_ws, edition=edition)
    dbp = tmp / "check.sqlite"
    rebuild_from_store(tmp / "raw", dbp)                       # 装得进去才算数
    db = GlyphDB(dbp)
    try:
        export_store(db, data / GS)
    finally:
        db.close()
    thresholds = {"min_confirm_batches": min_batches, "per_char": per_char, "audit_clean": True,
                  "no_approx": True}
    ev = data / "feedback" / "promote.jsonl"            # 不是人裁事件，不进 feedback/events/（规范 §9 F-8）
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text("".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n"
                          for e in promote_events(picked, src_ws=src_ws, lib=name, actor=actor, note=note,
                                                  thresholds=thresholds)), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    return {"lib": name, "edition": edition, "from": src_ws, "data_dir": str(data), "workspace_dir": str(ws),
            "thresholds": thresholds, "select": stats, **info}


def publish(conn, name: str, *, actor: str | None = None, uploader=None, branch: str = "main",
            dry_run: bool = False) -> dict:
    """把本机出好的 ``name`` 推进中心库（升级脚本身份；``glyphlib-*`` 只能写一次）。"""
    from ..datastore.workcopy import push
    return push(conn, lib_workdir(name, branch), actor=actor, uploader=uploader, shared_writer=True,
                dry_run=dry_run)
