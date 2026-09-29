# -*- coding: utf-8 -*-
"""近似字（overview#276）在文本输出里的两种出法。

人裁勾了「无匹配（近似字）」：Unicode 里没有真正对应的字，所定的 `shape` 只是字形最像、意思最近的
那个字。事件 payload 带 `approx: true`，可选 `ids`（实际结构）、`note`。

出文本时（用户在 overview#277 还没定，先按保守做法）：

- **`sidecar`（缺省）**：正文照填那个近似字，一个记号都不加；另出一张侧表
  `页:列:格 → 字 / ids / note`。正文与不勾近似时逐字相同，下游解析器不受影响。
- **`inline_ids`（预留）**：正文在近似字后面用后缀属性括注，`字{ids=⿰…}`（没填 IDS 的不括注）。
  与原刻残的 `□{guess=X}` 同一套 guji-markdown 属性语法，同样的「属性语法尚未合并 guji-markdown
  main」注意事项（见 `guji_markdown` 模块头第 4 条）。
- `off`：两样都不出。

标记从**事件**读，不读字形库：勾了「字形不入库」的格不进库，近似标记也就不在 `approx_labels` 里，
但字是定了的、文本照样出，这一格的近似说明不能丢。同一格按时间后到覆盖，人后来改口（再确认一次
没勾）就撤掉——与 `feedback/lookup.human_chars` 同一套口径（不过绑定表，按编号认格）。
"""
from __future__ import annotations

APPROX_MODES = ("sidecar", "inline_ids", "off")
DEFAULT_APPROX_MODE = "sidecar"


def approx_marks(book: str, log=None) -> dict[str, dict]:
    """`{字位 id: {"shape", "ids", "note"}}`：这本书现在仍标着近似的字位（后到覆盖）。"""
    from ..feedback.events import EventLog
    out: dict[str, dict] = {}
    pre = f"{book}:"
    try:
        evs = sorted((log or EventLog()).iter_all(), key=lambda e: (e.ts, e.batch, e.seq))
    except FileNotFoundError:
        return out
    for e in evs:
        if e.kind != "confirm" or e.target.unit != "cell" or not e.target.key.startswith(pre):
            continue
        p = e.payload or {}
        if p.get("v") not in ("confirm", "seg_defect") or not p.get("shape"):
            continue
        if p.get("approx"):
            out[e.target.key] = {"shape": str(p["shape"]), "ids": (p.get("ids") or "").strip(),
                                 "note": (p.get("note") or "").strip()}
        elif e.actor == "user":
            out.pop(e.target.key, None)          # 人再定一次没勾近似 = 改口
    return out


def _pos(key: str) -> str:
    """`book:页:列:格[a|b]` → `页:列:格[a|b]`。"""
    return key.split(":", 1)[1] if ":" in key else key


def sidecar_rows(marks: dict[str, dict], pages: list[int] | None = None) -> list[dict]:
    """侧表行（按页、列、格排序）；`pages` 给了就只留这些页的。"""
    want = set(pages) if pages is not None else None
    rows = []
    for key, m in marks.items():
        parts = key.split(":")
        try:
            pg, col = int(parts[1]), int(parts[2])
            slot_s = parts[3]
            sub = slot_s[-1] if slot_s and slot_s[-1] in "ab" else ""
            slot = int(slot_s[:-1] if sub else slot_s)
        except (IndexError, ValueError):
            continue
        if want is not None and pg not in want:
            continue
        rows.append({"pos": _pos(key), "page": pg, "col": col, "slot": slot, "sub": sub,
                     "shape": m["shape"], "ids": m.get("ids") or "", "note": m.get("note") or ""})
    rows.sort(key=lambda r: (r["page"], r["col"], r["slot"], r["sub"]))
    return rows


def sidecar_tsv(rows: list[dict]) -> str:
    """侧表的 TSV 文本（`页:列:格	字	ids	note`，带表头）。"""
    def clean(s: str) -> str:
        return s.replace("\t", " ").replace("\n", " ")
    lines = ["pos\tshape\tids\tnote"]
    lines += [f"{r['pos']}\t{r['shape']}\t{clean(r['ids'])}\t{clean(r['note'])}" for r in rows]
    return "\n".join(lines) + "\n"


def inline_ids_map(marks: dict[str, dict]) -> dict[str, tuple[str, str]]:
    """`inline_ids` 模式给 `render_page` 用的 `{字位 id: (字, ids)}`（没填 IDS 的不收）。"""
    return {k: (m["shape"], m["ids"]) for k, m in marks.items() if m.get("ids")}
