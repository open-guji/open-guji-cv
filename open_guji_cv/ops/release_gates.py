"""放行硬项（用户 2026-10-19 定，GUJI-624）：0.1.0 与 1.0.0 都查，`guji close-check` 第 2c、2d 项。

1. **□ 有去向**（2c）：导出文本里每个阙文占位（`□`／`〓`）对应的格，要么在公众人审页的待审单上
   （book-text 的 `NNN.pending.json`，`--pending` 给），要么在本册的**重切清单**上。都不在的不放行。
2. 人审页加「切坏格」一类：网站侧的事。2c 报出的没去向的格（close-check `--json` 的 `loose`）要上人审页时，
   在 pending.json 里写 `{"cell": 格, "review": "pending", "why": ["seg_defect"], "cls": "seg_defect"}`；人裁定保持 □ 的格留在单上、写 `review: "human"`，也算有去向。
3. **整理本对不上的列有交代**（2d）：align_ref 记进 `coord_fallback` 的列（格与整理本对不上），每一列都要在
   **列交代单**上写明处理（重切／改字／说明／一致），或落在重切清单的页、列上。没交代的不放行。

两张单都在数据目录 `feedback/lists/` 下（随 `guji db sync` 进中心库），TSV，`#` 开头是注释，首行是表头：

- `<册>-重切清单.tsv`：`位置<TAB>原因`。位置写页（`89`）、页:列（`89:7`）或格（`89:7:16`、`90:1:3a`）。
- `<册>-对不上列交代.tsv`：`页<TAB>列<TAB>处理<TAB>说明`。处理是 `重切`／`改字`／`说明`／`一致` 之一；
  `说明` 和 `一致` 必须写说明（`一致` 写怎么核的）。

只读：不改产物、不写单子。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

LACUNA = ("□", "〓")
ACTIONS = ("重切", "改字", "说明", "一致")
_POS = re.compile(r"(\d+)(?::(\d+)(?::(-?\d+[ab]?))?)?")


def lists_dir() -> Path:
    from ..core.workspace import feedback_root
    return feedback_root() / "lists"


def recut_path(book: str, root: Path | None = None) -> Path:
    return (root or lists_dir()) / f"{book}-重切清单.tsv"


def ledger_path(book: str, root: Path | None = None) -> Path:
    return (root or lists_dir()) / f"{book}-对不上列交代.tsv"


def _rows(p: Path) -> list[list[str]]:
    """TSV 去注释、去空行、去表头（第一条非注释行）。文件不在 → []。"""
    if not p.is_file():
        return []
    rows = [ln.rstrip("\n").split("\t") for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
    return rows[1:]


class RecutList:
    """重切清单：页、页:列、格三种粒度；`covers_cell`／`covers_col` 判某格、某列是否已在单上。"""

    def __init__(self, rows: list[list[str]]):
        self.pages: set[int] = set()
        self.cols: set[tuple[int, int]] = set()
        self.cells: set[str] = set()
        self.bad: list[str] = []
        for r in rows:
            pos = (r[0] if r else "").strip()
            m = _POS.fullmatch(pos)
            if not m:
                self.bad.append(pos)
                continue
            pg, col, slot = m.group(1), m.group(2), m.group(3)
            if slot is not None:
                self.cells.add(f"{int(pg)}:{int(col)}:{slot}")
            elif col is not None:
                self.cols.add((int(pg), int(col)))
            else:
                self.pages.add(int(pg))

    @classmethod
    def load(cls, book: str, root: Path | None = None) -> "RecutList":
        return cls(_rows(recut_path(book, root)))

    def covers_col(self, page: int, col: int) -> bool:
        return page in self.pages or (page, col) in self.cols

    def covers_cell(self, anchor: str) -> bool:
        pg, col, *_ = anchor.split(":")
        return anchor in self.cells or self.covers_col(int(pg), int(col))


def load_ledger(book: str, root: Path | None = None) -> tuple[dict[tuple[int, int], tuple[str, str]], list[str]]:
    """列交代单 → `{(页, 列): (处理, 说明)}`，外加写坏的行（人读一句话）。"""
    out: dict[tuple[int, int], tuple[str, str]] = {}
    bad: list[str] = []
    for r in _rows(ledger_path(book, root)):
        r = [x.strip() for x in r] + [""] * 4
        pg, col, act, note = r[:4]
        if not (pg.isdigit() and col.isdigit()):
            bad.append(f"页列不是数字：{pg}\t{col}")
            continue
        if act not in ACTIONS:
            bad.append(f"{pg}:{col} 处理「{act}」不是 {'/'.join(ACTIONS)} 之一")
            continue
        if act in ("说明", "一致") and not note:
            bad.append(f"{pg}:{col} 处理是「{act}」但没写说明")
            continue
        out[(int(pg), int(col))] = (act, note)
    return out, bad


def load_pending_cells(path: Path) -> set[str]:
    """book-text 的 `NNN.pending.json` → 待审单上的格（`cell` 字段，形如 `9:7:17`、`90:1:3a`）。

    `review: "human"` 的也算：人在审页上裁过、定了保持 □ 的格留在单上（网站不再显示），就算有去向。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return {c["cell"] for c in d.get("cells", []) if c.get("cell")}


