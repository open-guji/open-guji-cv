# -*- coding: utf-8 -*-
"""book-text 新形态：`NNN.char.json`（字）＋ `NNN.cord.json`（框）＋ `NNN.norm.json`（按格位的例外）。F4 道，overview#419。

规范：guji-format `spec/01-guji-cord.md`、`spec/02-guji-char.md`，schema 在仓根 `formats/guji_{char,cord}_v0.1.schema.json`
（从 guji-format 7ad86dc 照抄，测试只读本仓）。book-text 一侧见 `docs/ORIGINAL.md`。

入口只吃 F3 的 `guji-pages/0.1`（`NNN.pages.json`，格里带字）——**不读产物**：

- `from_pages_json(pj, zi=…, norm=…)` → `{NNN.char.json, NNN.cord.json, NNN.norm.json}`；
- `char_to_lines_md(char)` → 分行稿，记法与 `guji_page.to_guji_markdown`（Step9 9.1）逐字相同；
- `check(char, cord)` 核两边格位、页号、列号；`validate(obj, "char"|"cord")` 过 schema。

导出器（`scripts/export_guji_format.py --format char-cord`）先照旧出 pages.json，再走这里；纯转换入口是
`scripts/convert_pages_to_char_cord.py`，旧 pages.json 直接转。

**格位口径**（`keys=`）：
- `"cv"`（缺省，照 spec 02 §二）：= pages.json 的锚点 = CV 格 id 去册前缀。列是 Step3 物理列号，**空列也占号**；
  格是 Step3 slot，抬头为负、没有 0，行首排除格、列中留白格也占号。
- `"lines"`（兼容）：照 book-text `original_version.lines_slots` 数分行稿：列 = 本页第几个非空行，格从 `.`/`^`
  起数，排除格、留白、空列都不占号。wip/siku 上 T68 转出的 char 与现有 punct/entity 锚点用的是这一套。
  两套在四庫 vol02 差 841 格、vol03 差 4,000 格（主要是行首排除格与空列），选哪套待拍板（见 overview#419）。

**字段对应**（pages.json → char）：
- `c` = 格里的字；未收字取 zi.json 的近似字（没有近似字是「〓」），`zi` = IDS 或描述；
- `lacuna` = 字框 `lacuna: "unreadable"` 或页上 `lacuna_extra`；`c` 照规范写「□」。`lacuna: "defect"`（字在、
  图块切坏）不算阙文，char 里不标；
- `guess` = 字框 `guess` 且字是「□」（分行稿 `□{guess=X}`），`c` 写推测的字 X；
- `lane` 只在推不出来时写：`solo` 总写；夹注只在格位后缀与左右不符时写（lines 口径下单边夹注一律记 `a`）；
- 列：`raised`、`lead_blank` 非 0 才写；`kind` 版心记 `banxin`、没有字的列记 `blank`，正文不写。

cord 去掉字和 CV 内部字段（`by`、`cv_id`、`o`、`runs`、`lacuna`…）；`box` 为空的版框、列、格、记号不写（cord
允许 char 里的格暂时没有框）。norm 每条 `{a, c, t, by?, why?}`，按格位 key、不带字偏移。
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

CHAR_SCHEMA_URL = "https://open-guji.org/schema/char/v0.1.json"
CORD_SCHEMA_URL = "https://open-guji.org/schema/cord/v0.1.json"
NORM_SCHEMA = "guji-norm/0.2"          # guji-format 还没有 norm 的 schema；0.1 是 F3 带字偏移 `o` 的那版
LACUNA_CHAR = "□"
ZI_NO_NEAR = "〓"
_FORMATS = Path(__file__).resolve().parents[2] / "formats"
SCHEMA_PATHS = {"char": _FORMATS / "guji_char_v0.1.schema.json",
                "cord": _FORMATS / "guji_cord_v0.1.schema.json"}
KEYS = ("cv", "lines")

_REGION_KINDS = ("body", "banxin", "margin")
_MARK_KINDS = ("blank", "seal", "excluded")
_JZ_SUFFIX = {"jz_r": "a", "jz_l": "b"}
_KEY_RE = re.compile(r"^(\d+):(\d+):(-?[1-9]\d*)([ab]?)$")


def parse_key(a: str) -> tuple[int, int, int, str]:
    m = _KEY_RE.match(a or "")
    if not m:
        raise ValueError(f"格位 key 不对：{a!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)


def _col_no(col: Any) -> int | None:
    """pages.json 里列号有 `n`（整数）和 `col: "c3"`（列 id）两种写法。"""
    if col is None:
        return None
    if isinstance(col, int):
        return col
    m = re.fullmatch(r"c?(\d+)", str(col))
    return int(m.group(1)) if m else None


def _lane_of(cell: dict) -> str:
    if cell.get("lane"):
        return cell["lane"]
    suf = cell["a"][-1]
    return {"a": "jz_r", "b": "jz_l"}.get(suf, "main")


# ───────────────────────── 分行稿 ─────────────────────────

def _tok(cell: dict, *, in_solo: bool = False) -> str:
    if cell.get("lacuna"):
        return LACUNA_CHAR if in_solo else "[[]]"   # Step9 在 :jz[…] 里把阙文写成「□」（guji_page_v0.2 §10.1 已知例外）
    if cell.get("zi") is not None:
        return f":zi[{cell['zi']}]"
    if cell.get("guess"):
        return f"□{{guess={cell['c']}}}"
    return cell["c"]


def _runs(cells: list[dict]) -> list[tuple[str, list[dict]]]:
    out: list[tuple[str, list[dict]]] = []
    for c in cells:
        ln = _lane_of(c)
        if out and out[-1][0] == ln:
            out[-1][1].append(c)
        else:
            out.append((ln, [c]))
    return out


def column_line(col: dict) -> str | None:
    """一列 → 分行稿的一行；没有字的列返回 None（分行稿不出空行）。"""
    if not col.get("cells"):
        return None
    out = ["^" * int(col.get("raised") or 0) + "." * int(col.get("lead_blank") or 0)]
    runs = _runs(col["cells"])
    k = 0
    while k < len(runs):
        ln, cs = runs[k]
        if ln in ("jz_r", "jz_l"):
            right = "".join(map(_tok, cs)) if ln == "jz_r" else ""
            left = "".join(map(_tok, cs)) if ln == "jz_l" else ""
            if ln == "jz_r" and k + 1 < len(runs) and runs[k + 1][0] == "jz_l":
                left = "".join(map(_tok, runs[k + 1][1]))
                k += 1
            out.append(f"<{right}|{left}>" if right and left else f"<{right}{left}>")
        elif ln == "solo":
            out.append(":jz[" + "".join(_tok(c, in_solo=True) for c in cs) + "]{type=单行}")
        else:
            out.append("".join(map(_tok, cs)))
        k += 1
    return "".join(out)


def page_lines(page: dict) -> list[str]:
    lines = [f"<!-- p{page['page']} -->"]
    lines += [ln for ln in (column_line(c) for c in page["columns"]) if ln is not None]
    return lines


def char_to_lines_md(char: dict) -> str:
    """char → 一列一行的分行稿（与 F3 导出的 `NNN.lines.md` 同记法：每页先 `<!-- pN -->`，末尾一个换行）。"""
    return "\n".join("\n".join(page_lines(p)) for p in char["pages"]) + "\n"


# ── 分行稿 → 格位（book-text `original_version.lines_slots` 的口径；`:zi[…]` 算一格）──

_PAGE_RE = re.compile(r"^<!--\s*p(\d+)\s*-->$")
_PREFIX = re.compile(r"^(\^*)(\.*)")
_UNIT = re.compile(
    r"<(?P<jz>[^<>]*)>"
    r"|:jz\[(?P<dj>[^\]]*)\](?:\{[^}]*\})?"
    r"|(?P<zi>:zi\[[^\]]*\](?:\{[^}]*\})?)"
    r"|(?P<gap>\[\[[^\]]*\]\])"
    r"|(?P<box>□(?:\{[^}]*\})?)"
    r"|(?P<ch>.)", re.S)
_INNER = re.compile(r"(?P<zi>:zi\[[^\]]*\](?:\{[^}]*\})?)|(?P<gap>\[\[[^\]]*\]\])|(?P<box>□(?:\{[^}]*\})?)|(?P<ch>.)",
                    re.S)


def _inner_n(s: str) -> int:
    return sum(1 for m in _INNER.finditer(s) if m.group("ch") is None or not m.group("ch").isspace())


def _next(g: int) -> int:
    return 1 if g == -1 else g + 1


def lines_slots(md: str) -> list[str]:
    """分行稿 → 逐字格位 key（字流顺序）。与 book-text `lines_slots` 同口径，只多认 `:zi[…]` 为一格。"""
    keys: list[str] = []
    page, col = 0, 0
    for raw in md.splitlines():
        line = raw.strip()
        pm = _PAGE_RE.match(line)
        if pm:
            page, col = int(pm.group(1)), 0
            continue
        if not line:
            continue
        col += 1
        mp = _PREFIX.match(line)
        raised, dots = len(mp.group(1)), len(mp.group(2))
        g = (dots + 1) if dots else (-raised if raised else 1)
        for u in _UNIT.finditer(line[mp.end():]):
            if u.group("jz") is not None:
                first, _, second = u.group("jz").partition("|")
                na, nb = _inner_n(first), _inner_n(second)
                ga = gb = g
                for _ in range(na):
                    keys.append(f"{page}:{col}:{ga}a")
                    ga = _next(ga)
                for _ in range(nb):
                    keys.append(f"{page}:{col}:{gb}b")
                    gb = _next(gb)
                for _ in range(max(na, nb)):
                    g = _next(g)
            elif u.group("dj") is not None:
                for _ in range(_inner_n(u.group("dj"))):
                    keys.append(f"{page}:{col}:{g}")
                    g = _next(g)
            elif u.group("ch") is not None and u.group("ch").isspace():
                continue
            else:
                keys.append(f"{page}:{col}:{g}")
                g = _next(g)
    return keys


# ───────────────────────── pages.json → char / cord / norm ─────────────────────────

def _cells_by_col(pjp: dict) -> list[tuple[dict, list[dict]]]:
    """页上每列配上它的格（按列条带 runs 的字偏移归列，读序 = 偏移序）。"""
    owner: dict[int, int] = {}
    for ci, col in enumerate(pjp.get("columns", [])):
        for r in col.get("runs", []):
            for o in range(*r["o"]):
                owner.setdefault(o, ci)
    per = [[] for _ in pjp.get("columns", [])]
    for c in sorted(pjp.get("cells", []), key=lambda c: c["o"] if isinstance(c["o"], int) else c["o"][0]):
        o = c["o"] if isinstance(c["o"], int) else c["o"][0]
        ci = owner.get(o)
        if ci is None:
            raise ValueError(f"{pjp.get('page_id')} 格 {c.get('a')}：偏移 {o} 不在任何列条带里")
        per[ci].append(c)
    return list(zip(pjp.get("columns", []), per))


def _char_cell(c: dict, lane: str, *, lac_extra: set[int], zi_by_o: dict[int, dict]) -> dict:
    o = c["o"] if isinstance(c["o"], int) else c["o"][0]
    if not c.get("a"):
        raise ValueError(f"字偏移 {o}「{c.get('c')}」没有锚点，排不出格位 key")
    out: dict[str, Any] = {"a": c["a"], "c": c["c"]}
    z = zi_by_o.get(o)
    if z is not None:
        out["c"] = z.get("near") or ZI_NO_NEAR
        out["zi"] = z.get("ids") if z.get("ids") is not None else z.get("desc")
    _set_lane(out, lane)
    if c.get("lacuna") == "unreadable" or o in lac_extra:
        out["c"], out["lacuna"] = LACUNA_CHAR, True
    elif c.get("guess") and c["c"] == "□" and z is None:
        out["c"], out["guess"] = c["guess"], True
    return out


def _set_lane(cell: dict, lane: str) -> None:
    """`lane` 只在推不出来时写：solo 总写，夹注与 key 后缀不符才写，main 不写。"""
    cell.pop("lane", None)
    if lane == "solo" or (lane in _JZ_SUFFIX and not cell["a"].endswith(_JZ_SUFFIX[lane])):
        cell["lane"] = lane


def _box_ok(b) -> bool:
    return isinstance(b, list) and len(b) == 4 and all(isinstance(x, (int, float)) for x in b)


def from_pages_json(pj: dict, *, zi: dict | None = None, norm: dict | None = None, version: str = "0.1.0",
                    keys: str = "cv", chapter: str | None = None) -> tuple[dict[str, dict], dict]:
    """`guji-pages/0.1` → (`{NNN.char.json, NNN.cord.json, NNN.norm.json}`, 报告)。

    `zi`/`norm` 是 F3 同章的 `zi.json`（`guji-zi/0.1`）/`norm.json`（`guji-norm/0.1`），没有就当空。
    报告 `{pages, cells, boxed, dropped: {regions, columns, cells, marks}, rekeyed}`。
    pages.json 的格没盖满 `n_chars`（有字没框，字只在 lines.md 里）就报错——纯转换补不出那些字。
    """
    if keys not in KEYS:
        raise ValueError(f"keys 只能是 {KEYS}")
    chapter = chapter or pj.get("chapter") or "001"
    book_id = (pj.get("book") or {}).get("id") if isinstance(pj.get("book"), dict) else pj.get("book")
    vol = pj.get("volume")
    volume = vol.get("index") if isinstance(vol, dict) else vol
    zi_by_o = {z["o"]: z for z in (zi or {}).get("items", []) if z.get("o") is not None}
    n_cov = sum(1 if isinstance(c["o"], int) else c["o"][1] - c["o"][0] for p in pj["pages"] for c in p["cells"])
    if "n_chars" in pj and n_cov != pj["n_chars"]:
        raise ValueError(f"pages.json 的格只盖住 {n_cov} 字元，n_chars 是 {pj['n_chars']}——有字没框，要用 lines.md 补，纯转换做不了")

    allmap: dict[str, str] = {}                               # CV 锚点 → 输出 key（lines 口径下 norm 用）
    rep = {"pages": 0, "cells": 0, "boxed": 0, "rekeyed": 0,
           "dropped": {"regions": 0, "columns": 0, "cells": 0, "marks": 0}}
    char_pages, cord_pages = [], []
    for pjp in pj["pages"]:
        pn = pjp["page"]["index"] if isinstance(pjp.get("page"), dict) else pjp["page"]
        lac_extra = set(pjp.get("lacuna_extra", []))
        ccols, cv_cells, lanes = [], [], []                   # cv_cells、lanes 与 char 格一一对应，读序
        for col, cells in _cells_by_col(pjp):
            cc: dict[str, Any] = {"col": _col_no(col.get("n", col.get("id")))}
            if col.get("raised"):
                cc["raised"] = int(col["raised"])
            if col.get("lead_blank"):
                cc["lead_blank"] = int(col["lead_blank"])
            if not cells:
                cc["kind"] = "blank"
            elif col.get("kind") == "banxin":
                cc["kind"] = "banxin"
            lane_of_o = {o: r["lane"] for r in col.get("runs", []) for o in range(*r["o"])}
            cc["cells"] = []
            for c in cells:
                o = c["o"] if isinstance(c["o"], int) else c["o"][0]
                lane = c.get("lane") or lane_of_o.get(o) or "main"
                cc["cells"].append(_char_cell(c, lane, lac_extra=lac_extra, zi_by_o=zi_by_o))
                cv_cells.append(c)
                lanes.append(lane)
            ccols.append(cc)
        cpage: dict[str, Any] = {"page": pn}
        label = pjp.get("label") or (pjp["page"].get("label") if isinstance(pjp.get("page"), dict) else None)
        if label:
            cpage["label"] = str(label)
        cpage["columns"] = ccols

        # 格位 key：cv 口径就是锚点；lines 口径按分行稿重数，再把列号也换过去
        colmap: dict[int, int] = {}
        if keys == "lines":
            flat = [c for col in ccols for c in col["cells"]]
            if any(len(c["c"]) != 1 for c in flat):
                raise ValueError(f"p{pn}：有一格多字的格，lines 口径数不出格位")
            new = lines_slots("\n".join(page_lines(cpage)))
            if len(new) != len(flat):
                raise ValueError(f"p{pn}：分行稿数出 {len(new)} 格，char 有 {len(flat)} 格")
            for c, k, ln in zip(flat, new, lanes):
                rep["rekeyed"] += c["a"] != k
                c["a"] = k
                _set_lane(c, ln)
            li = 0
            kept = []
            for col in ccols:
                if not col["cells"]:
                    continue                                   # 分行稿里没有空列，lines 口径不给空列编号
                li += 1
                colmap[col["col"]] = li
                col["col"] = li
                kept.append(col)
            cpage["columns"] = ccols = kept
        char_pages.append(cpage)
        out_cells = [c for col in ccols for c in col["cells"]]
        keymap = {cv.get("a"): c["a"] for cv, c in zip(cv_cells, out_cells)}
        idmap = {cv["id"]: c["a"] for cv, c in zip(cv_cells, out_cells) if cv.get("id")}
        allmap.update(keymap)

        # cord
        if not (pjp.get("canvas") or {}).get("id"):
            raise ValueError(f"p{pn}：没有 canvas.id")
        kp: dict[str, Any] = {"page": pn}
        for k in ("image", "canvas", "producers"):
            if pjp.get(k) is not None:
                kp[k] = copy.deepcopy(pjp[k])
        regions = []
        for r in pjp.get("regions", []):
            if r.get("kind") not in _REGION_KINDS or not _box_ok(r.get("box")):
                rep["dropped"]["regions"] += 1
                continue
            regions.append({k: copy.deepcopy(r[k]) for k in ("id", "kind", "box", "rules") if r.get(k) is not None})
        columns = []
        for col in pjp.get("columns", []):
            n = _col_no(col.get("n", col.get("id")))
            if keys == "lines":
                if n not in colmap:
                    continue
                n = colmap[n]
            if not _box_ok(col.get("box")):
                rep["dropped"]["columns"] += 1
                continue
            columns.append({"col": n, **({"kind": col["kind"]} if col.get("kind") else {}), "box": col["box"]})
        cells = []
        for c in cv_cells:
            rep["cells"] += 1
            if not _box_ok(c.get("box")):
                rep["dropped"]["cells"] += 1
                continue
            cells.append({"a": keymap[c.get("a")], "box": c["box"], **({"id": c["id"]} if c.get("id") else {})})
            rep["boxed"] += 1
        marks = []
        for m in pjp.get("marks", []):
            if m.get("kind") not in _MARK_KINDS or not _box_ok(m.get("box")):
                rep["dropped"]["marks"] += 1
                continue
            mm: dict[str, Any] = {"kind": m["kind"]}
            if m.get("id"):
                mm["id"] = m["id"]
            n = _col_no(m.get("col"))
            if keys == "lines":
                n = colmap.get(n)                              # lines 口径下留白、排除格不占格号：只留列，不留 slot
            elif m.get("slot") is not None:
                mm["slot"] = m["slot"]
            if n is not None:
                mm["col"] = n
            mm["box"] = m["box"]
            if m.get("occludes"):
                mm["occludes"] = [idmap.get(x) or keymap.get(_strip_book(x), _strip_book(x))   # 字框 id 或 CV 格 id
                                  for x in m["occludes"]]
            if m.get("note"):
                mm["note"] = m["note"]
            marks.append(mm)
        if regions:
            kp["regions"] = regions
        if columns:
            kp["columns"] = columns
        kp["cells"] = cells
        if marks:
            kp["marks"] = marks
        cord_pages.append(kp)
        rep["pages"] += 1

    head = {"book_id": book_id, "volume": volume}
    char = {"$schema": CHAR_SCHEMA_URL, "version": version, **head, "pages": char_pages}
    cord = {"$schema": CORD_SCHEMA_URL, **head, "pages": cord_pages}
    norm_out = {"schema": NORM_SCHEMA, **head, "table": (norm or {}).get("table"),
                "items": [_norm_item(n, allmap) for n in (norm or {}).get("items", [])]}
    return {f"{chapter}.char.json": char, f"{chapter}.cord.json": cord, f"{chapter}.norm.json": norm_out}, rep


def _strip_book(x: str) -> str:
    parts = str(x).split(":")
    return ":".join(parts[1:]) if len(parts) == 4 else str(x)


def _norm_item(n: dict, keymap: dict | None) -> dict:
    a = n.get("a")
    if a is None:
        raise ValueError(f"norm 条目没有格位：{n}")
    out = {"a": keymap.get(a, a), "c": n.get("c"), "t": n["t"]}
    for k in ("by", "why"):
        if n.get(k) is not None:
            out[k] = n[k]
    return out


# ───────────────────────── 读写 ─────────────────────────

def _flat(o: Any) -> bool:
    if isinstance(o, dict):
        return all(not isinstance(v, dict) and not (isinstance(v, list) and any(isinstance(x, dict) for x in v))
                   for v in o.values())
    if isinstance(o, list):
        return not any(isinstance(x, dict) for x in o)
    return True


def dumps(obj: Any) -> str:
    """缩进两格；不再含对象的对象（一格、一个框、`image`）写在一行——git 按格比对。与 wip/siku 上 T68 的排版一致。"""
    def enc(o, ind):
        if _flat(o) or (isinstance(o, dict) and not o):
            return json.dumps(o, ensure_ascii=False)
        pad, sub = " " * ind, " " * (ind + 2)
        if isinstance(o, dict):
            body = ",\n".join(f"{sub}{json.dumps(k, ensure_ascii=False)}: {enc(v, ind + 2)}" for k, v in o.items())
            return "{\n" + body + "\n" + pad + "}"
        return "[\n" + ",\n".join(sub + enc(x, ind + 2) for x in o) + "\n" + pad + "]"
    return enc(obj, 0) + "\n"


def write_files(files: dict[str, Any], out_dir: Path | str) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, content in files.items():
        p = out / name
        p.write_text(content if isinstance(content, str) else dumps(content), encoding="utf-8", newline="\n")
        paths.append(p)
    return paths


# ───────────────────────── 校验 ─────────────────────────

def check(char: dict, cord: dict | None = None, norm: dict | None = None) -> list[str]:
    """两边一致：char 格位不重、key 的页/列与所在页/列相同；cord 的每个 `a` 在 char 里、页/列也对；
    两边页号集合相同、每页列号集合相同（cord 没有某列的框不算错）；norm 的格位在 char 里、`c` 等于该格的字。"""
    errs: list[str] = []
    where: dict[str, dict] = {}
    cols_of: dict[int, set[int]] = {}
    for p in char["pages"]:
        cols_of[p["page"]] = set()
        for col in p["columns"]:
            if col["col"] in cols_of[p["page"]]:
                errs.append(f"char p{p['page']} 列号 {col['col']} 重复")
            cols_of[p["page"]].add(col["col"])
            for c in col["cells"]:
                pg, cn, _, _ = parse_key(c["a"])
                if (pg, cn) != (p["page"], col["col"]):
                    errs.append(f"char {c['a']} 放在 p{p['page']} 列 {col['col']}")
                if c["a"] in where:
                    errs.append(f"char 格位 {c['a']} 重复")
                where[c["a"]] = c
    if cord is not None:
        cpages = {p["page"] for p in cord["pages"]}
        if cpages != set(cols_of):
            errs.append(f"页号两边不同：只在 char {sorted(set(cols_of) - cpages)[:5]}，只在 cord {sorted(cpages - set(cols_of))[:5]}")
        for p in cord["pages"]:
            ccols = {c["col"] for c in p.get("columns", [])}
            extra = ccols - cols_of.get(p["page"], set())
            if extra:
                errs.append(f"cord p{p['page']} 列 {sorted(extra)} 在 char 里没有")
            for c in p["cells"]:
                if c["a"] not in where:
                    errs.append(f"cord 格位 {c['a']} 在 char 里没有")
                    continue
                pg, cn, _, _ = parse_key(c["a"])
                if pg != p["page"]:
                    errs.append(f"cord {c['a']} 放在 p{p['page']}")
                if ccols and cn not in ccols:
                    errs.append(f"cord {c['a']} 的列 {cn} 没有列框")
            for m in p.get("marks", []):
                for a in m.get("occludes", []):
                    if a not in where:
                        errs.append(f"cord 印章压住的格 {a} 在 char 里没有")
    if norm is not None:
        for n in norm.get("items", []):
            c = where.get(n["a"])
            if c is None:
                errs.append(f"norm 格位 {n['a']} 在 char 里没有")
            elif n.get("c") is not None and n["c"] != c["c"]:
                errs.append(f"norm {n['a']} 记「{n['c']}」，char 是「{c['c']}」")
    return errs


def validate(obj: dict, kind: str) -> list[str]:
    """按 guji-format 的 JSON Schema 校验（`kind` = char / cord）。"""
    import jsonschema
    schema = json.loads(SCHEMA_PATHS[kind].read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in v.iter_errors(obj)]


def stats(char: dict, cord: dict) -> dict:
    cells = [c for p in char["pages"] for col in p["columns"] for c in col["cells"]]
    return {"pages": len(char["pages"]), "columns": sum(len(p["columns"]) for p in char["pages"]),
            "cells": len(cells), "lacuna": sum(1 for c in cells if c.get("lacuna")),
            "guess": sum(1 for c in cells if c.get("guess")), "zi": sum(1 for c in cells if "zi" in c),
            "boxed": sum(len(p["cells"]) for p in cord["pages"])}
