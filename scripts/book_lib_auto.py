# -*- coding: utf-8 -*-
"""机器高可信格进书级库（`source: auto`），与人裁刻例分开记、可整批撤回（H 道，2026-09-27 全唐文 #64）。

    # 进库（不带 --apply 只报告）
    PYTHONPATH=. python scripts/book_lib_auto.py -w <书工作区> --books v006,v007 \
        --channels match_ref --verdicts same,unsure --cap 3 --batch qtw-auto-20260927 [--apply]
    # 整批撤回（按批次；撤库 + 追加撤回事件，不改旧事件）
    PYTHONPATH=. python scripts/book_lib_auto.py -w <书工作区> --withdraw qtw-auto-20260927 [--apply]

用户 09-27 23:05Z：机器判得非常可信的格也应该进本书库。CV 总管定的口径（overview
`进度/字形库/全唐文数据流-唯一真源.md` §三）：只让**实测错率 ≤1% 的通道/档位**进库、标 `source: auto`、
每字设上限、可按来源整批撤回、与人裁冲突以人裁为准。

选格：
- `seed_admit` 已放行、`channel ∈ --channels`、`glyph_match` 判档 ∈ `--verdicts`；
- 字形是单个汉字；本书库里该字的**人裁**刻例已 ≥ `--cap` 的字不再加机器刻例（人裁够了）；
- **自有库否决**：该字已在本书库时，拿本书库（全是人裁刻例）对这格再匹配一次，首选不是这个字
  （也不是异体）就不进——两路独立来源不一致；
- 同一格已有人裁事件的不进（人裁为准）；
- 每字按 `glyph_match` 覆盖度 cov 从高到低、不同页，取到 `--cap` 个。

进库走 `GlyphDB.admit_instance(provenance="auto")`（**不是**人裁的 `glyphdb_admit`：那条路写死
`provenance="human"`，而 5-b 真刻例原型只认 human——机器刻例不该冒充人裁）；图块与人裁同一把二值化
（`binarize_page(edge_margin=0)`）；实例 id 与人裁同一命名空间 `v2:<书:页:列:格>`，人裁后来改判时
`glyphdb_admit` 会撤掉机器那份。每进一格同时追加一条 `confirm` 事件（`actor=model`，
`payload.source="auto"`，带通道/判档/cov/批次），库可以从事件重放。
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))


def _pages(root: Path, book: str, step: str):
    for f in sorted((root / book / step).glob("p*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        yield d[next(iter(d))]


def _cells(root: Path, book: str, step: str) -> dict:
    out = {}
    for pm in _pages(root, book, step):
        for col in (pm.get("columns") or pm.get("char_index", {}).get("columns") or []):
            for r in col.get("chars") or []:
                out[r["id"]] = r
    return out


def withdraw(ws: Path, batch: str, apply: bool) -> dict:
    from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
    from open_guji_cv.core.workspace import glyph_db_path
    dbp = glyph_db_path()
    with sqlite3.connect(f"file:{dbp}?mode=ro", uri=True) as c:
        ids = [r[0] for r in c.execute(
            "SELECT instance_id FROM admissions WHERE provenance='auto' "
            "AND json_extract(evidence,'$.batch')=?", (batch,))]
    rep = {"withdraw": batch, "instances": len(ids), "apply": apply}
    if apply and ids:
        from open_guji_cv.clustering.audit import evict_instance
        from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
        db = GlyphDB(dbp)
        for iid in ids:
            evict_instance(db, iid)
        db.conn.commit()
        rep["export"] = export_store(db, ws / "output" / "glyph_store")
        db.close()
        log = EventLog(ws / "feedback")
        wb = f"{batch}-withdraw"
        base = log.latest_seq(wb)
        evs = []
        for i, iid in enumerate(ids, 1):
            key = iid[3:] if iid.startswith("v2:") else iid
            bk, pg, col, slot = key.split(":")
            evs.append(make_event(wb, base + i, "confirm",
                                  EventTarget(step="seed_admit", unit="cell", key=key, book=bk,
                                              page=int(pg), col=int(col), slot=int(slot)),
                                  {"v": "skip", "source": "auto", "withdraw": batch,
                                   "note": "机器高可信刻例整批撤回"}, actor="model"))
        rep["events"] = log.append(evs)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--books", default="")
    ap.add_argument("--channels", default="match_ref")
    ap.add_argument("--verdicts", default="same,unsure")
    ap.add_argument("--cap", type=int, default=3, help="每字机器刻例上限（人裁刻例已 ≥cap 的字不加）")
    ap.add_argument("--batch", default=None, help="批次名，如 qtw-auto-20260927（撤回按它）")
    ap.add_argument("--withdraw", default=None, help="整批撤回这个批次")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default=None)
    a = ap.parse_args(argv)

    ws = Path(a.workspace).expanduser().resolve()
    from open_guji_cv.core.workspace import glyph_db_path, products_root, set_workspace_override
    set_workspace_override(str(ws))
    if a.withdraw:
        rep = withdraw(ws, a.withdraw, a.apply)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0
    assert a.batch and a.books, "进库要给 --books 和 --batch"
    books = [b.strip() for b in a.books.split(",") if b.strip()]
    channels, verdicts = set(a.channels.split(",")), set(a.verdicts.split(","))

    from book_lib_sync import _related          # 同一份异体判定
    from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
    from open_guji_cv.clustering.normalize import normalize_patch as N
    from open_guji_cv.clustering.seeding import load_matcher_from_db
    from open_guji_cv.core.book import load_book
    from open_guji_cv.feedback.events import EventLog, EventTarget, make_event

    dbp = glyph_db_path()
    log = EventLog(ws / "feedback")
    human_keys = {e.target.key for e in log.iter_all() if e.actor == "user"}
    with sqlite3.connect(f"file:{dbp}?mode=ro", uri=True) as c:
        edition = (c.execute("SELECT value FROM meta WHERE key='book_edition'").fetchone() or [None])[0]
        n_human = collections.Counter(r[0] for r in c.execute(
            "SELECT g.char FROM exemplars e JOIN glyphs g USING(glyph_id) "
            "JOIN admissions a ON a.instance_id=e.instance_id WHERE a.provenance='human'"))
        n_auto = collections.Counter(r[0] for r in c.execute(
            "SELECT g.char FROM exemplars e JOIN glyphs g USING(glyph_id) "
            "JOIN admissions a ON a.instance_id=e.instance_id WHERE a.provenance='auto'"))
        in_lib = {r[0] for r in c.execute("SELECT instance_id FROM admissions")}
    lib_chars = set(n_human)
    matcher = load_matcher_from_db(GlyphDB(dbp), knn_k=10)[0] if lib_chars else None

    root = products_root()
    cand = collections.defaultdict(list)
    meta: dict[str, dict] = {}
    stat = collections.Counter()
    for b in books:
        sa, gm = _cells(root, b, "seed_admit"), _cells(root, b, "glyph_match")
        for k, r in sa.items():
            if not r.get("admit"):
                continue
            stat["admitted"] += 1
            ev = r.get("evidence") or {}
            if r.get("channel") not in channels or ev.get("verdict") not in verdicts:
                continue
            ch = r.get("char") or ""
            if len(ch) != 1 or ord(ch) < 0x2E80:
                stat["不是单个汉字"] += 1
                continue
            if k in human_keys:
                stat["已有人裁"] += 1
                continue
            if f"v2:{k}" in in_lib:
                stat["已在库"] += 1
                continue
            stat["候选"] += 1
            cov = ev.get("cov") or (gm.get(k) or {}).get("cov") or 0
            cand[ch].append((-cov, k))
            meta[k] = {"channel": r.get("channel"), "verdict": ev.get("verdict"), "cov": cov}

    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.utils.binarized import binarize_page
    import cv2
    cache, specs = ImageCache(), {b: load_book(b) for b in books}
    ctxs = {b: RunContext(specs[b], ProductStore(), cache, log=lambda *_: None) for b in books}
    cells = {b: _cells(root, b, "cell_shrink") for b in books}

    def patch(key):
        bk = key.split(":")[0]
        pk = (cells[bk].get(key) or {}).get("patch_key")
        return ctxs[bk].image("char_patch", pk) if pk else None

    picks, vetoed = [], []
    for ch, xs in sorted(cand.items()):
        room = a.cap - n_auto[ch] if n_human[ch] < a.cap else 0
        if room <= 0:
            stat["人裁已够或机器已满"] += len(xs)
            continue
        pages = set()
        for _neg, k in sorted(xs):
            if len([p for p in picks if p[0] == ch]) >= room:
                break
            pg = ":".join(k.split(":")[:2])
            if pg in pages:
                continue
            img = None
            if matcher is not None and ch in lib_chars:
                img = patch(k)
                if img is None:
                    continue
                c = matcher.match(N(img), exclude_id=f"v2:{k}").candidates
                top = c[0][0] if c else None
                if top != ch and not (top and _related(top, ch)):
                    vetoed.append({"key": k, "char": ch, "own_lib_top": top})
                    continue
            picks.append((ch, k, img))
            pages.add(pg)
    rep = {"workspace": str(ws), "edition": edition, "batch": a.batch, "apply": a.apply,
           "channels": sorted(channels), "verdicts": sorted(verdicts), "cap": a.cap,
           "stat": dict(stat), "picks": len(picks), "chars_new": len({ch for ch, _, _ in picks} - lib_chars),
           "vetoed_by_own_lib": vetoed[:200], "n_vetoed": len(vetoed),
           "lib_chars_before": len(lib_chars | set(n_auto))}
    if a.apply and picks:
        db = GlyphDB(dbp)
        base = log.latest_seq(a.batch)
        evs, n = [], 0
        for i, (ch, k, img) in enumerate(picks, 1):
            img = img if img is not None else patch(k)
            if img is None:
                continue
            bin_img = binarize_page(img, edge_margin=0)
            bk, pg, col, slot = k.split(":")
            e = make_event(a.batch, base + i, "confirm",
                           EventTarget(step="seed_admit", unit="cell", key=k, book=bk,
                                       page=int(pg), col=int(col), slot=int(slot)),
                           {"v": "confirm", "shape": ch, "source": "auto", **meta[k]},
                           actor="model")
            evs.append(e)
            ok = db.admit_instance(f"v2:{k}", ch, cv2.imencode(".png", bin_img)[1].tobytes(),
                                   provenance="auto", shape=ch,
                                   evidence={"event": e.id, "batch": a.batch, "source": "auto", **meta[k]},
                                   page=pg, col=int(col), idx=int(slot))
            n += bool(ok)
        rep["admitted"] = n
        rep["events"] = log.append(evs)
        rep["export"] = export_store(db, ws / "output" / "glyph_store")
        with sqlite3.connect(f"file:{dbp}?mode=ro", uri=True) as c:
            rep["lib_chars_after"] = c.execute("SELECT count(DISTINCT char) FROM glyphs").fetchone()[0]
        db.close()
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    if a.report:
        Path(a.report).write_text(out, encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "vetoed_by_own_lib"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