def lacuna_cells(export_dir: Path, chapter: str | None = None) -> list[dict]:
    """导出目录里每个阙文占位 → `{"o": 偏移, "a": 格锚点或 None, "c": 占位符}`，按偏移排。

    锚点取自 pages.json 的格；找不到格的（导出器补的占位）`a=None`，也算没去向。"""
    from ..formats.guji_format import _plain_chars
    ld = sorted(Path(export_dir).glob("*.lines.md"))
    if chapter:
        ld = [p for p in ld if p.name.startswith(chapter + ".")]
    if len(ld) != 1:
        raise RuntimeError(f"{export_dir} 下找到 {len(ld)} 个 lines.md，应为 1 个")
    chars = _plain_chars(ld[0].read_text(encoding="utf-8"))
    pj = ld[0].with_name(ld[0].name[: -len(".lines.md")] + ".pages.json")
    by_o: dict[int, str] = {}
    if pj.exists():
        for p in json.loads(pj.read_text(encoding="utf-8"))["pages"]:
            for c in p["cells"]:
                if isinstance(c.get("o"), int) and c.get("a"):
                    by_o[c["o"]] = c["a"]
    return [{"o": i, "a": by_o.get(i), "c": ch} for i, ch in enumerate(chars) if ch in LACUNA]


def check_lacuna(book: str, export_dir: Path, chapter: str | None, pending: Path | None,
                 lists_root: Path | None = None) -> dict:
    """第 2c 项的数：每个 □ 在待审单或重切清单上。"""
    lac = lacuna_cells(export_dir, chapter)
    on_page = load_pending_cells(pending) if pending else set()
    recut = RecutList.load(book, lists_root)
    in_pending, in_recut, loose = [], [], []
    for x in lac:
        a = x["a"]
        if a and a in on_page:
            in_pending.append(a)
        elif a and recut.covers_cell(a):
            in_recut.append(a)
        else:
            loose.append(a or f"偏移{x['o']}")
    return {"lacuna": len(lac), "pending": in_pending, "recut": in_recut, "loose": loose,
            "recut_bad": recut.bad, "pending_file": str(pending) if pending else None}


def fallback_columns(book: str, pages, store) -> list[dict]:
    """align_ref 产物里 `coord_fallback` 的列 → `[{"page", "col", "why"}]`。没产物的页跳过。"""
    from ..core.spec import page_key
    out = []
    for pg in pages:
        ar = store.read(book, "align_ref", page_key(pg), "align_ref")
        if ar is None:
            continue
        for col, why in sorted(ar.coord_fallback.items(), key=lambda kv: int(kv[0])):
            out.append({"page": pg, "col": int(col), "why": why})
    return out


def check_fallback(book: str, pages, store, lists_root: Path | None = None) -> dict:
    """第 2d 项的数：每个 coord_fallback 列在列交代单或重切清单上。"""
    cols = fallback_columns(book, pages, store)
    ledger, bad = load_ledger(book, lists_root)
    recut = RecutList.load(book, lists_root)
    by_act: dict[str, int] = {}
    loose = []
    for c in cols:
        k = (c["page"], c["col"])
        if k in ledger:
            by_act[ledger[k][0]] = by_act.get(ledger[k][0], 0) + 1
        elif recut.covers_col(*k):
            by_act["重切"] = by_act.get("重切", 0) + 1
        else:
            loose.append(f"{c['page']}:{c['col']}")
    return {"columns": len(cols), "by_action": by_act, "loose": loose, "ledger_bad": bad,
            "recut_bad": recut.bad}

