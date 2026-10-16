# -*- coding: utf-8 -*-
"""格级审阅（GUJI-364b，2026-10）：人对清单里每格看单字特写，裁「是哪个字」，导出 TSV。

清单沿用 `feedback/candidates.py` 的格式（`feedback/candidates/<清单 id>.jsonl`），本模块只多认两个可选字段：

    {"cell_id": "vol01:24:3:5", "char": "仕", "cands": ["仕", "任"], "reason": "形近"}

- `cands`：候选字（字符串数组），面板上做按钮；缺省为空。
- `reason`：为什么进清单，只给人看。

## 裁决（四档，GUJI-364 拍板）
`verdict` ∈ `pick`（选候选字，`picked` 必填且须在 `cands` 里）／`none`（格内无可识别字）／
`unsure`（看不出）／`other`（`other_char` 填单个码位字符；多字写 `note`）。

事件：`kind="cell_review"`，批次 `cellreview-<清单 id>`，`target.key` = `cell_id`，只追加。
**路由表不配消费者**：不写定字事件，不进 glyph.db，不让任何产物过期。同一格多次裁决取最新一条。

## 导出
`tsv(...)`：一行一格、按 `cell_id` 排序、取每格最新一条；没裁的格 verdict 等列留空，行数 = 清单行数。
`t` 列取服务端时间（事件的 `ts`），不取前端的 `client_ts`。
"""
from __future__ import annotations

from ..feedback import candidates as cand

KIND = "cell_review"
STEP = "cell_review"
VERDICTS = ("pick", "none", "unsure", "other")
BATCH_PREFIX = "cellreview-"
NOTE_MAX = 500

TSV_COLUMNS = ("cell_id", "book", "page", "col", "slot", "sub", "char", "verdict",
               "picked", "other_char", "note", "reviewer", "t")


def batch_of(list_id: str) -> str:
    return BATCH_PREFIX + list_id


def load(path) -> tuple[dict, list[dict], list[str]]:
    """清单 → (meta, rows, problems)；rows 带 `cands`、`reason`（candidates.load_list 只留了基础字段）。"""
    meta, rows, problems = cand.load_list(path)
    raw = _raw_extras(path)
    for r in rows:
        ex = raw.get(r["cell_id"], {})
        r["cands"] = ex.get("cands", [])
        r["reason"] = ex.get("reason")
    return meta, rows, problems


def _raw_extras(path) -> dict[str, dict]:
    """只为取 `cands` / `reason` 再读一遍清单行（同 cell_id 只留第一行，与 load_list 一致）。"""
    import json
    from pathlib import Path
    out: dict[str, dict] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            d = json.loads(s)
        except ValueError:
            continue
        if not isinstance(d, dict) or "_meta" in d or not d.get("cell_id"):
            continue
        out.setdefault(d["cell_id"], {
            "cands": [c for c in (d.get("cands") or []) if isinstance(c, str) and len(c) == 1],
            "reason": d.get("reason"),
        })
    return out


def check_payload(payload: dict, cands: list[str]) -> str | None:
    """校验一条裁决的 payload；合法返回 None，否则返回中文原因（由路由转成 400）。"""
    v = payload.get("verdict")
    if v not in VERDICTS:
        return f"verdict 必须是 {'/'.join(VERDICTS)} 之一：{v!r}"
    if v == "pick":
        picked = payload.get("picked")
        if not isinstance(picked, str) or len(picked) != 1 or picked.isspace():
            return "pick 的 picked 只收单个码位字符"
        if cands and picked not in cands:
            return f"picked {picked!r} 不在这格的候选字里：{cands}"
    if v == "other":
        oc = payload.get("other_char")
        if not isinstance(oc, str) or len(oc) != 1 or oc.isspace():
            return "other 的 other_char 只收单个码位字符；多字请写进备注"
    note = payload.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > NOTE_MAX):
        return f"note 须为字符串，且不超过 {NOTE_MAX} 字"
    return None


def latest(log, list_id: str) -> dict[str, dict]:
    """这份清单已落的裁决：{cell_id: {verdict, picked, other_char, note, reviewer, ts, client_ts}}，同格取最新一条。"""
    out: dict[str, dict] = {}
    for e in log.read(batch_of(list_id)):          # 已按 seq 排好
        if e.kind != KIND:
            continue
        p = e.payload
        out[e.target.key] = {
            "verdict": p.get("verdict"), "picked": p.get("picked"),
            "other_char": p.get("other_char"), "note": p.get("note"),
            "reviewer": e.reviewer, "ts": e.ts, "client_ts": p.get("client_ts"),
        }
    return out


def _clean(v) -> str:
    """TSV 单元格：制表符与换行压成空格，None 写空。"""
    if v is None:
        return ""
    return str(v).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def tsv_rows(rows: list[dict], dec: dict[str, dict]) -> list[list[str]]:
    out = []
    for r in sorted(rows, key=lambda r: r["cell_id"]):
        pc = cand.parse_cell(r["cell_id"]) or {}
        d = dec.get(r["cell_id"], {})
        out.append([
            _clean(r["cell_id"]), _clean(pc.get("book")), _clean(pc.get("page")),
            _clean(pc.get("col")), _clean(pc.get("slot")), _clean(pc.get("sub")),
            _clean(r["char"]), _clean(d.get("verdict")), _clean(d.get("picked")),
            _clean(d.get("other_char")), _clean(d.get("note")), _clean(d.get("reviewer")),
            _clean(d.get("ts")),
        ])
    return out


def tsv(rows: list[dict], dec: dict[str, dict]) -> str:
    """UTF-8 带 BOM（Excel 直接打开），行尾 \\n。"""
    lines = ["\t".join(TSV_COLUMNS)] + ["\t".join(r) for r in tsv_rows(rows, dec)]
    return "﻿" + "\n".join(lines) + "\n"
