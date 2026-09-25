# -*- coding: utf-8 -*-
"""字形库 × 工作区记录 对账：库里的刻例，与这一格现在的裁决、排除名单、管线决定、字块图是否还对得上。

    GUJI_WORKSPACE=<书目录> PYTHONPATH=. python scripts/glyph_crosscheck.py <out.jsonl> [--drift]

字形库是「进库那一刻」的快照，工作区的记录会继续变：人改判、判非字、重切、管线重跑。
两边脱节时库里就留着过期的刻例，而新 Step7 要拿「库里同形已定实例」当铁证。
逐条检查（2026-09-26，字形库 08）：

- ``excluded``   这一格进了排除名单（判非字 / 原图破损 / 切坏），库里却还有刻例
- ``verdict``    人裁刻例：这一格**最新**的定字裁决已经不是库里的字（改判了），或已判非字 / 存疑
- ``pipeline``   机器准入的刻例（align / match / context）：这一格现在的 seed_admit 已不放行，或放行成别的字
- ``drift``      （--drift）库里的图与这一格现在的字块图不像了——重切之后 id 指到了别的字

v1 来源（四庫 vol01 旧管线，idx 从 0）按 slot = idx+1 对到现在的格；只作参考，不保证同格。
只报不改；每条带足证据，改库走控制台字形库页或 glyph_audit 事件。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.core.workspace import (exclusions_path, feedback_root,  # noqa: E402
                                         glyph_db_path, products_root)


def cell_of(iid: str, v1: set[str]) -> str | None:
    p = iid.split(":")
    if p[0] == "v2" and len(p) == 5:
        return ":".join(p[1:])
    if len(p) == 4:
        if p[0] in v1 and p[3].isdigit():
            return f"{p[0]}:{p[1]}:{p[2]}:{int(p[3]) + 1}"
        return iid
    return None


def latest_confirms(root: Path) -> dict[str, dict]:
    """每格最新一条定字类裁决（confirm 事件，含 v=not_a_char / skip / damaged / seg_defect）。"""
    out: dict[str, dict] = {}
    for f in sorted((root / "events").glob("*.jsonl")):
        for ln in open(f, encoding="utf-8"):
            if not ln.strip():
                continue
            e = json.loads(ln)
            if e.get("kind") != "confirm":
                continue
            k = e["target"]["key"]
            if k.startswith("v2:"):
                k = k[3:]
            p = e.get("payload") or {}
            v = p.get("v") or "confirm"
            if v == "seg_defect" and k in out:
                # 切分缺陷与定字是两件事：只补记，不盖掉定字
                out[k].setdefault("seg_defect", p.get("quality"))
                continue
            prev = out.get(k)
            if prev is None or (e.get("ts") or "") >= prev["ts"]:
                out[k] = {"ts": e.get("ts") or "", "v": v, "shape": p.get("shape") or p.get("char"),
                          "event": e["id"], "note": p.get("note")}
    return out


def pipeline_decisions(book_dirs: list[Path]) -> dict[str, dict]:
    out = {}
    for d in book_dirs:
        for f in sorted((d / "seed_admit").glob("p*.json")):
            doc = json.load(open(f, encoding="utf-8"))["seed_admit"]
            for c in doc.get("columns", []):
                for ch in c.get("chars", []):
                    out[ch["id"]] = {"admit": ch.get("admit"), "char": ch.get("char"),
                                     "channel": ch.get("channel"), "provenance": ch.get("provenance"),
                                     "doubts": ch.get("doubts")}
    return out


def main() -> int:
    out_path = Path(sys.argv[1])
    drift = "--drift" in sys.argv
    db = glyph_db_path()
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    v1 = {r[0] for r in c.execute("SELECT source_id FROM sources WHERE pipeline_version='v1'")}
    lib = c.execute(
        "SELECT e.instance_id, g.char, i.semantic, a.provenance, a.admitted_at "
        "FROM exemplars e JOIN glyphs g USING(glyph_id) JOIN instances i ON i.instance_id=e.instance_id "
        "LEFT JOIN admissions a ON a.instance_id=e.instance_id "
        "WHERE g.edition_tag NOT LIKE 'font:%'").fetchall()

    excl: dict[str, dict] = {}
    ep = exclusions_path()
    if ep.exists():
        for ln in open(ep, encoding="utf-8"):
            if ln.strip():
                d = json.loads(ln)
                excl[d["instance_id"]] = d
    conf = latest_confirms(feedback_root())
    pr = products_root()
    pipe = pipeline_decisions([d for d in pr.iterdir() if d.is_dir()]) if pr.exists() else {}

    findings = []
    for iid, ch, sem, prov, at in lib:
        cell = cell_of(iid, v1)
        if not cell:
            continue
        human = (prov or "").startswith("human")
        base = {"instance_id": iid, "cell": cell, "char": ch, "provenance": prov, "admitted_at": at,
                "v1_guess": iid.split(":")[0] in v1}
        x = excl.get(cell)
        if x and x.get("origin") == "human" and x.get("reason") in ("not_a_char", "damaged"):
            findings.append({**base, "check": "excluded", "why": x.get("reason"),
                             "evidence": x.get("source_event") or x.get("note")})
        v = conf.get(cell)
        if human and v and (x is None or x.get("origin") != "human"):
            if v["v"] in ("not_a_char", "damaged", "skip"):
                findings.append({**base, "check": "verdict", "why": f"latest:{v['v']}", "evidence": v["event"]})
            elif v["v"] == "confirm" and v["shape"] and v["shape"] != ch and (v["ts"] or "") > (at or ""):
                findings.append({**base, "check": "verdict", "why": f"latest:{v['shape']}",
                                 "evidence": v["event"], "note": v.get("note")})
        if v and v.get("seg_defect"):
            findings.append({**base, "check": "excluded", "why": f"seg_defect:{v['seg_defect']}",
                             "evidence": v["event"]})
        if not human and cell in pipe and not base["v1_guess"]:
            d = pipe[cell]
            if not d["admit"]:
                findings.append({**base, "check": "pipeline", "why": "no_longer_admitted",
                                 "evidence": {k: d[k] for k in ("channel", "doubts")}})
            elif d["char"] and d["char"] != ch:
                findings.append({**base, "check": "pipeline", "why": f"now:{d['char']}",
                                 "evidence": {k: d[k] for k in ("channel", "provenance")}})

    if drift:
        import cv2
        import numpy as np
        from open_guji_cv.clustering.canonical import to_canonical
        from open_guji_cv.clustering.glyph_db import _unpng
        from open_guji_cv.clustering.normalize import normalize_patch
        from open_guji_cv.clustering.verify import verify_pair_elastic
        from open_guji_cv.products.cache import ImageCache
        from open_guji_cv.utils.binarized import binarize_page
        cache = ImageCache()
        n_missing = 0
        for iid, ch, sem, prov, at in lib:
            cell = cell_of(iid, v1)
            if not cell or iid.split(":")[0] in v1:
                continue
            b, pg, col, slot = cell.split(":")
            sub = slot[-1] if slot[-1:] in ("a", "b") else ""
            s = slot[:-1] if sub else slot
            key = f"p{int(pg):04d}c{int(col):02d}s{int(s)}{sub}"
            path = cache.get(b, "char_patch", key)
            if path is None:
                n_missing += 1
                continue
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            cur = normalize_patch(to_canonical(binarize_page(img, edge_margin=0)))
            row = c.execute("SELECT data FROM derived WHERE instance_id=? AND kind='norm'", (iid,)).fetchone()
            if not row:
                continue
            f1 = float(verify_pair_elastic(_unpng(row[0]), cur).f1)
            if f1 < 0.80:
                findings.append({"instance_id": iid, "cell": cell, "char": ch, "provenance": prov,
                                 "admitted_at": at, "check": "drift", "why": f"cov={f1:.3f}"})
        print("drift: 缓存里没有字块的", n_missing)

    with open(out_path, "w", encoding="utf-8") as f:
        for x in findings:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(len(lib), "刻例；", Counter(x["check"] for x in findings),
          Counter((x["check"], x["why"].split(":")[0]) for x in findings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
