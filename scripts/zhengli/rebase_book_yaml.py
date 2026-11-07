"""换图源后册 yaml 的改动：钉新页表 rev，像素量按新旧页比例换算（只改文本行，不重排整份 yaml）。

场景：殿本 99 册 2026-11-07 起切到 Commons 景印文淵閣本（页表 r003/r004，设计稿见 A20 线程）。页序、页号、列、格不变，
只有像素变；每页 `from_rev.H` 给出旧页→新页的 3×3 矩阵，整册比例取各页 `sqrt|det(H[:2,:2])|` 的中位数 k（约 1.41–1.45）。

怎么改（册 yaml 里凡是「像素量」的键）：
- `source_rev`：旧值 → 新页表 rev（最新那版带 `from_rev` 的页表；旧值必须小于它，否则不动）；
- `period_prior`、`outer_gap.top/bottom`、`outer_shift.top/bottom`、`params.border_detect.grid_col_pitch`、
  `params.border_detect.head_raise_scale`：旧值 × k（head_raise_scale 实测就是按像素比例缩的：vol05 0.6889×1.4468＝0.9967）；
- `bottom_gap`（有这个键才改）：新页下方留白固定 pad.b（新页表每页同一数，殿本 36）；
- `params.border_detect.vline_overrides.<页>`：每条界线的 x 按该页 H 在页高中线处换算（旧页高 `from_rev.h`）；
- 不动：页号集（dev_set、sets、column_grid_pages 等）、`frame_layers`（层数）、各种布尔／字符串开关。

每个改动的行末加一段 `# 换新图（A20 11-07）：旧值 ×k`，原有行尾注释接在后面；整份 yaml 文件头加一行总说明。

用法：
  python scripts/zhengli/rebase_book_yaml.py <books 目录或 yaml 文件…> [--apply] [--tables 目录] [--report 报告.md]
  不加 --apply 只打印每册改动；页表缺省按册从 https://blob.open-guji.com/pack/source/pages/96mid1ogzk/<册>/ 公开读（r006…r003 取最新带 from_rev 的），
  也可 --tables <目录> 里放 <册2位>.r00N.json。重复跑不会重复改（source_rev 已是新 rev 就跳过）。
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import urllib.request
from pathlib import Path

import numpy as np

BOOK_ID = "96mid1ogzk"
BASE_URL = f"https://blob.open-guji.com/pack/source/pages/{BOOK_ID}"
TAG = "换新图（A20 11-07）"


# ── 页表 ─────────────────────────────────────────────────────────────
def _fetch(vol2: str, rev: int, tables: Path | None) -> dict | None:
    if tables:
        p = tables / f"{vol2}.r{rev:03d}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    try:
        req = urllib.request.Request(f"{BASE_URL}/{vol2}/r{rev:03d}.json", headers={"User-Agent": "open-guji-cv/rebase_book_yaml"})
        with urllib.request.urlopen(req, timeout=60) as r:       # 默认 UA 会被 CDN 403，当成「没有这一版」
            return json.loads(r.read())
    except Exception:  # noqa: BLE001  （404／403 都当没有这一版）
        return None


def latest_rebase_table(vol2: str, tables: Path | None = None) -> dict:
    """最新一版带 `from_rev` 的页表（换图源页表）。"""
    for rev in range(9, 2, -1):
        t = _fetch(vol2, rev, tables)
        if t and any(p.get("from_rev") for p in t.get("pages", [])):
            return t
    raise FileNotFoundError(f"{vol2}：找不到带 from_rev 的页表")


def scale_of(table: dict) -> float:
    ks = [float(np.sqrt(abs(np.linalg.det(np.array(p["from_rev"]["H"], float)[:2, :2]))))
          for p in table["pages"] if p.get("from_rev")]
    return float(statistics.median(ks))


def pad_bottom(table: dict) -> float | None:
    v = [p["frame"]["pad"]["b"] for p in table["pages"] if p.get("frame")]
    return float(statistics.median(v)) if v else None


def map_x(table: dict, page: int, x: float) -> float:
    """旧页（左上原点）页高中线上的 x → 新页同一位置的 x。"""
    row = next(p for p in table["pages"] if int(p["page"]) == page)
    f = row["from_rev"]
    H = np.array(f["H"], float)
    v = H @ np.array([x, f["h"] / 2.0, 1.0])
    return float(v[0] / v[2])


# ── 文本改写 ─────────────────────────────────────────────────────────
_NUM = r"-?\d+(?:\.\d+)?"


def _fmt(v: float, nd: int) -> str:
    s = f"{v:.{nd}f}"
    if nd and "." in s:
        s = s.rstrip("0").rstrip(".") if nd > 1 else s     # nd=1 保留一位（114.0 不写成 114）
    return s


def _sub_line(line: str, new: str, note: str) -> str:
    """把行里 `键: <旧值>` 的旧值换成 new，行尾加注，原行尾注释接后面。"""
    m = re.match(rf"^(\s*[^#\s][^:]*:\s*)({_NUM})(\s*)(#.*)?$", line.rstrip("\n"))
    if not m:
        raise ValueError(f"认不出的行：{line!r}")
    head, old, _, cmt = m.groups()
    tail = f"   # {TAG}：{note}" + (f"；原注：{cmt[1:].strip()}" if cmt else "")
    return f"{head}{new}{tail}\n"


def _find(lines: list[str], key: str, indent: int | None = None, start: int = 0, stop: int | None = None) -> int | None:
    lead = " " * indent if indent is not None else r"\s*"     # f-string 里不能有反斜杠（3.11）
    pat = re.compile(rf"^{lead}{re.escape(key)}:\s*")
    for i in range(start, len(lines) if stop is None else stop):
        if pat.match(lines[i]) and not lines[i].lstrip().startswith("#"):
            return i
    return None


def _block_end(lines: list[str], i: int) -> int:
    """第 i 行是 `key:`（无值），返回这个块的末行（缩进更深的连续行，含空行与注释）后一行。"""
    ind = len(lines[i]) - len(lines[i].lstrip())
    j = i + 1
    while j < len(lines):
        s = lines[j]
        if s.strip() and not s.lstrip().startswith("#") and (len(s) - len(s.lstrip())) <= ind:
            break
        j += 1
    return j


def rebase_yaml_text(text: str, vol2: str, table: dict) -> tuple[str, list[str]]:
    """返回 (新文本, 改动清单)。没有可改的（已经是新 rev）返回原文本与空清单。"""
    lines = text.splitlines(keepends=True)
    changes: list[str] = []
    new_rev = int(table["rev"])
    k = scale_of(table)
    ks = f"×{k:.4f}"

    i = _find(lines, "source_rev", 0)
    if i is None:
        raise ValueError("册 yaml 没有 source_rev（没钉页表的册不在这次范围）")
    old_rev = int(re.search(rf"({_NUM})", lines[i].split(":", 1)[1])[1])
    if old_rev >= new_rev:
        return text, []
    lines[i] = _sub_line(lines[i], str(new_rev), f"页表 rev {old_rev} → {new_rev}")
    changes.append(f"source_rev {old_rev} → {new_rev}")

    def scaled(key: str, indent: int | None, nd: int, *, start: int = 0, stop: int | None = None, label: str = "") -> None:
        j = _find(lines, key, indent, start, stop)
        if j is None:
            return
        old = float(re.search(_NUM, lines[j].split(":", 1)[1])[0])
        new = old * k
        text_new = str(int(round(new))) if nd == 0 else _fmt(new, nd)
        lines[j] = _sub_line(lines[j], text_new, f"旧 {_fmt(old, 4)} {ks}")
        changes.append(f"{label or key} {_fmt(old, 4)} → {text_new}")

    scaled("period_prior", 0, 1)
    j = _find(lines, "bottom_gap", 0)
    if j is not None:
        pb = pad_bottom(table)
        if pb is not None:
            old = float(re.search(_NUM, lines[j].split(":", 1)[1])[0])
            lines[j] = _sub_line(lines[j], _fmt(pb, 1) if pb != int(pb) else f"{pb:.1f}", f"旧 {_fmt(old, 4)}，新页下方留白 pad.b")
            changes.append(f"bottom_gap {_fmt(old, 4)} → {pb:.1f}")
    for blk in ("outer_gap", "outer_shift"):
        b = _find(lines, blk, 0)
        if b is not None:
            end = _block_end(lines, b)
            for sub in ("top", "bottom"):
                scaled(sub, 2, 1, start=b + 1, stop=end, label=f"{blk}.{sub}")
    scaled("head_raise_scale", None, 4)
    scaled("grid_col_pitch", None, 0)

    v = _find(lines, "vline_overrides", None)
    if v is not None:
        end = _block_end(lines, v)
        for j in range(v + 1, end):
            m = re.match(r"^(\s*)(\d+):\s*\[([^\]]*)\](\s*)(#.*)?$", lines[j].rstrip("\n"))
            if not m:
                continue
            ind, page, xs, _, cmt = m.groups()
            old = [float(a) for a in xs.split(",") if a.strip()]
            new = [int(round(map_x(table, int(page), a))) for a in old]
            tail = f"   # {TAG}：旧 [{', '.join(str(int(a)) if a == int(a) else str(a) for a in old)}] 按第 {page} 页 H 在页高中线换算" \
                   + (f"；原注：{cmt[1:].strip()}" if cmt else "")
            lines[j] = f"{ind}{page}: [{', '.join(map(str, new))}]{tail}\n"
            changes.append(f"vline_overrides.{page} 换算 {len(new)} 条")

    head = (f"# {TAG}：景印文淵閣本按版框重切，页表 rev {old_rev} → {new_rev}（页序、页号、列、格不变），"
            f"像素量按整册比例 k={k:.4f} 换算；由 scripts/zhengli/rebase_book_yaml.py 生成，旧值见各行注释。\n")
    return head + "".join(lines), changes


# ── 命令行 ───────────────────────────────────────────────────────────
def _yamls(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        out += sorted(p.glob("vol*.yaml")) if p.is_dir() else [p]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--apply", action="store_true", help="写回 yaml（缺省只打印）")
    ap.add_argument("--tables", type=Path, default=None, help="页表目录（<册2位>.r00N.json），缺省从公开地址取")
    ap.add_argument("--report", type=Path, default=None)
    a = ap.parse_args(argv)
    rep = ["# 殿本册 yaml 换图源改动", ""]
    n_changed = 0
    for f in _yamls(a.paths):
        m = re.fullmatch(r"vol(\d+)\.yaml", f.name)
        if not m:
            continue
        vol2 = f"{int(m[1]):02d}"
        table = latest_rebase_table(vol2, a.tables)
        new, ch = rebase_yaml_text(f.read_text(encoding="utf-8"), vol2, table)
        if not ch:
            print(f"{f.name}: 已是新 rev 或无需改，跳过")
            continue
        n_changed += 1
        line = f"{f.name}（k={scale_of(table):.4f}，r{int(table['rev']):03d}）：" + "；".join(ch)
        print(line)
        rep.append(f"- {line}")
        if a.apply:
            f.write_text(new, encoding="utf-8", newline="\n")
    print(f"共改 {n_changed} 册" + ("（已写回）" if a.apply else "（预览，加 --apply 写回）"))
    if a.report:
        a.report.write_text("\n".join(rep) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
