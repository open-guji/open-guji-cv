# -*- coding: utf-8 -*-
"""书级字形库增量回收：人裁事件 → 本书自有库（H 道，2026-09-27 全唐文 #64 起）。**可重复跑、幂等**。

    PYTHONPATH=. python scripts/book_lib_sync.py -w <书工作区> --books v006,v007 \
        [--import-events <别处的 feedback/events 目录> ...] [--cap 30] [--apply]

新书（全唐文）的库口径（用户 09-27 22:20Z）：**只收本书刻例**，借库只用于冷启动；人审确认后回流进本书库，
库随审随长。人裁有两条来路，本脚本把两条都收进同一个工作区的库：

1. **控制台当场消费**：服务器校对平台上点的格，`POST /api/events` 后 `glyphdb_admit` 当场进库。
   这条路不经本脚本；本脚本只**补**当场消费失败的（字块缓存缺、库锁）——它们在
   `feedback/consumed/glyphdb_admit.jsonl` 里没有记账，这里重跑一次。
2. **别处来的事件**（`--import-events`，可多个）：审查页收回的 jsonl 导成的事件（H 道 a4_import）、
   或服务器 `glyph_store_sync` 定时器推到 ws main 的 `<工作区>/feedback/events/`。按事件原样追加进本工作区
   （`EventLog.append`：同批次同序号同内容跳过 → 重复导入不灌重；乱码/非单字闸；人裁单写者锁）。

然后对**本轮新消费**的 `confirm` 事件过进库闸（控制台当场消费的那部分已经进了，只体检不拦）：
- 字形不是单个汉字 → 不进（`glyphdb_admit` 自己也拦）；
- 事件带 `no_glyph_lib=true` → 不进（审查页/导入脚本标的）；
- 本书 `codepoints` 之外的**简化字**（opencc s2t 会变的字，如 `闻`）→ 不进、列出待定（清刻本多半是输入法打出来的）；
- 整理本对齐（锚定页 `align_ref` equal/replace）给的字与人裁字不同、又不是异体/码位关系 → 不进、列出；
- 该字在本书库里已有 ≥ `--cap` 个刻例 → 不进（R #86：库塞满反而略降，混进簇里的错格随 K 增多）。
不进的也记账（`consumed/glyphdb_admit.jsonl` 带 `gated:` 原因），下次不再重试；要放行就改 `--cap` 或
追加一条新的确认事件。最后 `export_store` 导出本书真源（`output/glyph_store`）。

不带 `--apply` 只报告（会导入哪些事件、哪些格进库、各闸拦了多少），什么都不写。
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _simplified_only(ch: str) -> str | None:
    try:
        import opencc
    except ImportError:          # 没装 opencc 就不做这道闸
        return None
    t = opencc.OpenCC("s2t").convert(ch)
    return t if t != ch else None


def _align_chars(ws: Path, books: list[str]) -> dict[str, str]:
    out = {}
    from open_guji_cv.core.workspace import products_root
    root = products_root()
    for b in books:
        for f in sorted((root / b / "align_ref").glob("p*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            ar = d[next(iter(d))]
            if not ar.get("anchored"):
                continue
            for c in ar.get("chars") or []:
                if c.get("align_op") in ("equal", "replace") and c.get("align_char"):
                    out[c["id"]] = c["align_char"]
    return out


def _related(a: str, b: str) -> bool:
    try:
        from open_guji_cv.clustering.confusable import variant_related  # type: ignore
        return bool(variant_related(a, b))
    except Exception:  # noqa: BLE001
        pass
    try:
        vj = json.loads((REPO / "config" / "variants" / "variants.json").read_text(encoding="utf-8"))
        P, D = vj.get("pairs", {}), vj.get("directed", {})
        return (b in (P.get(a) or {})) or (a in (P.get(b) or {})) or (b in (D.get(a) or {})) or (a in (D.get(b) or {}))
    except Exception:  # noqa: BLE001
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-w", "--workspace", required=True, help="书工作区（books/ products/ feedback/ output/）")
    ap.add_argument("--books", required=True, help="逗号分隔，如 v006,v007")
    ap.add_argument("--import-events", action="append", default=[],
                    help="别处的 feedback/events 目录（或单个 .jsonl），只取指向 --books 的事件")
    ap.add_argument("--cap", type=int, default=30, help="每字进库上限（本书 edition 内）")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default=None, help="报告 JSON 写到这里")
    a = ap.parse_args(argv)

    ws = Path(a.workspace).expanduser().resolve()
    books = [b.strip() for b in a.books.split(",") if b.strip()]
    from open_guji_cv.core.workspace import set_workspace_override, glyph_db_path
    set_workspace_override(str(ws))
    from open_guji_cv.core.book import load_book
    from open_guji_cv.feedback.events import Event, EventLog

    log = EventLog(ws / "feedback")
    rep: dict = {"workspace": str(ws), "books": books, "apply": a.apply}

    # ── 1. 导入别处来的事件 ─────────────────────────────────────────
    incoming: list[Event] = []
    for src in a.import_events:
        p = Path(src).expanduser()
        files = [p] if p.is_file() else sorted(p.glob("*.jsonl"))
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                e = Event.model_validate(json.loads(line))
                bk = e.target.book or e.target.key.split(":")[0]
                if bk in books:
                    incoming.append(e)
    have = {(e.batch, e.seq): e for e in log.iter_all()}
    fresh = [e for e in incoming if (e.batch, e.seq) not in have]
    rep["import"] = {"seen": len(incoming), "new": len(fresh),
                     "by_batch": dict(collections.Counter(e.batch for e in fresh))}
    if a.apply and fresh:
        rep["import"]["appended"] = log.append(fresh)

    # ── 2. 待消费的确认事件 → 进库闸 ────────────────────────────────
    done = log.consumed_ids("glyphdb_admit")
    evs = sorted((e for e in (log.iter_all() if a.apply else list(have.values()) + fresh)
                  if e.id not in done and e.kind == "confirm"
                  and (e.payload.get("v") or "confirm") == "confirm"
                  and (e.target.book or e.target.key.split(":")[0]) in books),
                 key=lambda e: (e.ts, e.order))
    # 同一格多条：只看时间最新的那条（旧的照记账，不再进库）
    latest: dict[str, Event] = {}
    for e in evs:
        latest[e.target.key] = e
    superseded = [e for e in evs if latest[e.target.key] is not e]

    import sqlite3
    dbp = glyph_db_path()
    counts: collections.Counter = collections.Counter()
    in_lib: set[str] = set()
    edition = None
    if dbp.exists():
        with sqlite3.connect(f"file:{dbp}?mode=ro", uri=True) as c:
            r = c.execute("SELECT value FROM meta WHERE key='book_edition'").fetchone()
            edition = r[0] if r else None
            q = ("SELECT g.char, e.instance_id FROM exemplars e JOIN glyphs g USING(glyph_id)"
                 + (" WHERE g.edition_tag=?" if edition else ""))
            for ch, iid in c.execute(q, (edition,) if edition else ()):
                counts[ch] += 1
                in_lib.add(iid)
    rep["library_before"] = {"db": str(dbp), "edition": edition, "exemplars": sum(counts.values()),
                             "chars": len(counts)}
    spec = {b: load_book(b) for b in books}
    align = _align_chars(ws, books)
    admit, gated = [], {}
    for e in latest.values():
        ch = e.payload.get("shape") or e.payload.get("char") or ""
        bk = e.target.book or e.target.key.split(":")[0]
        canon = spec[bk].canonical_char(ch) if ch else ch
        a_ch = align.get(e.target.key)
        again = f"v2:{e.target.key}" in in_lib           # 改判已在库的格：不拦，让 glyphdb_admit 撤旧进新
        why = None
        if e.payload.get("no_glyph_lib"):
            why = "事件标了 no_glyph_lib"
        elif len(ch) != 1 or ord(ch) < 0x2E80:
            why = f"字形 {ch!r} 不是单个汉字"
        elif canon == ch and (t := _simplified_only(ch)) and t not in spec[bk].codepoints:
            why = f"简化字，待定是否为「{t}」"
        elif a_ch and not spec[bk].codepoint_equal(a_ch, ch) and not _related(a_ch, ch):
            why = f"整理本对齐字「{a_ch}」≠人裁「{ch}」"
        elif not again and counts[ch] >= a.cap:
            why = f"本书库「{ch}」已有 {counts[ch]} 例（上限 {a.cap}）"
        if why:
            gated[e.id] = {"key": e.target.key, "char": ch, "why": why}
        else:
            admit.append(e)
            if not again:
                counts[ch] += 1
    rep["admit"] = {"pending": len(evs), "superseded": len(superseded), "to_admit": len(admit),
                    "gated": len(gated),
                    "gated_by_reason": dict(collections.Counter(v["why"].split("「")[0].split("（")[0].split(" ")[0]
                                                               for v in gated.values()))}
    rep["gated"] = list(gated.values())

    if a.apply:
        from open_guji_cv.core.book import load_book as _lb  # noqa: F401
        from open_guji_cv.core.step import RunContext
        from open_guji_cv.feedback.consumers import glyphdb_admit
        from open_guji_cv.products.cache import ImageCache
        from open_guji_cv.products.store import ProductStore
        cache = ImageCache()
        miss = 0
        for e in admit:                                     # 字块缓存缺的先现场渲染
            _b, pg, col, slot = e.target.key.split(":")
            ck = f"p{int(pg):04d}c{int(col):02d}s{int(slot)}"
            if cache.get(_b, "char_patch", ck) is None:
                try:
                    RunContext(spec[_b], ProductStore(), cache, log=lambda *_: None).image("char_patch", ck)
                except Exception:  # noqa: BLE001
                    miss += 1
        res = glyphdb_admit([(e, None) for e in admit], db_path=str(dbp))
        rep["admit"].update(added=res.added, updated=res.updated, errors=res.errors[:20], render_miss=miss)
        bad_keys = {":".join(x.split(":")[:4]) for x in res.errors}   # 错误信息以格键开头
        ok_ids = {e.id for e in admit if e.target.key not in bad_keys}
        log.mark_consumed("glyphdb_admit", [e for e in admit if e.id in ok_ids] + superseded,
                          note="book_lib_sync")
        by_id = {e.id: e for e in evs}
        for eid, g in gated.items():
            log.mark_consumed("glyphdb_admit", [by_id[eid]], note=f"book_lib_sync gated: {g['why']}")
        from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
        db = GlyphDB(dbp)
        rep["export"] = export_store(db, ws / "output" / "glyph_store")
        db.close()
    hist = collections.Counter(min(n, 10) for n in counts.values())
    rep["library_after"] = {"exemplars": sum(counts.values()), "chars": len(counts),
                            "chars_ge3": sum(n >= 3 for n in counts.values()),
                            "per_char_hist(10=≥10)": dict(sorted(hist.items()))}
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    if a.report:
        Path(a.report).write_text(out, encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "gated"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
