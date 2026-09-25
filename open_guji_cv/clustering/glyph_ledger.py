# -*- coding: utf-8 -*-
"""字形库总账：一本书「收了哪些字形」的只读口径 + 字头维护。

## 为什么要单列一个模块

`GlyphDB.stats()` 只数表行数。可用户要问的是「这本书收了哪些字」，而库里
一本书的刻例天然分在好几个 `edition_tag` 里：

- 机器准入（整理本对齐/库匹配/上下文）按实例 id 前缀落 `vol01` / `bxgb`；
- 人裁（`glyphdb_admit`）一律加 `v2:` 前缀落 `v2`——那是**实例 id 命名空间**
  （v1 的 `idx` 与 v2 的 `slot` 长得一样但不是同一格，见 consumers.glyphdb_admit），
  不是另一套书；
- 字体渲染落 `font:*`。

一个 glyph.db 只属于一个工作区（一本书），所以**本书套 = 库里全部非字体来源**。
这里在读的一侧把它们并成一套（按字聚合、按来路细分），不去改写 `glyphs` 的
`(edition_tag, char)` 键——匹配器对刻本链本来就不按 edition 过滤
（`seeding.load_matcher_from_db(edition=None)`），并套只影响「怎么数」，
不影响「怎么配」。真要在 schema 层并，得先做 v1→v2 的实例重键（B2），
那是另一件事。

CLI `glyph-db stats`、控制台字形库页、体检共用这一份口径，别各算各的。

## 影子副本

同一格可能在库里有两份：播种（`seed_witness`，id = `<book>:p:c:s`）与人裁
（id = `v2:<book>:p:c:s`）。两者都是 v2 的 slot 坐标、指的是同一格。只有来源的
`pipeline_version = 'v1'`（四庫 vol01，idx 坐标）时同名 id 才**不是**同一格。
`shadow_duplicates()` 找出前者；人裁到来时 `glyphdb_admit` 会撤掉机器那份。
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

#: CJK 部首补充区起点。semantic/reading 低于它的单字（拉丁字母、数字）都是
#: 输入法没转出汉字的脏值（2026-09-04 前的事件里有「l」「m」这类）。
_CJK_MIN = 0x2E80


def _valid_char(s: str | None) -> bool:
    return bool(s) and len(s) == 1 and ord(s) >= _CJK_MIN


def connect_ro(db_path: str | Path) -> sqlite3.Connection:
    """只读打开，别跟跑批抢写锁。"""
    return sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)


def _font_editions(c: sqlite3.Connection) -> set[str]:
    return {r[0] for r in c.execute(
        "SELECT edition_tag FROM sources WHERE kind='font'")} | {
        r[0] for r in c.execute(
            "SELECT DISTINCT edition_tag FROM glyphs WHERE edition_tag LIKE 'font:%'")}


def _v1_sources(c: sqlite3.Connection) -> set[str]:
    return {r[0] for r in c.execute(
        "SELECT source_id FROM sources WHERE pipeline_version='v1'")}


def cell_key(instance_id: str, v1_sources: set[str] = frozenset()) -> str:
    """实例 id → 格键。`v2:<x>` 与 `<x>` 是同一格，除非 `<x>` 属于 v1 来源。"""
    if instance_id.startswith("v2:"):
        return instance_id[3:]
    if instance_id.split(":", 1)[0] in v1_sources:
        return "v1:" + instance_id
    return instance_id


def _book_rows(c: sqlite3.Connection) -> list[tuple]:
    """本书套全部刻例：(char, instance_id, edition, provenance, semantic)。"""
    fe = _font_editions(c)
    rows = c.execute(
        "SELECT g.char, e.instance_id, g.edition_tag, a.provenance, i.semantic "
        "FROM exemplars e JOIN glyphs g ON g.glyph_id = e.glyph_id "
        "LEFT JOIN admissions a ON a.instance_id = e.instance_id "
        "LEFT JOIN instances i ON i.instance_id = e.instance_id").fetchall()
    return [r for r in rows if r[2] not in fe]


def _prov_class(p: str | None) -> str:
    """来路归类：human_stale_* 这类历史标记并回 human。"""
    if not p:
        return "unknown"
    return "human" if p.startswith("human") else p


def shadow_duplicates(c: sqlite3.Connection) -> list[tuple[str, str]]:
    """同一格的两份刻例：[(机器那份 id, 人裁那份 id)]。"""
    v1 = _v1_sources(c)
    out = []
    for (iid,) in c.execute(
            "SELECT instance_id FROM exemplars WHERE instance_id LIKE 'v2:%'"):
        twin = iid[3:]
        if twin.split(":", 1)[0] in v1:
            continue
        if c.execute("SELECT 1 FROM exemplars WHERE instance_id=?", (twin,)).fetchone():
            out.append((twin, iid))
    return out


def store_drift(c: sqlite3.Connection, store_dir: str | Path | None) -> dict:
    """db 与真源 store 的刻例数差。db 不进 git，差额就是只在本机的数据。"""
    fe = _font_editions(c)
    n_db = sum(1 for r in c.execute(
        "SELECT g.edition_tag FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id")
        if r[0] not in fe)
    out = {"db_exemplars": n_db, "store": str(store_dir) if store_dir else None}
    p = Path(store_dir) / "exemplars.jsonl" if store_dir else None
    if not p or not p.exists():
        out.update(store_exemplars=None, ok=False,
                   message="没有 glyph_store 真源：db 不进 git，这份库只在本机")
        return out
    with open(p, encoding="utf-8") as f:
        n_store = sum(1 for l in f if l.strip())
    out.update(store_exemplars=n_store, ok=n_store == n_db,
               message=None if n_store == n_db else
               f"store 与 db 差 {n_db - n_store:+d} 例，先 `glyph-db export` 再提交")
    return out


def head_anomalies(c: sqlite3.Connection) -> list[dict]:
    """字头行的脏数据：semantic 不是汉字、unicode_cp 缺失或与字不符。"""
    out = []
    for gid, ed, ch, sem, cp in c.execute(
            "SELECT glyph_id, edition_tag, char, semantic, unicode_cp FROM glyphs "
            "WHERE edition_tag NOT LIKE 'font:%'"):
        why = []
        if sem is not None and not _valid_char(sem) and len(sem) <= 1:
            why.append("semantic_not_cjk")
        if len(ch) == 1 and cp != ord(ch):
            why.append("unicode_cp_missing" if cp is None else "unicode_cp_mismatch")
        if why:
            out.append({"glyph_id": gid, "edition": ed, "char": ch,
                        "semantic": sem, "unicode_cp": cp, "issues": why})
    return out


def library_summary(db_path: str | Path, store_dir: str | Path | None = None) -> dict:
    """一本书字形库的总账（控制台字形库页 / `glyph-db stats` 共用）。"""
    c = connect_ro(db_path)
    try:
        fe = _font_editions(c)
        v1 = _v1_sources(c)
        sources = [dict(zip(("source_id", "edition_tag", "kind", "title", "volume",
                             "pipeline_version"), r)) for r in c.execute(
            "SELECT source_id, edition_tag, kind, title, volume, pipeline_version "
            "FROM sources ORDER BY source_id")]
        editions = []
        for ed, n_rows, n_stable, n_ex in c.execute(
                "SELECT g.edition_tag, COUNT(*), SUM(g.status='stable'), "
                "  (SELECT COUNT(*) FROM exemplars e JOIN glyphs g2 "
                "     ON g2.glyph_id=e.glyph_id WHERE g2.edition_tag=g.edition_tag) "
                "FROM glyphs g GROUP BY g.edition_tag ORDER BY g.edition_tag"):
            editions.append({"edition": ed, "kind": "font" if ed in fe else "woodblock",
                             "chars": n_rows, "stable": n_stable or 0, "exemplars": n_ex})

        rows = _book_rows(c)
        per_char: dict[str, dict] = defaultdict(lambda: {"cells": set(), "prov": Counter(),
                                                        "editions": set()})
        prov = Counter()
        cells: set[str] = set()
        for ch, iid, ed, p, _sem in rows:
            k = cell_key(iid, v1)
            d = per_char[ch]
            d["cells"].add(k)
            d["prov"][_prov_class(p)] += 1
            d["editions"].add(ed)
            prov[_prov_class(p)] += 1
            cells.add(k)
        n_chars = len(per_char)
        singles = sum(1 for d in per_char.values() if len(d["cells"]) == 1)
        human_chars = sum(1 for d in per_char.values() if d["prov"].get("human"))
        split = sum(1 for d in per_char.values() if len(d["editions"]) > 1)
        font_chars = {}
        for ed in sorted(fe):
            have = {r[0] for r in c.execute(
                "SELECT char FROM glyphs WHERE edition_tag=?", (ed,))}
            if have:
                font_chars[ed] = {"chars": len(have),
                                  "book_chars_not_in_font": sum(
                                      1 for ch in per_char if ch not in have)}
        return {
            "db": str(db_path),
            "sources": sources,
            "editions": editions,
            "book": {
                "chars": n_chars,
                "exemplars": len(rows),
                "cells": len(cells),
                "shadow_duplicates": len(rows) - len(cells),
                "provenance": dict(prov.most_common()),
                "human_share": round(prov.get("human", 0) / len(rows), 4) if rows else 0,
                "chars_with_human": human_chars,
                "singleton_chars": singles,
                "chars_split_across_editions": split,
            },
            "fonts": font_chars,
            "store": store_drift(c, store_dir),
            "head_anomalies": len(head_anomalies(c)),
        }
    finally:
        c.close()


def char_table(db_path: str | Path) -> list[dict]:
    """本书套按字一行：刻例数（按格去重）、来路分布、是否在字体里。"""
    c = connect_ro(db_path)
    try:
        v1 = _v1_sources(c)
        fe = _font_editions(c)
        in_font = {r[0] for r in c.execute(
            "SELECT DISTINCT char FROM glyphs WHERE edition_tag IN (%s)"
            % ",".join("?" * len(fe)), tuple(fe))} if fe else set()
        heads = defaultdict(dict)
        for ed, ch, sem, cp in c.execute(
                "SELECT edition_tag, char, semantic, unicode_cp FROM glyphs"):
            if ed not in fe:
                heads[ch][ed] = (sem, cp)
        per = defaultdict(lambda: {"cells": set(), "prov": Counter(), "semantic": Counter()})
        for ch, iid, ed, p, sem in _book_rows(c):
            d = per[ch]
            d["cells"].add(cell_key(iid, v1))
            d["prov"][_prov_class(p)] += 1
            if sem:
                d["semantic"][sem] += 1
        out = []
        for ch, d in per.items():
            sem = d["semantic"].most_common(1)[0][0] if d["semantic"] else ch
            out.append({
                "char": ch,
                "cp": ord(ch) if len(ch) == 1 else None,
                "n": len(d["cells"]),
                "prov": dict(d["prov"]),
                "semantic": sem,
                "editions": sorted(heads.get(ch, {})),
                "in_font": ch in in_font if fe else None,
            })
        out.sort(key=lambda r: (-r["n"], r["char"]))
        return out
    finally:
        c.close()


def char_detail(db_path: str | Path, char: str) -> dict:
    """一个字在本书套里的全部刻例（按来路）＋ 字体里有没有这个字。"""
    c = connect_ro(db_path)
    try:
        v1 = _v1_sources(c)
        fe = _font_editions(c)
        ex = []
        seen: set[str] = set()
        for iid, ed, p, sem, page, col, idx, ev, at in c.execute(
                "SELECT e.instance_id, g.edition_tag, a.provenance, i.semantic, "
                "  i.page, i.col, i.idx, a.evidence, a.admitted_at "
                "FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id "
                "JOIN instances i ON i.instance_id=e.instance_id "
                "LEFT JOIN admissions a ON a.instance_id=e.instance_id "
                "WHERE g.char=? ORDER BY e.instance_id", (char,)):
            if ed in fe:
                continue
            k = cell_key(iid, v1)
            try:
                evd = json.loads(ev) if ev else {}
            except ValueError:
                evd = {}
            ex.append({"instance_id": iid, "cell": k, "edition": ed,
                       "provenance": _prov_class(p), "provenance_raw": p,
                       "semantic": sem, "page": page, "col": col, "idx": idx,
                       "duplicate": k in seen, "admitted_at": at,
                       "event": evd.get("event") if isinstance(evd, dict) else None})
            seen.add(k)
        fonts = []
        for ed in sorted(fe):
            r = c.execute(
                "SELECT e.instance_id FROM glyphs g JOIN exemplars e "
                "ON e.glyph_id=g.glyph_id WHERE g.edition_tag=? AND g.char=? LIMIT 1",
                (ed, char)).fetchone()
            if r:
                fonts.append({"edition": ed, "instance_id": r[0]})
        heads = [dict(zip(("edition", "semantic", "unicode_cp", "status", "n_confirmed"), r))
                 for r in c.execute(
                     "SELECT edition_tag, semantic, unicode_cp, status, n_confirmed "
                     "FROM glyphs WHERE char=? AND edition_tag NOT LIKE 'font:%'", (char,))]
        return {"char": char, "cp": ord(char) if len(char) == 1 else None,
                "heads": heads, "exemplars": ex, "fonts": fonts}
    finally:
        c.close()


# ── 维护（写库）────────────────────────────────────────


def repair_glyph_heads(db_path: str | Path, dry_run: bool = True) -> dict:
    """修字头行的脏数据（`head_anomalies` 报的那些）。

    - `unicode_cp`：直接由 `char` 算；
    - `semantic` 不是汉字：取该字头下刻例 `instances.semantic` 的多数值
      （实例层 2026-09-04 起有输入法护栏，字头层是首次插入时冻结的旧值）；
      刻例里也没有像样的值就退回字头本身。

    `semantic` 是汉字但与实例不一致的（如 曰→日）不在这里自动改——那是读法
    判断，交给体检出卡由人裁。
    """
    c = sqlite3.connect(str(db_path))
    fixes = []
    try:
        for a in head_anomalies(c):
            upd = {}
            if "unicode_cp_missing" in a["issues"] or "unicode_cp_mismatch" in a["issues"]:
                upd["unicode_cp"] = ord(a["char"])
            if "semantic_not_cjk" in a["issues"]:
                votes = Counter(r[0] for r in c.execute(
                    "SELECT i.semantic FROM exemplars e JOIN instances i "
                    "ON i.instance_id=e.instance_id WHERE e.glyph_id=?", (a["glyph_id"],))
                    if _valid_char(r[0]))
                upd["semantic"] = votes.most_common(1)[0][0] if votes else a["char"]
            fixes.append({**a, "set": upd})
            if not dry_run and upd:
                c.execute("UPDATE glyphs SET %s WHERE glyph_id=?"
                          % ",".join(f"{k}=?" for k in upd),
                          (*upd.values(), a["glyph_id"]))
        if not dry_run:
            c.commit()
    finally:
        c.close()
    return {"dry_run": dry_run, "n": len(fixes), "fixes": fixes}


def semantic_disagreements(db_path: str | Path) -> list[dict]:
    """字头 semantic 是汉字、却与刻例多数读法不同的（如 曰 字头记成 日）。"""
    c = connect_ro(db_path)
    try:
        out = []
        for gid, ed, ch, sem in c.execute(
                "SELECT glyph_id, edition_tag, char, semantic FROM glyphs "
                "WHERE edition_tag NOT LIKE 'font:%' AND semantic IS NOT NULL"):
            if not _valid_char(sem):
                continue
            votes = Counter(r[0] for r in c.execute(
                "SELECT i.semantic FROM exemplars e JOIN instances i "
                "ON i.instance_id=e.instance_id WHERE e.glyph_id=?", (gid,))
                if _valid_char(r[0]))
            if votes and sem not in votes:
                out.append({"glyph_id": gid, "edition": ed, "char": ch,
                            "head_semantic": sem, "instance_semantic": dict(votes)})
        return out
    finally:
        c.close()


def evict_shadow_duplicates(db_path: str | Path, dry_run: bool = True) -> dict:
    """撤掉同一格的机器副本（人裁那份留下）。"""
    from .glyph_db import GlyphDB
    from .audit import evict_instance
    c = connect_ro(db_path)
    try:
        pairs = shadow_duplicates(c)
        prov = {iid: p for iid, p in c.execute("SELECT instance_id, provenance FROM admissions")}
    finally:
        c.close()
    todo = [(m, h) for m, h in pairs if not _prov_class(prov.get(m)).startswith("human")]
    if not dry_run and todo:
        db = GlyphDB(str(db_path))
        try:
            for m, _h in todo:
                evict_instance(db, m)
            db.conn.commit()
        finally:
            db.close()
    return {"dry_run": dry_run, "pairs": len(pairs), "evicted": len(todo),
            "ids": [m for m, _ in todo]}
