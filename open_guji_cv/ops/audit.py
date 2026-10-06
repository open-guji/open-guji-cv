"""定版检查的两张清单（overview#413 C2；runbook S8、S10）：只读，出给人或会话逐格看的表。

`admitted`：放行错穷举——已放行、不是人裁、和证人不同的格。读 `guji collate` 的 JSON，
  按字位合并各证人，分「系统性」（码位、异体、用字账一类，`grade=systematic`）和「非系统」两档。
  **非系统那档才要逐格看图**；系统性的按类核一次即可。
`jys`：己/已/巳 全族清单——这三字在殿本里同形，只能按文意判（证人不是真值）。
  读 `guji export format` 的三份文件，给每格出前后文；同时写一份 muse 输入格式的 jsonl
  （`{id, left, right}`，**不含整理本与证人字**），量大时可交 muse 预判（并发 2–4）。
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

JYS = set("己已巳")


def latest_collation(reports_book: Path) -> Path | None:
    files = sorted(reports_book.glob("collation_*.json"))
    return files[-1] if files else None


def admitted(collation: Path) -> dict:
    d = json.loads(collation.read_text(encoding="utf-8"))
    cells: dict[str, dict] = {}
    for x in d.get("diffs", []):
        if not x.get("admit") or x.get("human"):
            continue
        c = cells.setdefault(x["id"], {"id": x["id"], "page": x["page"], "char": x.get("char"),
                                       "channel": x.get("channel"), "grades": set(), "kinds": set(),
                                       "witness": {}, "ctx": x.get("hyp_ctx")})
        c["grades"].add(x.get("grade") or "")
        c["kinds"].add(x.get("kind") or "")
        c["witness"][x.get("witness")] = x.get("ref")
    rows = []
    for c in cells.values():
        systematic = c["grades"] == {"systematic"}
        variant_only = all(k.startswith("variant.") for k in c["kinds"])
        tier = "systematic" if systematic else "variant" if variant_only else "real"
        rows.append({**c, "grades": sorted(c["grades"]), "kinds": sorted(c["kinds"]),
                     "systematic": systematic, "tier": tier})
    order = {"real": 0, "variant": 1, "systematic": 2}
    rows.sort(key=lambda r: (order[r["tier"]], r["page"], r["id"]))
    non = [r for r in rows if r["tier"] == "real"]
    return {"collation": str(collation), "book": d.get("book"), "n": len(rows),
            "n_systematic": sum(1 for r in rows if r["tier"] == "systematic"),
            "n_variant": sum(1 for r in rows if r["tier"] == "variant"),
            "n_non_systematic": len(non),
            "by_channel": dict(Counter(r["channel"] for r in non).most_common()),
            "by_kind": dict(Counter(k for r in non for k in r["kinds"]).most_common()),
            "rows": rows}


def admitted_md(res: dict) -> str:
    out = [f"# {res['book']} 放行错穷举（已放行 ∧ 非人裁 ∧ 与证人不同）", "",
           f"- 来源：`{Path(res['collation']).name}`",
           f"- 共 {res['n']} 格：**认字差异 {res['n_non_systematic']}（逐格看图）**；异体差异 {res['n_variant']}（按用字账核）；系统性 {res['n_systematic']}（按类核）",
           f"- 认字差异按通道：{res['by_channel']}", f"- 认字差异按差异类：{res['by_kind']}", "",
           "## 认字差异（逐格看图）", "",
           "| 字位 | 放行字 | 证人 | 通道 | 差异类 | 上下文 | 看图结论 |", "|---|---|---|---|---|---|---|"]
    for r in res["rows"]:
        if r["tier"] != "real":
            continue
        wit = "；".join(f"{k}:{v}" for k, v in r["witness"].items())
        out.append(f"| `{r['id']}` | {r['char']} | {wit} | {r['channel']} | {'、'.join(r['kinds'])} | {r['ctx'] or ''} | |")
    for tier, title in (("variant", "异体差异（按用字账核：刻本原字照录，证人改成了通行字就不算错）"),
                        ("systematic", "系统性（码位、用字账一类，按类核一次）")):
        sel = [r for r in res["rows"] if r["tier"] == tier]
        if not sel:
            continue
        out += ["", f"## {title}", ""]
        groups: dict[tuple, list] = defaultdict(list)
        for r in sel:
            groups[(r["char"], tuple(sorted(set(r["witness"].values()), key=str)))].append(r["id"])
        for (ch, refs), ids in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            out.append(f"- {ch} ← 证人 {'/'.join(x or '∅' for x in refs)}：{len(ids)} 格（如 `{ids[0]}`）")
    return "\n".join(out) + "\n"


def _load_export(export_dir: Path, chapter: str | None):
    from ..formats.guji_format import _plain_chars
    lines = sorted(export_dir.glob(f"{chapter}.lines.md" if chapter else "*.lines.md"))
    if len(lines) != 1:
        raise SystemExit(f"{export_dir} 下找到 {len(lines)} 个 lines.md，应为 1 个（用 --chapter 指定）")
    stem = lines[0].name[: -len(".lines.md")]
    chars = _plain_chars(lines[0].read_text(encoding="utf-8"))
    pages = json.loads((export_dir / f"{stem}.pages.json").read_text(encoding="utf-8"))
    proof_p = export_dir / f"{stem}.proof.json"
    proof = {c["a"]: c for c in json.loads(proof_p.read_text(encoding="utf-8"))["cells"]} if proof_p.exists() else {}
    return chars, pages, proof


def jys(export_dir: Path, chapter: str | None = None, width: int = 20, book: str = "") -> dict:
    chars, pages, proof = _load_export(export_dir, chapter)
    rows = []
    for p in pages["pages"]:
        for c in p["cells"]:
            if c.get("c") in JYS and isinstance(c.get("o"), int):
                o = c["o"]
                pr = proof.get(c["a"], {})
                rows.append({"id": f"{book}:{c['a']}" if book else c["a"], "char": c["c"],
                             "method": pr.get("method"), "review": pr.get("review"),
                             "left": "".join(chars[max(0, o - width):o]),
                             "right": "".join(chars[o + 1:o + 1 + width])})
    return {"n": len(rows), "by_char": dict(Counter(r["char"] for r in rows)),
            "n_human": sum(1 for r in rows if r["review"] == "human"), "rows": rows}


def jys_md(res: dict, book: str) -> str:
    out = [f"# {book} 己/已/巳 全族清单（按文意逐格判；证人不是真值）", "",
           f"- 共 {res['n']} 格：{res['by_char']}；其中人裁过 {res['n_human']} 格",
           "- 判法：干支用「己」；「並已」「時已」「而已」「既已」一类用「已」；地支、時辰用「巳」；判不了的进请审单。", "",
           "| 字位 | 现字 | 来路 | 上文 | 下文 | 文意判 |", "|---|---|---|---|---|---|"]
    for r in res["rows"]:
        out.append(f"| `{r['id']}` | {r['char']} | {r['review'] or ''} | {r['left']} | {r['right']} | |")
    return "\n".join(out) + "\n"


def jys_muse_jsonl(res: dict) -> str:
    """muse 输入（格式同 overview 四庫vol03/muse-己已巳试点/input.jsonl）：只给刻本前后文，不给现字、证人、整理本。"""
    return "".join(json.dumps({"id": r["id"], "left": r["left"], "right": r["right"]}, ensure_ascii=False) + "\n"
                   for r in res["rows"] if r["review"] != "human")


def review_count(events_dir: Path, book: str, since: str, expect: list[str] | None = None) -> dict:
    """用户审完当场核数（runbook S12）：`since`（ISO 时间，如 2026-10-06T08:00）之后、本册、人写的事件。

    报：事件数、涉及字位数、按裁决类别计数、同一字位裁了多次的、**没带锚点的**（锚点缺了，
    切分一变这条裁决就失效，#403 的教训）；给了 `expect`（请审单上的字位）再报漏审与单外多审。
    """
    evs = []
    for f in sorted(events_dir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = e.get("target") or {}
            if t.get("book") != book or (e.get("ts") or "") < since or e.get("actor") not in ("user", None):
                continue
            evs.append((f.name, e))
    keys = Counter((e.get("target") or {}).get("key") for _, e in evs)
    kinds = Counter(((e.get("payload") or {}).get("v") or e.get("kind")) for _, e in evs)
    no_anchor = sorted({(e.get("target") or {}).get("key") for _, e in evs if not (e.get("target") or {}).get("anchor")})
    res = {"book": book, "since": since, "n_events": len(evs), "n_cells": len(keys),
           "by_kind": dict(kinds.most_common()), "batches": dict(Counter(n for n, _ in evs)),
           "repeated": sorted(k for k, n in keys.items() if n > 1), "no_anchor": no_anchor}
    if expect is not None:
        exp = set(expect)
        res["missing"] = sorted(exp - set(keys))
        res["extra"] = sorted(set(keys) - exp)
    return res
