#!/usr/bin/env python3
"""已知错单（GUJI-684，M10 总设计 G4）：把散在各处的历史错例汇成一张表，对 book-text 当前文本逐格核。

两步：
  build  从来源汇成 known-errors.tsv（列：cell  shown  expect  kind  source  note）
  check  对 book-text 某书 default 目录下各章 char.json 逐格比，分四类报：
         still_wrong 仍是错字 ／ fixed 已改对 ／ changed 格上的字既不是错字也不是应为字（多半格号变了，要看图）／
         missing 文本里没有这一格（重切换号，或非字已排除）

用法：
  python scripts/zhengli/known_errors.py build -o known-errors.tsv \
      --table <ai-team>/team/CV/基线错放格总表-Ezra.md \
      --vision <ws>/reports/vol04/看图结论.jsonl --vision <ws>/reports/vol05/看图结论.jsonl \
      --extra extra.tsv
  python scripts/zhengli/known_errors.py check --list known-errors.tsv \
      --text-dir <book-text>/Book/g/z/k/96mid1ogzk/default [--json out.json] [--strict]

kind：char＝应为某字；nonchar＝不是字（应排除或不出字）；review＝只知道错、不知道应为什么，要人看。
来源里「看图结论」是模型判的（vision），不是人裁：check 照样列，但 source 带 vision，改字前要人确认。
只读：不写事件、不写文本。--strict 时有 still_wrong（kind=char/nonchar）退出码 3。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

COLS = ["cell", "shown", "expect", "kind", "source", "note"]
CELL_RE = re.compile(r"^(vol\d{2}):(\d+):(\d+):(-?\d+[ab]?)$")


def _first_char(s: str) -> str:
    s = s.strip()
    return s[0] if s else ""


def parse_table(path: Path) -> list[dict]:
    """基线错放格总表第一节：| 格号 | 放的字 | 应为 | 来源 | 是否 iron | 窗口新引入 | 要不要给 Eliot |。"""
    rows = []
    in_list = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_list = line.startswith("## 一")
            continue
        if not in_list or not line.startswith("| vol"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        cell, shown, expect, _src, _iron, _new, give = cells[:7]
        if give.startswith("否"):
            continue                      # 撤出错放清单的（如文本对）
        note = expect
        if expect.startswith("非字"):
            kind, exp = "nonchar", ""
        elif expect.startswith(("待审", "待证据")):
            kind, exp = "review", ""
        else:
            kind, exp = "char", _first_char(expect)
        if "待证据" in _iron or "疑" in expect:
            note += "；证据未坐实"
        rows.append({"cell": cell, "shown": _first_char(shown), "expect": exp, "kind": kind,
                     "source": f"{path.name}", "note": note})
    return rows


def parse_vision(path: Path) -> list[dict]:
    """看图结论.jsonl 里 v=wrong 的行（模型看图，不是人裁）。同一格按 ts 后到覆盖。"""
    last: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        prev = last.get(r["cell"])
        if prev is None or str(r.get("ts", "")) >= str(prev.get("ts", "")):
            last[r["cell"]] = r
    rows = []
    for cell, r in last.items():
        if r.get("v") != "wrong":
            continue
        note = r.get("note", "")
        if r.get("char"):
            kind, exp = "char", r["char"]
        elif "非字" in note:
            kind, exp = "nonchar", ""
        else:
            kind, exp = "review", ""
        rows.append({"cell": cell, "shown": r.get("shown", ""), "expect": exp, "kind": kind,
                     "source": f"vision:{r.get('judge', '?')}:{path.parent.name}/{path.name}", "note": note})
    return rows


def read_tsv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    return [{k: (r.get(k) or "") for k in COLS} for r in csv.DictReader(lines, delimiter="\t")]


def write_tsv(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("# 已知错单（GUJI-684）：cell 放的字 应为 类别 来源 备注。kind=char/nonchar/review。生成：scripts/zhengli/known_errors.py build\n")
        w = csv.DictWriter(f, fieldnames=COLS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLS})


def merge(rows: list[dict]) -> list[dict]:
    """同一格多来源：人工来源（非 vision）优先，来源串起来。"""
    by: dict[str, dict] = {}
    for r in rows:
        if not CELL_RE.match(r["cell"]):
            continue
        cur = by.get(r["cell"])
        if cur is None:
            by[r["cell"]] = dict(r)
            continue
        if cur["source"].startswith("vision") and not r["source"].startswith("vision"):
            r = dict(r, source=r["source"] + "；" + cur["source"])
            by[r["cell"]] = r
        elif r["source"] not in cur["source"]:
            cur["source"] += "；" + r["source"]
    return sorted(by.values(), key=_sort_key)


def _sort_key(r: dict):
    m = CELL_RE.match(r["cell"])
    vol, page, col, slot = m.groups()
    return (vol, int(page), int(col), int(re.sub(r"[ab]$", "", slot)), slot)


def load_text(text_dir: Path) -> dict[str, dict[str, str]]:
    """{volNN: {页:列:格: 字}}；章号 NNN 对 volNN。"""
    out: dict[str, dict[str, str]] = {}
    for p in sorted(text_dir.glob("[0-9][0-9][0-9].char.json")):
        vol = f"vol{int(p.name[:3]):02d}"
        cells: dict[str, str] = {}
        for page in json.loads(p.read_text(encoding="utf-8")).get("pages", []):
            for col in page.get("columns", []):
                for c in col.get("cells", []):
                    if "a" in c:
                        cells[c["a"]] = c.get("c", "")
        out[vol] = cells
    return out


def classify(row: dict, text: dict[str, dict[str, str]]) -> tuple[str, str]:
    vol, rest = row["cell"].split(":", 1)
    if vol not in text:
        return "no_text", ""
    cur = text[vol].get(rest)
    if cur is None:
        return "missing", ""
    if row["kind"] == "nonchar":
        return ("still_wrong" if cur and cur not in ("□", "〓") else "fixed"), cur
    if row["shown"] and cur == row["shown"]:
        return "still_wrong", cur
    if row["kind"] == "char" and cur == row["expect"]:
        return "fixed", cur
    return "changed", cur


def cmd_build(a) -> int:
    rows: list[dict] = []
    for t in a.table or []:
        rows += parse_table(Path(t))
    for v in a.vision or []:
        rows += parse_vision(Path(v))
    for e in a.extra or []:
        rows += read_tsv(Path(e))
    rows = merge(rows)
    write_tsv(rows, Path(a.out))
    kinds = Counter(r["kind"] for r in rows)
    print(f"写出 {a.out}：{len(rows)} 格（{dict(kinds)}）")
    return 0


def cmd_check(a) -> int:
    rows = read_tsv(Path(a.list))
    text = load_text(Path(a.text_dir))
    res = []
    per = defaultdict(Counter)
    for r in rows:
        cat, cur = classify(r, text)
        res.append(dict(r, now=cur, result=cat))
        per[r["cell"].split(":")[0]][cat] += 1
    for vol in sorted(per):
        print(vol, dict(per[vol]))
    hard = [x for x in res if x["result"] == "still_wrong" and x["kind"] in ("char", "nonchar")]
    print(f"仍是错字（char/nonchar）：{len(hard)} 格")
    for x in hard:
        print(f"  {x['cell']}\t现「{x['now']}」\t应为「{x['expect'] or '非字'}」\t{x['source']}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 3 if (a.strict and hard) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("-o", "--out", required=True)
    b.add_argument("--table", action="append", help="基线错放格总表 md（可多个）")
    b.add_argument("--vision", action="append", help="看图结论.jsonl（可多个）")
    b.add_argument("--extra", action="append", help="手工补充的 TSV，列同输出（可多个）")
    c = sub.add_parser("check")
    c.add_argument("--list", required=True)
    c.add_argument("--text-dir", required=True, help="book-text 某书 default 目录（含 NNN.char.json）")
    c.add_argument("--json")
    c.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    return cmd_build(a) if a.cmd == "build" else cmd_check(a)


if __name__ == "__main__":
    sys.exit(main())
