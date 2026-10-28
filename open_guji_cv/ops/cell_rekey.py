"""换图源重编页号后，按**格级对照表**把按格号寻址的数据改键（GUJI-748，设计稿 `doc/design/殿本换图源-siku-qiefen-v2.md` §三、§五）。

格级表（A31 出，`old_new_cells/<册>.tsv[.gz]`）列为 `旧格 新格 旧字 新字 类别 IoU 说明`，类别：
`同格`／`改号`（对上了，旧格 → 新格）、`删`（旧格在新图上没有对应）、`新增`（只有新格）。
本模块只认这张表，不按同编号猜，也不按页号平移。

改四样东西：

- **字形库**（`rekey_glyph_db`，直接改 glyph.db，改完照常 `guji store commit`／`glyph-db export` 出账本）：
  实例 id 是 `v2:` 加格键，`seed_admit._human_shapes` 按它当「这一格的人裁字形」一票定案，页号重编后旧 id
  会和新页同号的另一格撞上。对上的改成新格键（`instances`／`derived`／`exemplars`／`admissions`／
  `cluster_members`／`approx_labels`／`pairs` 一起改，`instances.page/col/idx` 跟着改、`bbox` 是旧图坐标，清空），
  对不上的（表里 `删`、表里没有、v1 的 idx 坐标刻例）**停放**到不按格寻址的 id：`<前缀>~r<旧页表rev>~册~页~列~格`。
  停放 id 里**不能有冒号**——`groups/freq._cell_key` 取冒号分的末 4 段、`ops/glyphlib.cell_key` 认 5 段去头，
  留着冒号尾巴就又被读回成格（cv#632 A24 复核 v4 第 1 条）。旧 id 都写一行 `evictions`（`reason=rekey:…`），
  中心库镜像与审计能分清「改键挪走」和「漏了」。
  所有本册实例先挪到临时 id 再落到终点：新旧页号互相交错（旧 3 页 → 新 1 页、旧 5 页 → 新 3 页…），一次改名会撞主键。
- **L2 文意答案表／按格 id 当键的 JSON**（`rekey_json`）：`cells` 字典（`group_clf/1`）或顶层字典的键改成新格；
  `删` 的去掉、记进 `rekey.dropped`。`ctx_key` 护栏不动，`CtxL3Backend` 查表时会按新格的上下文再验一遍。
- **金标／回放集 jsonl**（`rekey_jsonl`）：`id`／`key` 改成新格，`page`／`col`／`slot` 跟着改；`删` 的行挪到
  `<文件名>.retired.jsonl`，不留在原文件里（留着就可能按旧号对上新页的另一格）。
- **IDS 模板库出处**（`rekey_ids_bank`）：模板图内嵌，不受影响；`source.cells` 只是出处，改成新格，对不上的写停放 id
  （与 `books`／`keys`／`labels` 平行的列表，不能删项）。

验收（`verify_glyph_db`）：本册 `_human_shapes` 读得到的键全部落在新格集合里；给了迁移事件时，逐格核对库里人裁字形
与事件最后一票的字形一致（设计稿 §五「字形库」验收）。

只依赖标准库与 sqlite，不进任何 Step 的 `code_deps`。
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

#: 格键：`册:页:列:格[a|b]`，格可以是 -1（页边格）
CELL_RE = re.compile(r"^(?P<book>[^:~]+):(?P<page>\d+):(?P<col>-?\d+):(?P<slot>-?\d+)(?P<sub>[ab]?)$")
MATCHED = ("同格", "改号")
DELETED = "删"
ADDED = "新增"

#: 实例 id 里要跟着改名的表（`instance_id` 列）；`pairs` 两列另改
_ID_TABLES = ("instances", "derived", "exemplars", "admissions", "cluster_members", "approx_labels")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_cell(key: str) -> tuple[str, int, int, int, str] | None:
    m = CELL_RE.match(key or "")
    if not m:
        return None
    return m["book"], int(m["page"]), int(m["col"]), int(m["slot"]), m["sub"]


def parked_id(prefix: str, key: str, rev: int | str) -> str:
    """停放 id：`v2~r3~vol04~3~6~10`。不带冒号（见模块头）。"""
    return f"{prefix}~r{rev}~" + key.replace(":", "~")


@dataclass
class CellMap:
    """格级对照表。`move`：旧格 → 新格（同格／改号）；`deleted`：旧格 → 说明；`new_cells`：新图上全部格。"""
    book: str
    move: dict[str, str] = field(default_factory=dict)
    deleted: dict[str, str] = field(default_factory=dict)
    new_cells: set[str] = field(default_factory=set)
    iou: dict[str, float] = field(default_factory=dict)
    source: str = ""

    def lookup(self, old: str) -> tuple[str, str | None]:
        """→ (`move`|`deleted`|`unknown`, 新格或 None)。"""
        if old in self.move:
            return "move", self.move[old]
        if old in self.deleted:
            return "deleted", None
        return "unknown", None

    def counts(self) -> dict:
        return {"move": len(self.move), "renumbered": sum(1 for o, n in self.move.items() if o != n),
                "deleted": len(self.deleted), "new_cells": len(self.new_cells)}


def load_cell_map(path: str | Path) -> CellMap:
    """读格级表（`.tsv` 或 `.tsv.gz`）。只收一册；旧格、新格都必须一对一，不然报错（不静默挑一个）。"""
    p = Path(path)
    raw = gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")
    with raw as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    books: set[str] = set()
    cm = CellMap(book="", source=p.name)
    seen_new: dict[str, str] = {}
    for i, r in enumerate(rows, start=2):
        old, new, kind = (r.get("旧格") or "").strip(), (r.get("新格") or "").strip(), (r.get("类别") or "").strip()
        for k in (old, new):
            if k:
                pc = parse_cell(k)
                if pc is None:
                    raise ValueError(f"{p.name}:{i}: 格键 {k!r} 解析不了")
                books.add(pc[0])
        if new:
            cm.new_cells.add(new)
        if kind in MATCHED:
            if not old or not new:
                raise ValueError(f"{p.name}:{i}: 类别 {kind} 要旧格、新格都有")
            if old in cm.move or old in cm.deleted:
                raise ValueError(f"{p.name}:{i}: 旧格 {old} 出现两次")
            if new in seen_new:
                raise ValueError(f"{p.name}:{i}: 新格 {new} 被 {seen_new[new]} 和 {old} 同时对上")
            seen_new[new] = old
            cm.move[old] = new
            try:
                cm.iou[old] = float(r.get("IoU") or "nan")
            except ValueError:
                pass
        elif kind == DELETED:
            if not old:
                raise ValueError(f"{p.name}:{i}: 类别 删 要有旧格")
            if old in cm.move or old in cm.deleted:
                raise ValueError(f"{p.name}:{i}: 旧格 {old} 出现两次")
            cm.deleted[old] = (r.get("说明") or "").strip()
        elif kind == ADDED:
            continue
        else:
            raise ValueError(f"{p.name}:{i}: 不认识的类别 {kind!r}")
    if len(books) != 1:
        raise ValueError(f"{p.name}: 格级表要正好一册，读到 {sorted(books)}")
    cm.book = books.pop()
    return cm


# —— 字形库 ——

def _split_instance(iid: str, book: str) -> tuple[str, str] | None:
    """实例 id → (前缀, 格键)；不属于本册 → None。前缀 `v2`／`v1`／``（裸 id）。"""
    for pre in ("v2", "v1"):
        if iid.startswith(pre + ":"):
            key = iid[len(pre) + 1:]
            return (pre, key) if key.startswith(book + ":") else None
    if iid.startswith(book + ":"):
        return "", iid
    return None


def plan_glyph_db(c: sqlite3.Connection, cm: CellMap, rev: int | str) -> list[dict]:
    """只读推演：本册每个实例 → {old, new, action, char, prov, iou, why}。action：`rekey`／`park`。

    - `v2:<格>` 与裸 `<格>`（来源不是 v1，即格号坐标）：按表改，前缀照旧；表里 `删`／没有 → 停放；
    - v1 刻例（带 `v1:`，或裸 id 而来源 `pipeline_version='v1'`）：idx 坐标，格级表对不上 → 一律停放。"""
    v1_src = {r[0] for r in c.execute("SELECT source_id FROM sources WHERE pipeline_version='v1'")}
    adm = {r[0]: r[1] for r in c.execute("SELECT instance_id, provenance FROM admissions")}
    out = []
    for iid, src, label in c.execute("SELECT instance_id, source_id, label FROM instances ORDER BY instance_id"):
        sp = _split_instance(iid, cm.book)
        if sp is None:
            continue
        pre, key = sp
        rec = {"old": iid, "char": label, "prov": adm.get(iid), "iou": None, "why": ""}
        if pre == "v1" or (pre == "" and src in v1_src):
            rec.update(action="park", new=parked_id(pre or "v1", key, rev), why="v1_idx")
        else:
            kind, new = cm.lookup(key)
            if kind == "move":
                rec.update(action="rekey", new=f"{pre}:{new}" if pre else new, iou=cm.iou.get(key))
            else:
                rec.update(action="park", new=parked_id(pre or "bare", key, rev),
                           why="deleted:" + cm.deleted[key] if kind == "deleted" else "not_in_table")
        out.append(rec)
    return out


def _rename(c: sqlite3.Connection, old: str, new: str) -> None:
    for t in _ID_TABLES:
        c.execute(f"UPDATE {t} SET instance_id=? WHERE instance_id=?", (new, old))
    c.execute("UPDATE pairs SET inst_a=? WHERE inst_a=?", (new, old))
    c.execute("UPDATE pairs SET inst_b=? WHERE inst_b=?", (new, old))


def _has_table(c: sqlite3.Connection, name: str) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def rekey_glyph_db(db_path: str | Path, cm: CellMap, rev: int | str, *, dry_run: bool = False,
                   note: str = "siku-qiefen-v2") -> dict:
    """按格级表改本册实例 id。返回 `{summary, rows}`；`dry_run` 只推演不写。

    幂等：改过的库里本册已经没有旧坐标的 id——新格键会被当成「旧格」再查一次表，
    所以**同一册不能对同一个库改两遍**（换一张表也不行）；第二遍会被拒（库里已有本册的 `rekey:` 撤例记录）。"""
    db_path = str(db_path)
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) if dry_run else sqlite3.connect(db_path)
    try:
        tag = f"rekey:{note}:{cm.source}"
        # 按册判，不按表的文件名判：试算表和正式表文件名可以不同，换一张表再跑一遍同样会把新格键当旧格再改一次
        done = c.execute("SELECT reason FROM evictions WHERE reason LIKE ? AND "
                         "(instance_id LIKE ? OR instance_id LIKE ?) LIMIT 1",
                         (f"rekey:{note}:%", f"{cm.book}:%", f"%:{cm.book}:%")).fetchone()
        if done:
            raise SystemExit(f"✗ 这个库的 {cm.book} 已经改过键（evictions 里有 {done[0].split('->')[0]}…），不能再跑一遍")
        rows = plan_glyph_db(c, cm, rev)
        summary = _summarize(rows)
        if dry_run or not rows:
            return {"summary": summary, "rows": rows}
        missing = [t for t in _ID_TABLES if not _has_table(c, t)]
        if missing:
            raise SystemExit(f"✗ glyph.db 缺表 {missing}，先 `guji glyph-db rebuild`")
        now = _now()
        bbox_old = dict(c.execute("SELECT instance_id, bbox FROM instances"))
        for r in rows:                         # 两段改名：先全挪到临时 id，再落到终点
            _rename(c, r["old"], "__rekey__:" + r["old"])
        for r in rows:
            _rename(c, "__rekey__:" + r["old"], r["new"])
            r["bbox_old"] = bbox_old.get(r["old"])
            c.execute("INSERT INTO evictions (instance_id, char, reason, at) VALUES (?,?,?,?)",
                      (r["old"], r["char"], f"{tag}:{r['action']}->{r['new']}", now))
            if r["action"] == "rekey":
                _, pg, col, slot, _sub = parse_cell(r["new"].split(":", 1)[1] if r["new"].startswith(("v2:", "v1:"))
                                                    else r["new"])
                c.execute("UPDATE instances SET page=?, col=?, idx=?, bbox=NULL, updated_at=? WHERE instance_id=?",
                          (str(pg), col, slot, now, r["new"]))
            else:
                c.execute("UPDATE instances SET bbox=NULL, updated_at=? WHERE instance_id=?", (now, r["new"]))
            ev = c.execute("SELECT evidence FROM admissions WHERE instance_id=?", (r["new"],)).fetchone()
            if ev is not None:
                try:
                    evd = json.loads(ev[0]) if ev[0] else {}
                except ValueError:
                    evd = {}
                evd = {**(evd if isinstance(evd, dict) else {"_raw": evd}),
                       "rekeyed_from": r["old"], "rekey": f"{note}:{cm.source}:{r['action']}"}
                c.execute("UPDATE admissions SET evidence=? WHERE instance_id=?",
                          (json.dumps(evd, ensure_ascii=False), r["new"]))
            # 库指纹与匹配器常驻缓存靠 exemplars.added_at（`steps/glyph_match.py` 模块头）
            c.execute("UPDATE exemplars SET added_at=? WHERE instance_id=?", (now, r["new"]))
        c.commit()
        return {"summary": summary, "rows": rows}
    finally:
        c.close()


def _summarize(rows: list[dict]) -> dict:
    s = {"instances": len(rows), "rekey": 0, "rekey_id_changed": 0, "park": 0, "park_by_reason": {},
         "human": 0, "human_parked": 0}
    for r in rows:
        human = (r.get("prov") or "") == "human"
        s["human"] += human
        if r["action"] == "rekey":
            s["rekey"] += 1
            s["rekey_id_changed"] += r["old"] != r["new"]
        else:
            s["park"] += 1
            why = r["why"].split(":", 1)[0]
            s["park_by_reason"][why] = s["park_by_reason"].get(why, 0) + 1
            s["human_parked"] += human
    return s


def write_glyph_table(rows: list[dict], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("old_id\tnew_id\taction\tchar\tprovenance\tiou\twhy\tbbox_old\n")
        for r in rows:
            fh.write("\t".join(str(x if x is not None else "") for x in (
                r["old"], r["new"], r["action"], r["char"], r.get("prov"), r.get("iou"), r["why"],
                r.get("bbox_old"))) + "\n")


def verify_glyph_db(db_path: str | Path, cm: CellMap, events: list[dict] | None = None) -> dict:
    """验收：①本册 `_human_shapes` 的键（`v2:` 人裁）全在新格集合里；②本册不再有旧坐标 id
    （v2／裸 id 都应落在新格集合，v1 应已停放）；③给了迁移事件：事件最后一票的字形 = 库里人裁字形。"""
    from ..clustering.glyph_fp import HUMAN_SQL
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        human = {iid[3:]: ch for iid, ch in c.execute(HUMAN_SQL) if iid[3:].startswith(cm.book + ":")}
        stray = []
        for (iid,) in c.execute("SELECT instance_id FROM instances"):
            sp = _split_instance(iid, cm.book)
            if sp is not None and (sp[0] == "v1" or sp[1] not in cm.new_cells):
                stray.append(iid)
    finally:
        c.close()
    out = {"human_keys": len(human), "human_not_in_new": sorted(k for k in human if k not in cm.new_cells),
           "stray_ids": stray}
    if events is not None:
        last: dict[str, tuple[str, str]] = {}
        for e in events:
            t = e.get("target") or {}
            if e.get("kind") != "confirm" or t.get("book") != cm.book or not t.get("key"):
                continue
            p = e.get("payload") or {}
            if (p.get("v") or "confirm") != "confirm":
                continue
            shape = p.get("shape") or p.get("char")
            k = t["key"][3:] if t["key"].startswith("v2:") else t["key"]
            if shape and (k not in last or (e.get("ts") or "") >= last[k][0]):
                last[k] = (e.get("ts") or "", shape)
        out["events_keys"] = len(last)
        out["shape_mismatch"] = sorted((k, human[k], s) for k, (_t, s) in last.items()
                                       if k in human and human[k] != s)
        out["lib_without_event"] = len([k for k in human if k not in last])
    out["ok"] = not out["human_not_in_new"] and not out["stray_ids"] and not out.get("shape_mismatch")
    return out


# —— 文件类数据 ——

def _map_key(key: str, cm: CellMap) -> tuple[str, str | None]:
    """→ (`move`|`deleted`|`unknown`|`other`, 新键)。`other` = 不是本册的格键，原样留。键可带 `v2:` 前缀。"""
    pre = ""
    if key.startswith("v2:"):
        pre, key = "v2:", key[3:]
    pc = parse_cell(key)
    if pc is None or pc[0] != cm.book:
        return "other", None
    kind, new = cm.lookup(key)
    return kind, (pre + new if new else None)


def rekey_json(path: str | Path, cm: CellMap, out: str | Path | None = None, *, note: str = "siku-qiefen-v2") -> dict:
    """按格 id 当键的 JSON（L2 表 `{"cells": {...}}`，或顶层就是 `{格: …}`）。`删` 与表里没有的去掉。"""
    p = Path(path)
    d = json.loads(p.read_text(encoding="utf-8"))
    holder, field_ = (d, "cells") if isinstance(d.get("cells"), dict) else (None, None)
    cells = d["cells"] if holder is not None else d
    new_cells: dict = {}
    s = {"move": 0, "renumbered": 0, "deleted": 0, "unknown": 0, "other": 0}
    dropped = []
    for k, v in cells.items():
        kind, nk = _map_key(k, cm)
        if kind == "move":
            s["move"] += 1
            s["renumbered"] += nk != k
            new_cells[nk] = v
        elif kind == "other":
            s["other"] += 1
            if k in new_cells:
                raise ValueError(f"{p.name}: 键 {k} 和改键后的格撞了")
            new_cells[k] = v
        else:
            s[kind] += 1
            dropped.append(k)
    if holder is not None:
        holder[field_] = new_cells
        rk = d.setdefault("rekey", [])
        rk.append({"note": note, "map": cm.source, "book": cm.book, "at": _now(), **s, "dropped": sorted(dropped)})
        payload = d
    else:
        payload = new_cells
    target = Path(out) if out else p
    indent = _sniff_indent(p)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")
    return {"file": str(target), **s, "dropped": sorted(dropped)}


def _sniff_indent(p: Path) -> int | None:
    head = p.read_text(encoding="utf-8")[:200]
    m = re.search(r"\n( *)\"", head)
    return len(m.group(1)) if m else None


def rekey_jsonl(path: str | Path, cm: CellMap, out: str | Path | None = None,
                fields: tuple[str, ...] = ("id", "key")) -> dict:
    """金标／回放集 jsonl：`fields` 里的格键改成新格，`page`／`col`／`slot` 跟着改；对不上的行挪到 `.retired.jsonl`。"""
    p = Path(path)
    kept, retired = [], []
    s = {"rows": 0, "move": 0, "renumbered": 0, "deleted": 0, "unknown": 0, "other": 0}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        s["rows"] += 1
        kinds, new, changed = set(), None, False
        for f in fields:
            if isinstance(r.get(f), str):
                kind, nk = _map_key(r[f], cm)
                kinds.add(kind)
                if kind == "move":
                    changed |= nk != r[f]
                    new = nk
                    r[f] = nk
        if "deleted" in kinds or "unknown" in kinds:
            s["deleted" if "deleted" in kinds else "unknown"] += 1
            retired.append(r)
            continue
        if "move" in kinds:
            s["move"] += 1
            _b, pg, col, slot, sub = parse_cell(new[3:] if new.startswith("v2:") else new)
            s["renumbered"] += changed
            if "page" in r:
                r["page"] = pg if isinstance(r["page"], int) else str(pg)
            if "col" in r:
                r["col"] = col if isinstance(r["col"], int) else str(col)
            if "slot" in r:
                r["slot"] = f"{slot}{sub}" if isinstance(r["slot"], str) else slot
        else:
            s["other"] += 1
        kept.append(r)
    target = Path(out) if out else p
    _write_jsonl(target, kept)
    if retired:
        _write_jsonl(target.with_name(target.stem + ".retired.jsonl"), retired)
    return {"file": str(target), **s}


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    buf = io.StringIO()
    for r in rows:
        buf.write(json.dumps(r, ensure_ascii=False) + "\n")
    path.write_text(buf.getvalue(), encoding="utf-8")


def rekey_ids_bank(path: str | Path, cm: CellMap, rev: int | str, out: str | Path | None = None) -> dict:
    """IDS 模板库出处 `source.cells`（与 books／keys／labels 平行，不能删项）：对上的改新格，对不上的写停放 id。"""
    p = Path(path)
    d = json.loads(p.read_text(encoding="utf-8"))
    cells = ((d.get("source") or {}).get("cells")) or []
    s = {"cells": len(cells), "move": 0, "renumbered": 0, "parked": 0, "other": 0}
    for i, k in enumerate(cells):
        if not isinstance(k, str):
            continue
        kind, nk = _map_key(k, cm)
        if kind == "move":
            s["move"] += 1
            s["renumbered"] += nk != k
            cells[i] = nk
        elif kind == "other":
            s["other"] += 1
        else:
            s["parked"] += 1
            cells[i] = parked_id("cell", k[3:] if k.startswith("v2:") else k, rev)
    target = Path(out) if out else p
    # 与 `groups.ids_online.write_bank` 同一写法（indent=0、sort_keys），改完 diff 只有出处那几行
    target.write_text(json.dumps(d, ensure_ascii=False, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    return {"file": str(target), **s}
