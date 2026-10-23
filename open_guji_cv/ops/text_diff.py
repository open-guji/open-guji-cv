# -*- coding: utf-8 -*-
"""发布文本 vs 冻结产物导出：两份 `NNN.char.json` 逐格比（只读；1.0 发布标准 G2，GUJI-736）。

用户 10-20 定「不在 book-text 里直接改字」：1.0 的文本必须等于冻结快照导出。这里只比两份 char，
不管 char 是怎么来的——冻结那份由导出器从冻结产物出：

    python scripts/export_guji_format.py --products <冻结快照的 products 根> --book vol01 --chapter 001 \\
        --meta <meta> --out <临时目录> --format char-cord --text-version <现行版本>

然后 `guji char-diff <book-text>/…/001.char.json <临时目录>/001.char.json`，或在 `guji exit-check` 上给
`--frozen-char <临时目录>/001.char.json`（E9）。

逐格比的字段：`c`（字）、`lacuna`、`guess_c`、`lane`（夹注 a/b 行等版式）。格位只在一边的另列（补格、拆格、删格）。
差异＝0 才算过。册 001 第一次手比（2026-10-23，ai-team `domain/CV/质检/册001-003-1.0重检-2026-10-23.md`）
比出 345 格，其中 98 格是没有人裁事件的手改。
"""
from __future__ import annotations

import json
from pathlib import Path

FIELDS = ("c", "lacuna", "guess_c", "lane")


def cells(char_doc: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for page in char_doc.get("pages", []):
        for col in page.get("columns", []):
            for c in col.get("cells", []):
                out[c["a"]] = c
    return out


def _key(a: str) -> tuple:
    parts = a.split(":")
    try:
        return (int(parts[0]), int(parts[1]), int("".join(ch for ch in parts[2] if ch in "-0123456789") or 0), parts[2])
    except (IndexError, ValueError):
        return (10 ** 9, 0, 0, a)


def diff(text: dict, frozen: dict) -> dict:
    """text＝发布（候选）文本，frozen＝冻结导出。返回 {only_text, only_frozen, changed:[{a, field: (frozen, text)}], n}。"""
    t, f = cells(text), cells(frozen)
    only_text = sorted(set(t) - set(f), key=_key)
    only_frozen = sorted(set(f) - set(t), key=_key)
    changed = []
    for a in sorted(set(t) & set(f), key=_key):
        d = {k: (f[a].get(k), t[a].get(k)) for k in FIELDS if f[a].get(k) != t[a].get(k)}
        if d:
            changed.append({"a": a, **d})
    return {"only_text": only_text, "only_frozen": only_frozen, "changed": changed,
            "n": len(only_text) + len(only_frozen) + len(changed)}


def summary(res: dict, limit: int = 8) -> str:
    if not res["n"]:
        return "逐格相同"
    parts = []
    if res["changed"]:
        ex = "、".join(f"{d['a']} {d['c'][0]}→{d['c'][1]}" if "c" in d else d["a"] for d in res["changed"][:limit])
        parts.append(f"{len(res['changed'])} 格不同（{ex}）")
    if res["only_text"]:
        parts.append(f"{len(res['only_text'])} 格只在文本（{'、'.join(res['only_text'][:limit])}）")
    if res["only_frozen"]:
        parts.append(f"{len(res['only_frozen'])} 格只在冻结导出（{'、'.join(res['only_frozen'][:limit])}）")
    return "；".join(parts)


def write_tsv(res: dict, text: dict, frozen: dict, path: Path) -> None:
    t, f = cells(text), cells(frozen)
    rows = ["格\t类\t冻结导出\t文本\t字段"]
    for d in res["changed"]:
        for k in FIELDS:
            if k in d:
                rows.append(f"{d['a']}\t不同\t{d[k][0]}\t{d[k][1]}\t{k}")
    rows += [f"{a}\t只在文本\t\t{t[a].get('c')}\t" for a in res["only_text"]]
    rows += [f"{a}\t只在冻结导出\t{f[a].get('c')}\t\t" for a in res["only_frozen"]]
    Path(path).write_text("\n".join(rows) + "\n", encoding="utf-8")


def load(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
