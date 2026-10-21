"""人裁事件 v1 规整：把规范 §9 的历史遗留一次改成现行格式（2026-10-21，用户 10-20 定「不留历史包袱」）。

人裁日志只追加，平时不改行。这一次是例外：几类老数据与规范不符，读者为它们各留了一段兼容；
把数据改对，读者就只剩一种格式。改的东西（规范 §9）：

| 号 | 改什么 | 怎么改 |
|---|---|---|
| T-1 | 事件的 `batch` 与所在文件不符 | 挪进 `safe_batch_name(batch)` 那个文件；挪进去后批内 seq/id 撞了，整批按 `replay_key` 重编 1..n |
| T-2 | id 不是 `evt_<batch>_<seq:06d>` | 改成规范 id |
| T-5 | `anchor.product_key` 混着两种形状 | 只留控制台那种 `{step, key, fingerprint}`；`{<cells 步>: sha256}` 挪到 `anchor.cells_sha`；补锚档里的字符串 `product_key` 同样挪 |
| F-2 | `target.book/page/col/slot` 全空 | 从 key 补（`keys.parse_card_id`） |
| F-3 | `payload.client_ts` 是秒 | ×1000 取整成毫秒 |
| F-8 | 刻例库升格记账 `feedback/events/promote.jsonl`（整文件 `kind=promote`） | 整文件挪到 `feedback/promote.jsonl`，内容不动 |

id 一改，引用它的地方跟着改：
- `consumed/<消费者>.jsonl`：旧 id 已不存在 → 原地换成新 id；旧 id 还在（T-1 撞号，一个 id 当时代表两条事件、
  只记了一行账）→ 原行不动，文件末尾补一行新 id（ts/note 照抄）。消费过的仍算消费过，不会重放一遍。
- `verdicts/**/items.jsonl` 的 `source_events`：按条目 id（= 事件 `target.key`）认是哪一条事件；金标条目的
  `anchor.product_key` 也只留 `{step, key, fingerprint}`。
- `anchors/<册>.jsonl` 的 `event`。

不动的：`ts`（规范 §4：落盘时间，T-4 是定义不是毛病）、批次名（T-3：批次名不带语义，没有读者从它推册号）、
任何裁决内容。核对（`verify`）保证：事件条数不变、按 `replay_key` 的重放顺序不变、除上表字段外逐字段相同、
`gold rebuild` 的结果只差上表那几处。

纯函数部分（`migrate`/`verify`）只吃 `{相对路径: bytes}`，可单测；`main` 连中心库：
`python -m open_guji_cv.feedback.migrate_v1 --ws <工作区> [--apply]`。不带 `--apply` 只报计划、不写库。
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .keys import parse_card_id

EVENT_DIRS = ("feedback/events/", "feedback/vision/")
CONSUMED_DIR = "feedback/consumed/"
VERDICTS_DIR = "feedback/verdicts/"
ANCHORS_DIR = "feedback/anchors/"
PRODUCT_KEY_FIELDS = ("step", "key", "fingerprint")
_ID = re.compile(r"^evt_(?P<batch>.+)_(?P<seq>\d{6,})$")
_BAD_IN_NAME = ':*?"<>|/\\\x00'          # = EventLog._BAD_IN_NAME（不为它 import EventLog）


#: 刻例库升格记账（``ops/glyphlib.py`` 写）：不是人裁事件，不放 ``feedback/events/``（规范 §9 F-8）
PROMOTE_PATH = "feedback/promote.jsonl"


def safe_batch_name(batch: str) -> str:
    out = "".join("-" if c in _BAD_IN_NAME else c for c in batch)
    return out.strip(". ") or "batch"


def event_id(batch: str, seq: int) -> str:
    return f"evt_{batch}_{seq:06d}"


def dumps(d: dict) -> str:
    """事件、金标、记账行的写法（`EventLog.append`／`GoldStore._write_all` 同口径）。"""
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


def _replay_key(e: dict) -> tuple:
    return (e["ts"], e["batch"], e["seq"])


def _is_event(d) -> bool:
    return isinstance(d, dict) and isinstance(d.get("target"), dict) and {"id", "ts", "batch", "seq"} <= set(d)


@dataclass
class Rename:
    old: str
    new: str
    key: str
    src: str          # 原文件


@dataclass
class Migration:
    files: dict[str, bytes]                                   # 改后的全部文件（含没改的）
    renames: list[Rename] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)
    examples: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    skipped: dict[str, int] = field(default_factory=dict)     # 不是人裁事件的行（如刻例库的 promote）：不碰

    def note(self, code: str, ex: str) -> None:
        self.counts[code] += 1
        if len(self.examples[code]) < 5:
            self.examples[code].append(ex)

    def changed(self, before: dict[str, bytes]) -> list[str]:
        paths = set(before) | set(self.files)
        return sorted(p for p in paths if before.get(p) != self.files.get(p))

    def report(self) -> dict:
        return {"counts": dict(sorted(self.counts.items())), "renames": len(self.renames),
                "examples": {k: v for k, v in sorted(self.examples.items())}, "skipped": self.skipped}


def _lines(b: bytes) -> list[str]:
    return [x for x in b.decode("utf-8").splitlines() if x.strip()]


def _join(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


# ─── 逐条 ─────────────────────────────────────────────────────────────

def split_product_key(anchor: dict, cells_step: str | None) -> bool:
    """T-5：`product_key` 里不是 step/key/fingerprint 的键挪到 `cells_sha`；字符串形状（补锚档）整个挪。→ 改了没有。"""
    pk = anchor.get("product_key")
    if pk is None:
        return False
    if isinstance(pk, str):
        if not cells_step:
            raise ValueError("补锚档里有字符串 product_key，但不知道这个工作区的 cells 步")
        moved = {cells_step: pk}
        keep: dict = {}
    elif isinstance(pk, dict):
        moved = {k: v for k, v in pk.items() if k not in PRODUCT_KEY_FIELDS}
        if not moved:
            return False
        keep = {k: v for k, v in pk.items() if k in PRODUCT_KEY_FIELDS}
    else:
        return False
    cs = dict(anchor.get("cells_sha") or {})
    for k, v in moved.items():
        if cs.get(k, v) != v:
            raise ValueError(f"cells_sha.{k} 已有不同的值：{cs[k]} ≠ {v}")
        cs[k] = v
    anchor["cells_sha"] = cs
    if keep:
        anchor["product_key"] = keep
    else:
        del anchor["product_key"]
    return True


def normalize_event(e: dict, cells_step: str | None, m: Migration, where: str) -> bool:
    """F-2、F-3、T-5，原地改。→ 改了没有。"""
    changed = False
    t = e["target"]
    if all(t.get(k) is None for k in ("book", "page", "col", "slot")):
        got = {k: v for k, v in parse_card_id(t.get("key") or "").items() if v is not None}
        if got:
            t.update(got)
            m.note("F-2 target 补字段", f"{where} {e['id']} {t['key']}")
            changed = True
    p = e.get("payload")
    if isinstance(p, dict):
        ct = p.get("client_ts")
        if isinstance(ct, (int, float)) and not isinstance(ct, bool) and 0 < ct < 1e11:
            p["client_ts"] = int(round(ct * 1000))
            m.note("F-3 client_ts 秒→毫秒", f"{where} {e['id']} {ct}")
            changed = True
    a = t.get("anchor")
    if isinstance(a, dict) and split_product_key(a, cells_step):
        m.note("T-5 product_key 拆出 cells_sha", f"{where} {e['id']}")
        changed = True
    return changed


# ─── 主流程 ───────────────────────────────────────────────────────────

def migrate(files: dict[str, bytes], cells_step: str | None = None) -> Migration:
    """``files``：一个工作区 ``feedback/`` 下的文本文件。``cells_step``：补锚档字符串 product_key 指的那一步。"""
    m = Migration(files=dict(files))
    # 0. F-8：刻例库的升格记账（整文件都是 kind=promote）不是人裁事件，挪出 feedback/events/
    for path in sorted(files):
        if path.startswith("feedback/events/") and path.endswith(".jsonl"):
            ls = _lines(files[path])
            if ls and all(json.loads(x).get("kind") == "promote" for x in ls):
                dst = PROMOTE_PATH
                if dst in m.files and m.files[dst] != files[path]:
                    raise SystemExit(f"{dst} 已存在且内容不同，{path} 挪不过去")
                m.files[dst] = m.files.pop(path)
                m.note("F-8 升格记账挪出事件目录", f"{path} → {dst}（{len(ls)} 行）")
    files = m.files
    # 1. 读事件，逐条规整
    by_file: dict[str, list] = {}           # 路径 → [事件 dict 或 原样保留的行]
    dirty: set[str] = set()
    reorder: set[str] = set()               # 挪进了事件或重编过 seq 的文件：按 seq 重排
    for path in sorted(files):
        if not path.endswith(".jsonl") or not any(path.startswith(d) for d in EVENT_DIRS):
            continue
        rows = []
        for n, line in enumerate(_lines(files[path]), 1):
            d = json.loads(line)
            if not _is_event(d) or d.get("kind") == "promote":
                m.skipped[path] = m.skipped.get(path, 0) + 1
                rows.append(line)
                continue
            d["_src"], d["_raw"], d["_orig"] = path, line, json.loads(line)
            if normalize_event(d, cells_step, m, f"{path}:{n}"):
                dirty.add(path)
            rows.append(d)
        by_file[path] = rows
    # 2. T-1：batch 与文件不符的挪走
    for path in list(by_file):
        stay = []
        for d in by_file[path]:
            if isinstance(d, dict):
                want = str(PurePosixPath(path).parent / f"{safe_batch_name(d['batch'])}.jsonl")
                if want != path:
                    by_file.setdefault(want, []).append(d)
                    dirty |= {path, want}
                    reorder.add(want)
                    m.note("T-1 挪进本批次文件", f"{path} → {want} {d['id']}")
                    continue
            stay.append(d)
        by_file[path] = stay
    # 3. 批内 seq 撞号 → 整批按 replay_key 重编；id 不规范 → 改
    for path, rows in by_file.items():
        evs = [d for d in rows if isinstance(d, dict)]
        for batch in {d["batch"] for d in evs}:
            mine = [d for d in evs if d["batch"] == batch]
            seqs = Counter(d["seq"] for d in mine)
            if any(n > 1 for n in seqs.values()):
                for i, d in enumerate(sorted(mine, key=_replay_key), 1):
                    if d["seq"] != i:
                        m.note("T-1 批内撞号重编 seq", f"{path} {d['id']} seq {d['seq']}→{i}")
                        d["seq"] = i
                        dirty.add(path)
                        reorder.add(path)
            for d in mine:
                want = event_id(batch, d["seq"])
                if d["id"] != want:
                    if not _ID.match(d["id"]) or _ID.match(d["id"])["batch"] != batch:
                        m.note("T-2 id 改成 evt_<batch>_<seq>", f"{path} {d['id']} → {want}")
                    m.renames.append(Rename(d["id"], want, d["target"].get("key", ""), d["_src"]))
                    d["id"] = want
                    dirty.add(path)
        # 文件内顺序：挪进来的、重编过的按 seq 排；别的文件保持原行序
        if path in reorder:
            keep = [d for d in rows if not isinstance(d, dict)]
            by_file[path] = keep + sorted(evs, key=lambda d: (d["batch"], d["seq"]))
    ids = Counter(d["id"] for rows in by_file.values() for d in rows if isinstance(d, dict))
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise ValueError(f"规整后仍有重复 id：{dup[:5]}")
    for path in dirty:
        out = []
        for d in by_file[path]:
            if isinstance(d, dict):
                clean = {k: v for k, v in d.items() if not k.startswith("_")}
                out.append(d["_raw"] if clean == d["_orig"] else dumps(clean))
            else:
                out.append(d)
        m.files[path] = _join(out)
    # 4. 引用
    _fix_consumed(m, set(ids))
    _fix_verdicts(m, set(ids))
    _fix_anchors(m, set(ids), cells_step)
    return m


def _targets(m: Migration) -> dict[str, list[Rename]]:
    out: dict[str, list[Rename]] = defaultdict(list)
    for r in m.renames:
        out[r.old].append(r)
    return out


def _fix_consumed(m: Migration, now_ids: set[str]) -> None:
    tg = _targets(m)
    if not tg:
        return
    for path in sorted(m.files):
        if not (path.startswith(CONSUMED_DIR) and path.endswith(".jsonl")):
            continue
        lines = _lines(m.files[path])
        have = {json.loads(x).get("event") for x in lines}
        out, extra, changed = [], [], False
        for line in lines:
            d = json.loads(line)
            old = d.get("event")
            if old not in tg:
                out.append(line)
                continue
            news = [r.new for r in tg[old]]
            if old in now_ids:                              # 旧 id 还在（撞号拆开）：原行留着，补新 id
                out.append(line)
            else:
                first, news = news[0], news[1:]
                out.append(json.dumps({**d, "event": first}, ensure_ascii=False))
                have.add(first)
                m.note("记账 id 原地改", f"{path} {old} → {first}")
                changed = True
            for n in news:
                if n != old and n not in have:
                    # 补的行放文件末尾：记账主键是行号，插在中间会让后面整段行号都变
                    extra.append(json.dumps({**d, "event": n}, ensure_ascii=False))
                    have.add(n)
                    m.note("记账补新 id", f"{path} {old} → +{n}")
                    changed = True
        if changed:
            m.files[path] = _join(out + extra)


def _fix_verdicts(m: Migration, now_ids: set[str]) -> None:
    tg = _targets(m)
    for path in sorted(m.files):
        if not (path.startswith(VERDICTS_DIR) and path.endswith(".jsonl")):
            continue
        out, changed = [], False
        for line in _lines(m.files[path]):
            d = json.loads(line)
            touched = False
            se = d.get("source_events")
            if tg and isinstance(se, list) and any(s in tg for s in se):
                new = []
                for s in se:
                    rs = tg.get(s)
                    if not rs:
                        new.append(s)
                        continue
                    hit = [r for r in rs if r.key == d.get("id")]
                    if hit:
                        new += [r.new for r in hit]
                    elif s in now_ids:
                        new.append(s)
                    else:
                        new += [r.new for r in rs]
                new = sorted(set(new))
                if new != se:
                    d["source_events"] = new
                    m.note("金标 source_events 跟着改", f"{path} {d.get('id')} {se} → {new}")
                    touched = True
            a = d.get("anchor")
            if isinstance(a, dict) and isinstance(a.get("product_key"), dict):
                pk = {k: v for k, v in a["product_key"].items() if k in PRODUCT_KEY_FIELDS}
                if pk != a["product_key"]:
                    if pk:
                        a["product_key"] = pk
                    else:
                        del a["product_key"]
                    m.note("金标 anchor.product_key 只留 step/key/fingerprint", f"{path} {d.get('id')}")
                    touched = True
            out.append(dumps(d) if touched else line)
            changed |= touched
        if changed:
            m.files[path] = _join(out)


def _fix_anchors(m: Migration, now_ids: set[str], cells_step: str | None) -> None:
    tg = _targets(m)
    for path in sorted(m.files):
        if not (path.startswith(ANCHORS_DIR) and path.endswith(".jsonl")):
            continue
        out, changed = [], False
        for line in _lines(m.files[path]):
            d = json.loads(line)
            touched = False
            rs = tg.get(d.get("event"))
            if rs:
                hit = [r for r in rs if r.key == d.get("key")] or ([] if d["event"] in now_ids else rs)
                if len(hit) > 1:
                    raise ValueError(f"{path}: 补锚档 {d['event']} 对得上不止一条事件")
                if hit:
                    m.note("补锚档 event 跟着改", f"{path} {d['event']} → {hit[0].new}")
                    d["event"] = hit[0].new
                    touched = True
            a = d.get("anchor")
            if isinstance(a, dict) and split_product_key(a, cells_step):
                m.note("T-5 补锚档 product_key → cells_sha", f"{path} {d.get('event')}")
                touched = True
            out.append(json.dumps(d, ensure_ascii=False) if touched else line)
            changed |= touched
        if changed:
            m.files[path] = _join(out)


# ─── 核对 ─────────────────────────────────────────────────────────────

#: 迁移允许改的字段（其余逐字段必须相同）
ALLOWED = {"id", "seq", "target.book", "target.page", "target.col", "target.slot",
           "payload.client_ts", "target.anchor.product_key", "target.anchor.cells_sha"}


def _events(files: dict[str, bytes]) -> list[tuple[str, dict]]:
    out = []
    for path in sorted(files):
        if path.endswith(".jsonl") and any(path.startswith(d) for d in EVENT_DIRS):
            for line in _lines(files[path]):
                d = json.loads(line)
                if _is_event(d) and d.get("kind") != "promote":
                    out.append((path, d))
    return out


def _flat(d, pre="") -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict) and pre + k in ("target", "payload", "target.anchor"):
            out.update(_flat(v, f"{pre}{k}."))
        else:
            out[pre + k] = v
    return out


def verify(before: dict[str, bytes], m: Migration) -> dict:
    """事件一条不少、重放顺序不变、只改了 `ALLOWED` 里的字段；改后再迁一遍是空操作。→ 统计；不对就抛。"""
    b, a = _events(before), _events(m.files)
    if len(b) != len(a):
        raise AssertionError(f"事件条数变了：{len(b)} → {len(a)}")
    ren = {(r.src, r.old, r.key): r.new for r in m.renames}
    after = {d["id"]: d for _, d in a}
    if len(after) != len(a):
        raise AssertionError("改后 id 不唯一")
    diffs: Counter = Counter()
    mapped = []
    for src, d in b:
        new = ren.get((src, d["id"], d["target"].get("key", "")), d["id"])
        if new not in after:
            raise AssertionError(f"{src} {d['id']} 改后找不到（应为 {new}）")
        mapped.append((d, after[new]))
        fb, fa = _flat(d), _flat(after[new])
        for k in set(fb) | set(fa):
            if fb.get(k) != fa.get(k):
                if k not in ALLOWED:
                    raise AssertionError(f"{d['id']} 的 {k} 不该改：{fb.get(k)!r} → {fa.get(k)!r}")
                diffs[k] += 1
    if len({id(x) for _, x in mapped}) != len(mapped):
        raise AssertionError("两条旧事件对到了同一条新事件")
    order_b = [after_id for after_id in (x["id"] for _, x in sorted(mapped, key=lambda p: _replay_key(p[0])))]
    order_a = [d["id"] for _, d in sorted(a, key=lambda p: _replay_key(p[1]))]
    if order_b != order_a:
        k = next(i for i, (x, y) in enumerate(zip(order_b, order_a)) if x != y)
        raise AssertionError(f"重放顺序变了，第 {k} 条：{order_b[k]} vs {order_a[k]}")
    again = migrate(m.files, None)
    if again.changed(m.files):
        raise AssertionError(f"再迁一遍还有改动：{again.changed(m.files)[:5]}")
    return {"events": len(a), "field_changes": dict(sorted(diffs.items()))}


def gold_rebuild_check(before: dict[str, bytes], m: Migration) -> dict:
    """`gold rebuild` 改前、改后各跑一遍（空裁决表起步），改前的结果套上同样的规整后必须与改后相同（不比 history）。"""
    import tempfile
    from pathlib import Path

    from ..gold.store import GoldStore
    from ..gold.transfer import rebuild_verdicts
    from .events import EventLog

    def run(files: dict[str, bytes], root: Path) -> dict[str, bytes]:
        for p, data in files.items():
            if any(p.startswith(d) for d in EVENT_DIRS) or p == "feedback/routes.yaml":
                f = root / p
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
        store = GoldStore(root / "gold")
        rebuild_verdicts(EventLog(root / "feedback"), store)
        out = {}
        for f in sorted((root / "gold").rglob("items.jsonl")):
            lines = []
            for line in _lines(f.read_bytes()):
                d = json.loads(line)
                d.pop("history", None)
                lines.append(dumps(d))
            out[VERDICTS_DIR + f.relative_to(root / "gold").as_posix()] = _join(lines)
        return out

    with tempfile.TemporaryDirectory() as t0, tempfile.TemporaryDirectory() as t1:
        gb, ga = run(before, Path(t0)), run(m.files, Path(t1))
    want = Migration(files=dict(gb), renames=m.renames)
    _fix_verdicts(want, {d["id"] for _, d in _events(m.files)})
    bad = sorted(p for p in set(want.files) | set(ga) if want.files.get(p) != ga.get(p))
    if bad:
        p = bad[0]
        x, y = _lines(want.files.get(p, b"")), _lines(ga.get(p, b""))
        k = next((i for i, (u, v) in enumerate(zip(x, y)) if u != v), min(len(x), len(y)))
        raise AssertionError(f"gold rebuild 结果不同：{bad[:5]}；{p} 第 {k} 行\n  期望 {x[k][:300] if k < len(x) else None}"
                             f"\n  实得 {y[k][:300] if k < len(y) else None}")
    return {"shards": len(ga), "items": sum(len(_lines(v)) for v in ga.values())}


# ─── 连中心库 ─────────────────────────────────────────────────────────

def _cells_step(files: dict[str, bytes]) -> str | None:
    """事件里 `{<步>: sha}` 形状的 product_key 用的是哪一步（补锚档的字符串 product_key 指同一步）。"""
    steps = Counter()
    for _, d in _events(files):
        pk = ((d["target"].get("anchor") or {}).get("product_key"))
        if isinstance(pk, dict):
            steps.update(k for k in pk if k not in PRODUCT_KEY_FIELDS)
    if len(steps) > 1:
        raise ValueError(f"cells 步不止一种：{dict(steps)}")
    return next(iter(steps), None)


def main(argv=None) -> None:
    import argparse
    import sys

    from ..datastore.client import PgSource
    from ..datastore.connect import connect
    from ..datastore.importer import import_scans
    from ..datastore.materialize import materialize
    from ..datastore.scope import scan_files

    ap = argparse.ArgumentParser(prog="python -m open_guji_cv.feedback.migrate_v1", description=__doc__.splitlines()[0])
    ap.add_argument("--ws", required=True, action="append", help="中心库里的工作区名（可多次）")
    ap.add_argument("--apply", action="store_true", help="真写库；不给只报计划")
    ap.add_argument("--out", default=None, help="改前改后的文件落到这个目录备查")
    ap.add_argument("--no-gold-check", action="store_true", help="跳过 gold rebuild 对比（慢）")
    args = ap.parse_args(argv)
    conn = connect()
    src = PgSource(conn)
    import tempfile
    from pathlib import Path
    for ws in args.ws:
        rev = src.status()
        with tempfile.TemporaryDirectory() as tmp:
            materialize(src, ws, tmp, prefixes=("workspace.yaml", "feedback/"), with_images=False)
            root = Path(tmp)
            before = {f.relative_to(root).as_posix(): f.read_bytes() for f in root.rglob("*") if f.is_file()}
        m = migrate(before, _cells_step(before))
        changed = m.changed(before)
        rep = {"ws": ws, "rev": rev, **m.report(), "changed_files": changed}
        if changed:
            rep["verify"] = verify(before, m)
            if not args.no_gold_check:
                rep["gold_rebuild"] = gold_rebuild_check(before, m)
        if args.out:
            for tag, fs in (("before", before), ("after", m.files)):
                for p in changed:
                    if p in fs:
                        f = Path(args.out) / ws / tag / p
                        f.parent.mkdir(parents=True, exist_ok=True)
                        f.write_bytes(fs[p])
        if changed:
            items = [(p, (lambda b=m.files[p]: b)) for p in changed if p in m.files]
            items.append(("workspace.yaml", (lambda b=before["workspace.yaml"]: b)))
            sc = scan_files(items, ws)
            sc.ws = ws

            def guard(cur, ws=ws, rev=rev):
                cur.execute("SELECT 1 FROM changes WHERE ws = %s AND rev > %s LIMIT 1", (ws, rev))
                if cur.fetchone():
                    raise SystemExit(f"{ws} 在 rev {rev} 之后有新写入；重跑本脚本")

            # 上面的读已经让连接隐式开了事务；不先结束它，import_scans 的 transaction() 只是个保存点，
            # 关连接时整次写入跟着回滚（10-21 第一次 --apply 就是这样白跑的，库没动）
            conn.commit()
            ir = import_scans(conn, [sc], label=f"migrate_v1:{ws}@{rev}", actor="migrate_v1",
                              dry_run=not args.apply, source="migrate", guard=guard,
                              allow_delete=True, only_paths=set(changed))
            rep["import"] = ir.as_dict()
            if args.apply and not src.changes_since(ws, rev, limit=1):
                raise SystemExit(f"{ws}：写完库里没有新变更，写入没生效")
        json.dump(rep, sys.stdout, ensure_ascii=False, indent=1)
        print()


if __name__ == "__main__":
    main()
