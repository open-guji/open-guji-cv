# -*- coding: utf-8 -*-
"""新候选刻例待纳入：清单格式与裁决回读（2026-09-28，overview#176，来源 H #62）。

## 为什么要有
字形库体检（`/api/glyphlib/audit`）只收**已在库里**的实例（要 `exemplars` 里有这个
instance_id）。H 道扫出的「还没进库、但有双证的候选格」没有地方给人裁。本模块定清单
格式，控制台「字形库 → 待纳入」子视图读它出卡。

## 清单文件
工作区 `feedback/candidates/<清单 id>.jsonl`，一行一格::

    {"cell_id": "vol03:19:6:18", "char": "仕",
     "evidence": {"source": "H#62", "align_char": "仕", "ctx_top": "仕", "margin": 1.0},
     "ref_instances": ["v2:vol01:55:3:7"]}          # 可选：点名的对照刻例

`cell_id` 与定字裁决同口径（`书:页:列:格[ab]`，格从 1 数，v2 口径）。
以 `{"_meta": {...}}` 开头的行是清单说明（标题、来源），不算格。`#` 开头的行跳过。

## 裁决
**不在这里写库，也不另开写入口**：前端照常 `POST /api/events`，
`kind="admit_candidate"`、`unit="cell"`、`id=cell_id`、批次 `candidates-<清单 id>`，
payload `{v: admit|reject|unclear, char, shape, list, evidence}`。

路由表**故意不给 `admit_candidate` 配消费者**：事件由控制台写，进库由 H 道的重放
完成（人裁状态单写者，见 overview 并行分工）——`admit` 的事件带了 `shape`，H 那边
可以按 `confirm` 同样的口径（`glyphdb_admit`）送进库。同一格裁多次按最新一条算。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

KIND = "admit_candidate"
STEP = "glyph_candidate"
VERDICTS = ("admit", "reject", "unclear")
BATCH_PREFIX = "candidates-"

_LIST_ID = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$")
_CELL = re.compile(r"^(?P<book>[A-Za-z][A-Za-z0-9_-]*):(?P<page>\d+):(?P<col>\d+):(?P<slot>-?\d+)(?P<sub>[ab]?)$")


def candidates_dir() -> Path:
    from ..core.workspace import feedback_root
    return Path(feedback_root()) / "candidates"


def batch_of(list_id: str) -> str:
    return BATCH_PREFIX + list_id


def parse_cell(cell_id: str) -> dict | None:
    """`vol03:19:6:18` → {book, page, col, slot, sub, patch_key}；认不出返回 None。"""
    m = _CELL.match(cell_id or "")
    if not m:
        return None
    page, col, slot, sub = int(m["page"]), int(m["col"]), int(m["slot"]), m["sub"]
    return {"book": m["book"], "page": page, "col": col, "slot": slot, "sub": sub,
            "patch_key": f"p{page:04d}c{col:02d}s{slot}{sub}"}


def list_path(list_id: str, root: Path | None = None) -> Path:
    if not _LIST_ID.match(list_id or ""):
        raise ValueError(f"清单 id 只能是字母数字与 _ . -（不以 . 开头）：{list_id!r}")
    return (root or candidates_dir()) / f"{list_id}.jsonl"


def load_list(path: Path) -> tuple[dict, list[dict], list[str]]:
    """→ (meta, rows, problems)。坏行不抛，记进 problems、跳过（一行写错不该让整份清单打不开）。
    同一 cell_id 重复出现只留第一行。"""
    meta: dict = {}
    rows: list[dict] = []
    problems: list[str] = []
    seen: set[str] = set()
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            d = json.loads(s)
        except ValueError as e:
            problems.append(f"第 {n} 行不是 JSON：{e}")
            continue
        if not isinstance(d, dict):
            problems.append(f"第 {n} 行不是对象")
            continue
        if "_meta" in d:
            meta.update(d["_meta"] or {})
            continue
        cid, ch = d.get("cell_id"), d.get("char")
        if not cid or parse_cell(cid) is None:
            problems.append(f"第 {n} 行 cell_id 认不出：{cid!r}")
            continue
        if not isinstance(ch, str) or len(ch) != 1:
            problems.append(f"第 {n} 行 char 不是单字：{ch!r}")
            continue
        if cid in seen:
            problems.append(f"第 {n} 行 {cid} 重复，只留第一行")
            continue
        seen.add(cid)
        ev = d.get("evidence")
        rows.append({"cell_id": cid, "char": ch,
                     "evidence": ev if isinstance(ev, dict) else ({"note": ev} if ev else {}),
                     "ref_instances": [str(x) for x in (d.get("ref_instances") or [])]})
    return meta, rows, problems


def list_ids(root: Path | None = None) -> list[str]:
    d = root or candidates_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.jsonl") if _LIST_ID.match(p.stem))


def decisions(log, list_id: str) -> dict[str, dict]:
    """这份清单已落的裁决：{cell_id: {v, char, ts, reviewer}}，同格取最新一条。"""
    out: dict[str, dict] = {}
    for e in log.read(batch_of(list_id)):          # 已按 seq 排好；ts 只到秒，不拿它排
        if e.kind != KIND:
            continue
        v = e.payload.get("v")
        if v not in VERDICTS:
            continue
        out[e.target.key] = {"v": v, "char": e.payload.get("char"), "ts": e.ts,
                             "reviewer": e.reviewer}
    return out


def tally(rows: list[dict], dec: dict[str, dict]) -> dict:
    t = {v: 0 for v in VERDICTS}
    for r in rows:
        d = dec.get(r["cell_id"])
        if d:
            t[d["v"]] += 1
    t["todo"] = len(rows) - sum(t[v] for v in VERDICTS)
    return t
