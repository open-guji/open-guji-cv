# -*- coding: utf-8 -*-
"""book-text 新形态：`NNN.char.json`（字）＋ `NNN.cord.json`（框）＋ `NNN.norm.json`（按格位的例外）。F4 道，overview#419。

规范：guji-format `spec/01-guji-cord.md`、`spec/02-guji-char.md`，schema 在仓根 `formats/guji_{char,cord}_v0.1.schema.json`
（从 guji-format 7ad86dc 照抄，测试只读本仓）；char v0.2（`guess_c`）的 `formats/guji_char_v0.2.schema.json` 从 guji-format
0370a39（GUJI-717，guji-format#21）照抄。book-text 一侧见 `docs/ORIGINAL.md`。

入口只吃 F3 的 `guji-pages/0.1`（`NNN.pages.json`，格里带字）——**不读产物**：

- `from_pages_json(pj, zi=…, norm=…)` → `{NNN.char.json, NNN.cord.json, NNN.norm.json}`；
- `char_to_lines_md(char)` → 分行稿（spec 03 §三）；`guess_c_as_qz=True` 时与 `guji_page.to_guji_markdown`（Step9 9.1）
  逐字相同（只差阙文带推测字一处写法，见下）；
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
- 阙文带推测字（char v0.2 `guess_c`，GUJI-717，用户 10-20 定「录文以图为准」）= 字框 `guess` 且字是「□」——这只有
  人裁 `confirm v=damaged` 带 `guess=X` 一条来路（排除名单 evidence `guess=X` → Step7 `□` 占位 → 9.1 `□{guess=X}`）：
  `{"c": "□", "lacuna": true, "guess_c": X}`。原先写成残字 `guess: true`、`c` 写 X（阅读器出灰字 X），与「图上无字录 □」
  相反，改掉；char 里因此不再出 `guess: true`。有 `guess_c` 的册 `$schema` 写 char v0.2，没有的照旧 v0.1，逐字节不变。
  分行稿（spec 03 §三）里这格照阙文写 `[[]]`；9.1 的 lines.md 写的是 `□{guess=X}`，核往返时用 `guess_c_as_qz=True`；
- `lane` 只在推不出来时写：`solo` 总写；夹注只在格位后缀与左右不符时写（lines 口径下单边夹注一律记 `a`）；
- 列：`raised`、`lead_blank` 非 0 才写；`kind` 版心记 `banxin`、没有字的列记 `blank`，正文不写。

cord 去掉字和 CV 内部字段（`by`、`cv_id`、`o`、`runs`、`lacuna`…）；`box` 为空的版框、列、格、记号不写（cord
允许 char 里的格暂时没有框）。norm 每条 `{a, c, t, by?, why?}`，按格位 key、不带字偏移。

**图（GUJI-740，char v0.3／cord v0.2／fig v0.1，guji-format spec 09）**：

- 图片格：pages.json 的格带 `fig: {"alt": …}`（人裁 `confirm v=figure` → 排除名单理由 `figure` → `report/slots`
  → guji-page 字框 `fig`）→ char `{"a", "c": "□", "fig": <图 id>}`，不带 `lacuna`；cord 照旧在 `cells[]`；
- 插图块：`from_pages_json(figure_regions=…)`（控制台 `figure_region`，`feedback/figures.resolved_figure_regions`）→ char 在读序位置
  插一项图列 `{"col", "kind": "figure", "span", "fig", "cells": []}`，被占的列（含其上切出来的格、norm）去掉；cord 去掉
  这几列的列框、格、记号，`marks[]` 加 `{"kind": "figure", "fig", "col", "span", "box"}`；
- 两种都在 `NNN.fig.json` 记一条（`kind` inline／block，`box` 与 cord 一致）。文件字段（`sha256`、`width`、`height`）
  由 `crop_figures` 从页图裁出后填；**已有 fig.json（`prev_fig`，取 book-text 现行那份）里同页、框重叠的图沿用它的 id**
  （id 不跟格位变，spec 09 §3.2），`source: redraw` 的条目原样保留、不用裁图覆盖（只跟着改 `page`／`box`）；
- 用到图的册 char `$schema` 写 v0.3、有插图块的 cord 写 v0.2；没用到图的册逐字节不变（照旧 v0.1／v0.2，不出 fig.json）。
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

CHAR_SCHEMA_URL = "https://open-guji.org/schema/char/v0.1.json"
CHAR_SCHEMA_URL_V02 = "https://open-guji.org/schema/char/v0.2.json"     # 有 guess_c（阙文带推测字）才写这一版
CHAR_SCHEMA_URL_V03 = "https://open-guji.org/schema/char/v0.3.json"     # 有图片格或图列才写这一版
CORD_SCHEMA_URL = "https://open-guji.org/schema/cord/v0.1.json"
CORD_SCHEMA_URL_V02 = "https://open-guji.org/schema/cord/v0.2.json"     # 有插图块（marks.figure）才写这一版
FIG_SCHEMA_URL = "https://open-guji.org/schema/fig/v0.1.json"
FIG_DEFAULT_ALT = "图形符号"           # 人定是图时没写说明（spec 09 §3.2）
NORM_SCHEMA = "guji-norm/0.2"          # guji-format 还没有 norm 的 schema；0.1 是 F3 带字偏移 `o` 的那版
LACUNA_CHAR = "□"
ZI_NO_NEAR = "〓"
_FORMATS = Path(__file__).resolve().parents[2] / "formats"
SCHEMA_PATHS = {"char": _FORMATS / "guji_char_v0.1.schema.json",
                "cord": _FORMATS / "guji_cord_v0.1.schema.json",
                "fig": _FORMATS / "guji_fig_v0.1.schema.json"}
CHAR_SCHEMA_FILES = {CHAR_SCHEMA_URL: SCHEMA_PATHS["char"], CHAR_SCHEMA_URL_V02: _FORMATS / "guji_char_v0.2.schema.json",
                     CHAR_SCHEMA_URL_V03: _FORMATS / "guji_char_v0.3.schema.json"}
CORD_SCHEMA_FILES = {CORD_SCHEMA_URL: SCHEMA_PATHS["cord"], CORD_SCHEMA_URL_V02: _FORMATS / "guji_cord_v0.2.schema.json"}
KEYS = ("cv", "lines")

_REGION_KINDS = ("body", "banxin", "margin")
_MARK_KINDS = ("blank", "seal", "excluded")      # pages.json 里认的；`figure` 由 regions 另加
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

def _tok(cell: dict, *, in_solo: bool = False, guess_c_as_qz: bool = False, alts: dict | None = None) -> str:
    if cell.get("fig") is not None:
        # 图片格（spec 03 §三·5）：`:tu[说明]{id=…}`；核 9.1 往返（`guess_c_as_qz`）或不给 fig.json 时写 `c`（□），
        # 9.1 的 lines.md 里这格就是一个 □（`lines_slots` 也按一格数）
        if guess_c_as_qz or alts is None:
            return cell["c"]
        return f":tu[{alts.get(cell['fig']) or FIG_DEFAULT_ALT}]{{id={cell['fig']}}}"
    if cell.get("lacuna"):
        if guess_c_as_qz and cell.get("guess_c"):
            return f"□{{guess={cell['guess_c']}}}"   # 9.1 的写法（原刻残＋人给的最像字），只用于核往返
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


def column_line(col: dict, *, guess_c_as_qz: bool = False, alts: dict | None = None) -> str | None:
    """一列 → 分行稿的一行；没有字的列返回 None（分行稿不出空行）。`guess_c_as_qz`、`alts` 见 `char_to_lines_md`。"""
    if col.get("kind") == "figure":
        # 图列（spec 03 §三·5）：单独一行 `::tu[说明]{id=…}`；核 9.1 往返时不出（9.1 不知道插图块）
        if guess_c_as_qz or alts is None:
            return None
        return f"::tu[{alts.get(col['fig']) or FIG_DEFAULT_ALT}]{{id={col['fig']}}}"
    if not col.get("cells"):
        return None

    def tok(cell: dict, *, in_solo: bool = False) -> str:
        return _tok(cell, in_solo=in_solo, guess_c_as_qz=guess_c_as_qz, alts=alts)

    out = ["^" * int(col.get("raised") or 0) + "." * int(col.get("lead_blank") or 0)]
    runs = _runs(col["cells"])
    k = 0
    while k < len(runs):
        ln, cs = runs[k]
        if ln in ("jz_r", "jz_l"):
            right = "".join(map(tok, cs)) if ln == "jz_r" else ""
            left = "".join(map(tok, cs)) if ln == "jz_l" else ""
            if ln == "jz_r" and k + 1 < len(runs) and runs[k + 1][0] == "jz_l":
                left = "".join(map(tok, runs[k + 1][1]))
                k += 1
            out.append(f"<{right}|{left}>" if right and left else f"<{right}{left}>")
        elif ln == "solo":
            out.append(":jz[" + "".join(tok(c, in_solo=True) for c in cs) + "]{type=单行}")
        else:
            out.append("".join(map(tok, cs)))
        k += 1
    return "".join(out)


def page_lines(page: dict, *, guess_c_as_qz: bool = False, alts: dict | None = None) -> list[str]:
    lines = [f"<!-- p{page['page']} -->"]
    lines += [ln for ln in (column_line(c, guess_c_as_qz=guess_c_as_qz, alts=alts) for c in page["columns"])
              if ln is not None]
    return lines


def char_to_lines_md(char: dict, *, guess_c_as_qz: bool = False, fig: dict | None = None) -> str:
    """char → 一列一行的分行稿（每页先 `<!-- pN -->`，末尾一个换行），记法照 guji-format spec 03 §三。

    `guess_c_as_qz=True`：阙文带推测字写成 9.1 的 `□{guess=X}`、图片格写 □、图列不出，此时与 F3 导出的
    `NNN.lines.md` 逐字节相同，导出器核往返用它；缺省照 spec 03 写 `[[]]`（`□{guess=X}` 在分行稿里是残字
    `guess: true` 的写法）。`fig`（同章 fig.json）给了，图片格写 `:tu[说明]{id=…}`、图列写一行 `::tu[说明]{id=…}`。"""
    alts = {f["id"]: f.get("alt") for f in fig["figures"]} if fig else None
    return "\n".join("\n".join(page_lines(p, guess_c_as_qz=guess_c_as_qz, alts=alts)) for p in char["pages"]) + "\n"


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
    if c.get("fig") is not None:
        # 图片格（char v0.3）：`c` 写 □，不带 lacuna／guess／zi；图 id 由 from_pages_json 定好后填进 `fig`
        out["c"] = LACUNA_CHAR
        _set_lane(out, lane)
        out["fig"] = ""
        return out
    z = zi_by_o.get(o)
    if z is not None:
        out["c"] = z.get("near") or ZI_NO_NEAR
        out["zi"] = z.get("ids") if z.get("ids") is not None else z.get("desc")
    _set_lane(out, lane)
    if c.get("lacuna") == "unreadable" or o in lac_extra:
        out["c"], out["lacuna"] = LACUNA_CHAR, True
    elif c.get("guess") and c["c"] == "□" and z is None:
        # 原刻残、人给了最像的字（confirm v=damaged guess=X）：录 □，推测字记 guess_c（char v0.2，GUJI-717）
        out["c"], out["lacuna"], out["guess_c"] = LACUNA_CHAR, True, c["guess"]
    return out


def _set_lane(cell: dict, lane: str) -> None:
    """`lane` 只在推不出来时写：solo 总写，夹注与 key 后缀不符才写，main 不写。"""
    cell.pop("lane", None)
    if lane == "solo" or (lane in _JZ_SUFFIX and not cell["a"].endswith(_JZ_SUFFIX[lane])):
        cell["lane"] = lane


def _box_ok(b) -> bool:
    return isinstance(b, list) and len(b) == 4 and all(isinstance(x, (int, float)) for x in b)


def from_pages_json(pj: dict, *, zi: dict | None = None, norm: dict | None = None, version: str = "0.1.0",
                    keys: str = "cv", chapter: str | None = None, figure_regions: dict[int, list[dict]] | None = None,
                    prev_fig: dict | None = None) -> tuple[dict[str, dict], dict]:
    """`guji-pages/0.1` → (`{NNN.char.json, NNN.cord.json, NNN.norm.json[, NNN.fig.json]}`, 报告)。

    `zi`/`norm` 是 F3 同章的 `zi.json`（`guji-zi/0.1`）/`norm.json`（`guji-norm/0.1`），没有就当空。
    `figure_regions`：插图块 `{页: [{box, col, span, alt, fig?}]}`（`feedback/figures.resolved_figure_regions`）；
    `prev_fig`：book-text 现行的同章 fig.json（沿用图 id、保留重绘图），见模块头「图」。用到图才出 `NNN.fig.json`，
    其中文件字段待 `crop_figures` 填。
    报告 `{pages, cells, boxed, dropped: {regions, columns, cells, marks}, rekeyed, figures: {inline, block, kept, dropped_cells}}`。
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
    fig_alt: dict[tuple[int, str], str] = {}                   # (页, 输出 key) → 图片格说明
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
        for cv, c in zip(cv_cells, out_cells):
            if c.get("fig") is not None:
                fig_alt[(pn, c["a"])] = str((cv.get("fig") or {}).get("alt") or "")

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
    norm_items = [_norm_item(n, allmap) for n in (norm or {}).get("items", [])]
    figures, frep = _apply_figures(char_pages, cord_pages, fig_alt, figure_regions or {}, prev_fig, chapter)
    rep["figures"] = frep
    if frep["dropped_cells"]:
        gone = set(frep["dropped_cells"])
        norm_items = [n for n in norm_items if n["a"] not in gone]  # 插图块占掉的格上的规范层一并去掉
    has_fig = bool(figures)
    has_guess_c = any("guess_c" in c for p in char_pages for col in p["columns"] for c in col["cells"])
    char = {"$schema": CHAR_SCHEMA_URL_V03 if has_fig else CHAR_SCHEMA_URL_V02 if has_guess_c else CHAR_SCHEMA_URL,
            "version": version, **head, "pages": char_pages}
    has_block = any(m["kind"] == "figure" for p in cord_pages for m in p.get("marks", []))
    cord = {"$schema": CORD_SCHEMA_URL_V02 if has_block else CORD_SCHEMA_URL, **head, "pages": cord_pages}
    norm_out = {"schema": NORM_SCHEMA, **head, "table": (norm or {}).get("table"), "items": norm_items}
    out = {f"{chapter}.char.json": char, f"{chapter}.cord.json": cord, f"{chapter}.norm.json": norm_out}
    if figures:
        out[f"{chapter}.fig.json"] = {"$schema": FIG_SCHEMA_URL, **head, "figures": figures}
    return out, rep


