"""放行硬项（用户 2026-10-19 定，GUJI-624）：0.1.0 与 1.0.0 都查，`guji close-check` 第 2c、2d 项。

1. **□ 有去向**（2c）：导出文本里每个阙文占位（`□`／`〓`）对应的格，要么在公众人审页的待审单上，
   要么在本册的**重切清单**上。都不在的不放行。待审单 10-20 起只在中心库
   `feedback/lists/proofing/<书>/<章>.pending.json`（本地在数据目录同一相对路径，`guji db sync` 拉下来），
   不再在 book-text；`resolve_pending` 缺省就去那里找（GUJI-711），见下「待审单在哪」。
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
HOT_PAGE_COLS = 3
"""2d 里一页没交代的列 ≥ 这么多，就点名「整页处理」：重切清单写一个页号即覆盖全页。
殿本 10 册离线量（2026-10-19，`doc/research/切分现状梳理与新方向-2026-10-19.md` §六·5）：Step3 结构与
逐列本对不上的列扎堆在少数页——卷端页、Step1 整页列错位、拆过的页、印章页——这类页逐列交代是白费，
该整页送审或重切；只错一两列的页多是单格的事，照旧逐列交代。只提示，不改判定。"""
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


# ── 待审单在哪（GUJI-711）────────────────────────────────
#
# 10-20 起公众待审单只在中心库 `feedback/lists/proofing/<书>/<章>.pending.json`（网站 proofing-sync 从这里发布），
# 本地在数据目录 `$GUJI_DATA_HOME/<分支>/<工作区>/feedback/lists/proofing/…`（`lists_dir()` 已指过去）。
# `<书>` 是 book-text 的书 id（四庫總目 `96mid1ogzk`），`<章>` 是章号 NNN（`volNN` 册即 `0NN`）。

PROOFING = "proofing"
META_DIR = Path(__file__).resolve().parents[2] / "doc" / "formats" / "samples" / "guji_format_v0.1"
_VOL = re.compile(r"vol(\d+)")
_CHAP = re.compile(r"\d{3}")


def proofing_path(book_text_id: str, chapter: str, root: Path | None = None) -> Path:
    return (root or lists_dir()) / PROOFING / book_text_id / f"{chapter}.pending.json"


def chapter_of(book: str, chapter: str | None = None) -> str | None:
    """章号：给了就用；`volNN` 册推成 `0NN`（与 `guji export format` 同一口径）；推不出 → None。"""
    if chapter:
        return chapter
    m = _VOL.fullmatch(book or "")
    return f"{int(m.group(1)):03d}" if m else None


def book_text_id(book: str) -> str | None:
    """cv 册 → book-text 书 id：`guji export format` 用的那份 meta（`meta_<册>.json` 的 `defaults.book.id`）。"""
    p = META_DIR / f"meta_{book}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))["defaults"]["book"]["id"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def default_pending(book: str, chapter: str | None = None, root: Path | None = None) -> Path | None:
    """本册本章的中心库待审单（本地数据目录里的路径）；推不出章号 → None。

    书 id 先按 meta 取；取不到就在 `proofing/*/` 下找这一章，恰好一份才用。文件不一定在。"""
    chap = chapter_of(book, chapter)
    if not chap:
        return None
    bid = book_text_id(book)
    if bid:
        return proofing_path(bid, chap, root)
    hits = sorted(((root or lists_dir()) / PROOFING).glob(f"*/{chap}.pending.json"))
    return hits[0] if len(hits) == 1 else None


def resolve_pending(arg: str | Path | None, book: str, chapter: str | None = None,
                    root: Path | None = None) -> tuple[Path | None, str]:
    """`--pending` 的值 → (待审单路径或 None, 给人看的一句说明)。

    - 不给（`None`）或只写 `--pending`（空串）：本册本章的中心库待审单；
    - 给册（`vol04`）、章号（`004`）或 `<书>/<章>`：那一册／章的中心库待审单；
    - 给文件路径：在就用它；不在、又像 book-text 的旧路径（`NNN.pending.json`）→ 说明已迁移、指出新路径，
      新路径在就改读新路径。
    中心库待审单不在 → (None, 提示先 `guji db sync`)，2c 只认重切清单。"""
    a = "" if arg is None else str(arg).strip()
    target: Path | None
    if not a:
        target, how = default_pending(book, chapter, root), f"本册（{book}）"
    elif _VOL.fullmatch(a):
        target, how = default_pending(a, None, root), f"册 {a}"
    elif _CHAP.fullmatch(a):
        target, how = default_pending(book, a, root), f"章 {a}"
    elif re.fullmatch(r"[^/\\]+/\d{3}", a):
        bid, chap = a.split("/")
        target, how = proofing_path(bid, chap, root), a
    else:
        p = Path(a).expanduser()
        if p.is_file():
            return p, ""
        m = re.fullmatch(r"(\d{3})\.pending\.json", p.name)
        if not m:
            return None, f"--pending 给的 {a} 不在"
        # book-text 的目录是 `Book/g/z/k/<书 id>/NNN.pending.json`：书 id 先按 meta，取不到用上一级目录名
        bid = book_text_id(book) or (p.parent.name if p.parent.name not in ("", ".", "..") else None)
        new = proofing_path(bid, m.group(1), root) if bid else default_pending(book, m.group(1), root)
        moved = (f"--pending 给的 {a} 不在：待审单 10-20 起已从 book-text 迁到中心库，"
                 f"本地在 {new}（`guji db sync` 拉下来）")
        if new is not None and new.is_file():
            return new, moved + "，改读这份"
        return None, moved + "；那里也没有，只认重切清单"
    if target is None:
        return None, f"{how}推不出章号／书 id，没找中心库待审单（给 --chapter，或 --pending <书>/<章>）；只认重切清单"
    if not target.is_file():
        return None, f"中心库待审单 {target} 不在（先 guji db sync？）；只认重切清单"
    return target, f"待审单：{target}"


def load_pending_cells(path: Path) -> set[str]:
    """待审单 `NNN.pending.json`（中心库 `feedback/lists/proofing/<书>/`）→ 待审单上的格（`cell` 字段，形如 `9:7:17`、`90:1:3a`）。

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
    per_page: dict[int, int] = {}
    for x in loose:
        pg = int(x.split(":")[0])
        per_page[pg] = per_page.get(pg, 0) + 1
    hot = [{"page": pg, "cols": n} for pg, n in sorted(per_page.items()) if n >= HOT_PAGE_COLS]
    return {"columns": len(cols), "by_action": by_act, "loose": loose, "ledger_bad": bad,
            "recut_bad": recut.bad, "hot_pages": hot}