# ───────────────────────── 图（char v0.3 / cord v0.2 / fig v0.1） ─────────────────────────

_FIG_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def inline_fig_id(a: str) -> str:
    """图片格的缺省图 id：`148:2:14` → `f148-2-14`，`3:4:-1` → `f3-4-m1`，`9:2:5a` → `f9-2-5a`（spec 09 §3.2 建议写法）。"""
    pg, col, slot, sub = parse_key(a)
    return f"f{pg}-{col}-{'m' + str(-slot) if slot < 0 else slot}{sub}"


def _iou(a: list, b: list) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _apply_figures(char_pages: list[dict], cord_pages: list[dict], fig_alt: dict[tuple[int, str], str],
                   regions: dict[int, list[dict]], prev_fig: dict | None, chapter: str) -> tuple[list[dict], dict]:
    """就地改 char／cord：插图块换掉被占的列、图片格填图 id；返回 (fig.json 的 figures, 报告)。"""
    rep: dict[str, Any] = {"inline": 0, "block": 0, "kept": 0, "dropped_cells": []}
    prev = [f for f in (prev_fig or {}).get("figures") or []]
    taken: set[str] = set()
    figures: list[dict] = []

    def pick_id(kind: str, page: int, box: list | None, want: str) -> tuple[str, dict | None]:
        """同类、同页、框重叠（IoU ≥ 0.5）的旧图沿用它的 id；否则用 `want`（撞了加 -2、-3…）。"""
        if box is not None:
            best = max((f for f in prev if f.get("kind") == kind and f.get("page") == page and f["id"] not in taken),
                       key=lambda f: _iou(f["box"], box), default=None)
            if best is not None and _iou(best["box"], box) >= 0.5:
                taken.add(best["id"])
                return best["id"], best
        if not _FIG_ID_RE.match(want):
            raise ValueError(f"图 id 不合 [a-z0-9][a-z0-9-]*：{want!r}")
        fid, k = want, 1
        used = taken | {f["id"] for f in prev}
        while fid in used:
            k += 1
            fid = f"{want}-{k}"
        taken.add(fid)
        return fid, None

    def entry(fid: str, kind: str, page: int, box: list, alt: str, old: dict | None) -> dict:
        if old is not None and old.get("source") == "redraw":
            rep["kept"] += 1                   # 重绘图：文件、来源原样保留，只跟着改位置
            return {**old, "page": page, "box": box}
        ext = "png" if kind == "inline" else "webp"
        return {"id": fid, "kind": kind, "page": page, "box": box, "alt": alt or (old or {}).get("alt") or FIG_DEFAULT_ALT,
                "file": f"fig/{chapter}/{fid}.{ext}", "sha256": None,
                "mime": "image/png" if ext == "png" else "image/webp", "width": None, "height": None,
                "source": "crop", "by": "cv:export"}

    cord_by_page = {p["page"]: p for p in cord_pages}
    for cp in char_pages:
        pn = cp["page"]
        kp = cord_by_page.get(pn) or {}
        # 插图块：被占的列（含格）从 char、cord 去掉，读序位置插图列
        for k, r in enumerate(regions.get(pn) or [], 1):
            lo, span = int(r["col"]), int(r.get("span") or 1)
            covered = set(range(lo, lo + span))
            gone = [c["a"] for col in cp["columns"] if col["col"] in covered for c in col["cells"]]
            rep["dropped_cells"] += gone
            if any(col.get("kind") == "figure" and col["col"] in covered for col in cp["columns"]):
                raise ValueError(f"p{pn}：插图块 {r} 与本页另一个插图块重叠")
            fid, old = pick_id("block", pn, r["box"], r.get("fig") or f"p{pn}-fig{k}")
            fcol = {"col": lo, "kind": "figure", **({"span": span} if span != 1 else {}), "fig": fid, "cells": []}
            keep = [col for col in cp["columns"] if col["col"] not in covered]
            at = next((i for i, col in enumerate(keep) if col["col"] > lo), len(keep))
            cp["columns"] = keep[:at] + [fcol] + keep[at:]
            gone_set = set(gone)
            if kp.get("columns"):
                kp["columns"] = [c for c in kp["columns"] if c["col"] not in covered]
            kp["cells"] = [c for c in kp.get("cells", []) if c["a"] not in gone_set]
            marks = []
            for m in kp.get("marks", []):
                if m.get("col") in covered:
                    continue
                if m.get("occludes"):                  # 印章压着的格被插图块占掉了：引用跟着去掉
                    m["occludes"] = [x for x in m["occludes"] if x not in gone_set]
                    if not m["occludes"]:
                        del m["occludes"]
                marks.append(m)
            marks.append({"kind": "figure", "id": f"mfig-{fid}", "fig": fid, "col": lo,
                          **({"span": span} if span != 1 else {}), "box": list(r["box"])})
            kp["marks"] = marks
            figures.append(entry(fid, "block", pn, list(r["box"]), str(r.get("alt") or ""), old))
            rep["block"] += 1
        # 图片格
        box_of = {c["a"]: c["box"] for c in kp.get("cells", [])}
        for col in cp["columns"]:
            for c in col["cells"]:
                if c.get("fig") is None:
                    continue
                box = box_of.get(c["a"])
                if box is None:
                    raise ValueError(f"图片格 {c['a']} 在 cord 里没有框，裁不出图")
                fid, old = pick_id("inline", pn, box, inline_fig_id(c["a"]))
                c["fig"] = fid
                figures.append(entry(fid, "inline", pn, box, fig_alt.get((pn, c["a"]), ""), old))
                rep["inline"] += 1
    return figures, rep


def check_fig(char: dict, cord: dict, fig: dict | None) -> list[str]:
    """图的一致性（book-text F-OV-13 第 2、3、5 条在 cv 一侧先核）：引用的图都在 fig.json、不留孤图、类别对得上；
    图片格 `c` 是 □、不带阙文等标记；图列 `cells` 为空；fig 的 `page`／`box` 与 cord 一致；文件字段已填。"""
    errs: list[str] = []
    figs = {f["id"]: f for f in (fig or {}).get("figures") or []}
    used: dict[str, str] = {}
    for p in char["pages"]:
        for col in p["columns"]:
            if col.get("kind") == "figure":
                used[col["fig"]] = "block"
                if col["cells"]:
                    errs.append(f"char p{p['page']} 图列 {col['col']} 带了格")
            for c in col["cells"]:
                if c.get("fig") is None:
                    continue
                used[c["fig"]] = "inline"
                if c["c"] != LACUNA_CHAR or any(k in c for k in ("lacuna", "guess", "guess_c", "zi")):
                    errs.append(f"char 图片格 {c['a']} 的 c 不是 □ 或带了阙文／残字／组字标记")
    for fid, kind in used.items():
        f = figs.get(fid)
        if f is None:
            errs.append(f"char 引用的图 {fid} 在 fig.json 里没有")
        elif f["kind"] != kind:
            errs.append(f"图 {fid}：char 里是 {kind}，fig.json 记 {f['kind']}")
    for fid in figs:
        if fid not in used:
            errs.append(f"fig.json 的图 {fid} 没有被 char 引用（孤图）")
    box_of = {(p["page"], c["a"]): c["box"] for p in cord["pages"] for c in p["cells"]}
    mark_of = {m["fig"]: (p["page"], m["box"]) for p in cord["pages"] for m in p.get("marks", [])
               if m["kind"] == "figure"}
    for p in char["pages"]:
        for col in p["columns"]:
            for c in col["cells"]:
                f = figs.get(c.get("fig") or "")
                if f and (f["page"] != p["page"] or list(f["box"]) != list(box_of.get((p["page"], c["a"])) or [])):
                    errs.append(f"图 {f['id']} 的页／框与 cord 格 {c['a']} 不一致")
            if col.get("kind") == "figure":
                f = figs.get(col["fig"])
                m = mark_of.get(col["fig"])
                if f and (m is None or m[0] != f["page"] or list(m[1]) != list(f["box"])):
                    errs.append(f"图 {col['fig']} 的页／框与 cord marks.figure 不一致")
    for f in figs.values():
        if not f.get("sha256") or not f.get("width") or not f.get("height"):
            errs.append(f"图 {f['id']} 还没裁（sha256／width／height 空）")
    return errs


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
    """两边一致：char 格位不重、key 的页/列与所在页/列相同；cord 的每个 `a` 在 char 里、页/列也对、marks 的 id 不重复；
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
        mark_ids: set[str] = set()
        for p in cord["pages"]:
            for m in p.get("marks", []):
                if m.get("id") is None:
                    continue
                if m["id"] in mark_ids:
                    errs.append(f"cord p{p['page']} mark id {m['id']} 重复")
                mark_ids.add(m["id"])
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
    """按 guji-format 的 JSON Schema 校验（`kind` = char / cord / fig）。char、cord 按它自己的 `$schema` 取版本
    （char v0.1／v0.2／v0.3，cord v0.1／v0.2），认不出的按 v0.1。"""
    import jsonschema
    files = {"char": CHAR_SCHEMA_FILES, "cord": CORD_SCHEMA_FILES}.get(kind, {})
    path = files.get(obj.get("$schema"), SCHEMA_PATHS[kind])
    schema = json.loads(path.read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in v.iter_errors(obj)]


def stats(char: dict, cord: dict) -> dict:
    cells = [c for p in char["pages"] for col in p["columns"] for c in col["cells"]]
    return {"pages": len(char["pages"]), "columns": sum(len(p["columns"]) for p in char["pages"]),
            "cells": len(cells), "lacuna": sum(1 for c in cells if c.get("lacuna")),
            "guess": sum(1 for c in cells if c.get("guess")), "guess_c": sum(1 for c in cells if c.get("guess_c")),
            "zi": sum(1 for c in cells if "zi" in c), "fig": sum(1 for c in cells if c.get("fig")),
            "fig_cols": sum(1 for p in char["pages"] for col in p["columns"] if col.get("kind") == "figure"),
            "boxed": sum(len(p["cells"]) for p in cord["pages"])}


# ───────────────────────── 裁图 ─────────────────────────

FIG_PAD = 2                     # 按框外扩 2 像素裁（spec 09 §四）
FIG_MAX_BYTES = 1 << 20         # 单个文件 ≤ 1 MB
FIG_MAX_SIDE = 2000             # 超了的插图块先降到长边 2000


def _encode(im, mime: str) -> bytes:
    import io
    buf = io.BytesIO()
    if mime == "image/png":
        im.save(buf, format="PNG", optimize=True)
    else:
        im.save(buf, format="WEBP", quality=90, method=6)
    return buf.getvalue()


def crop_figures(fig: dict, cord: dict, load_image, out_dir: Path | str) -> list[str]:
    """按 fig.json 里 `source: crop` 的每张图，从页图裁出、写到 `<out_dir>/<file>`，填 `sha256`／`width`／`height`。
    就地改 `fig`；返回问题清单（裁不了的图留空，交 `check_fig` 报）。

    `load_image(page, sha256)` → PIL 图（或 None）：取 **cord 该页 `image.sha256` 那张页图**（坐标就是在它上面量的）——
    导出脚本先找工作区原图（sha 对得上才用），再取 R2 页图（`blob.open-guji.com/sha256/…`）。
    canvas 与这张图尺寸不同（拆页、换图）时框不在同一坐标里，不裁、报出来。
    不去底、不二值化，保持书影原貌（读者端按主题调色）。`source: redraw` 不碰。"""
    import hashlib

    from PIL import Image
    out = Path(out_dir)
    pages = {p["page"]: p for p in cord["pages"]}
    errs: list[str] = []
    cache: dict[int, Any] = {}
    for f in fig["figures"]:
        if f.get("source") != "crop":
            continue
        kp = pages.get(f["page"]) or {}
        img_meta, canvas = kp.get("image") or {}, kp.get("canvas") or {}
        if canvas.get("width") and img_meta.get("width") and (canvas["width"], canvas.get("height")) != \
                (img_meta["width"], img_meta.get("height")):
            errs.append(f"图 {f['id']}：p{f['page']} 的 canvas 与跑批页图尺寸不同，框不在页图坐标里，没裁（需人核）")
            continue
        if f["page"] not in cache:
            cache[f["page"]] = load_image(f["page"], img_meta.get("sha256"))
        im = cache[f["page"]]
        if im is None:
            errs.append(f"图 {f['id']}：取不到 p{f['page']} 的页图（sha256 {str(img_meta.get('sha256'))[:12]}）")
            continue
        x, y, w, h = f["box"]
        box = (max(0, int(x) - FIG_PAD), max(0, int(y) - FIG_PAD),
               min(im.width, int(round(x + w)) + FIG_PAD), min(im.height, int(round(y + h)) + FIG_PAD))
        crop = im.crop(box)
        if crop.mode not in ("L", "RGB", "1"):
            crop = crop.convert("RGB")
        if crop.mode == "1":
            crop = crop.convert("L")
        data = _encode(crop, f["mime"])
        if len(data) > FIG_MAX_BYTES and max(crop.size) > FIG_MAX_SIDE:
            r = FIG_MAX_SIDE / max(crop.size)
            crop = crop.resize((max(1, round(crop.width * r)), max(1, round(crop.height * r))), Image.LANCZOS)
            data = _encode(crop, f["mime"])
        if len(data) > FIG_MAX_BYTES:
            errs.append(f"图 {f['id']}：裁出来 {len(data)} 字节，超过 1 MB")
            continue
        dst = out / f["file"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        f.update(sha256=hashlib.sha256(data).hexdigest(), width=crop.width, height=crop.height)
    return errs
