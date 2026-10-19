# -*- coding: utf-8 -*-
"""daizhige 逐列本 → 逐列格位表（`row_segment.layout_prior` 读的那张）。

    python scripts/dzg_layout.py --ws <四庫總目书目录> [--out corpus/daizhige/layout_slots.jsonl] [--vols 04,05]

一行一列（只收 `page_map.jsonl` 里 kind=text、dzg_kind=full 的页，空列不写）：

    {"vol": "vol04", "page": 23, "col": 1, "dzg": "0001-0141h0",
     "slots": [3, 4, …, 21],   # 有字的 slot（夹注两半共用一个 slot）
     "notes": [12, 13],        # 雙行小注左右两半都有字的 slot
     "half": [14],             # 只有一半有字的 slot（段尾奇数字只有右半；行内空格也会只剩一半）
     "raised": 0}              # 出格抬头级数（daizhige start=-1 → 1）

格位口径：daizhige 的格位 pos（`start` 起算，-1/-2 出格）→ 我们的 slot：pos≥0 → pos+1，pos<0 → pos
（字形库 instances 已核：idx = daizhige 格位 + 1，vol01 910 列 900 符合）。我们一页 = daizhige 一个半叶，
列号 = `no % 9 + 1`。用法与实测见 `doc/research/切分现状梳理与新方向-2026-10-19.md` §六。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dzg_import import NCOL, _corpus, load_records  # noqa: E402


def slot_of(pos: int) -> int:
    return pos + 1 if pos >= 0 else pos


def column_layout(col: dict) -> dict | None:
    """daizhige 一列 → {slots, notes, half, raised}；空列 None。"""
    body, a, b = set(), set(), set()
    for r in col.get("runs", []):
        if r.get("t") == "text":
            body |= {slot_of(r["start"] + i) for i in range(len(r.get("s", "")))}
        elif r.get("t") == "note":
            for side, acc in (("r", a), ("l", b)):
                for off, s in r.get(side, []):
                    acc |= {slot_of(r["start"] + off + i) for i in range(len(s))}
    slots = body | a | b
    if not slots:
        return None
    neg = [s for s in slots if s < 0]
    return {"slots": sorted(slots), "notes": sorted(a & b), "half": sorted(a ^ b),
            "raised": -min(neg) if neg else 0}


def build(ws: Path, vols: set[str] | None = None) -> list[dict]:
    dz = _corpus(ws) / "daizhige"
    recs = {}
    for f in sorted(dz.glob("000*.jsonl")):
        for r in load_records(f):
            recs[r["id"]] = r
    out = []
    for ln in (dz / "page_map.jsonl").read_text(encoding="utf-8").splitlines():
        m = json.loads(ln)
        if m.get("kind") != "text" or m.get("dzg_kind") != "full" or (vols and m["vol"] not in vols):
            continue
        rec = recs.get(m["dzg_id"])
        cols = rec.get("cols") if rec and isinstance(rec.get("cols"), list) else []
        for c in cols:
            if (c["no"] >= NCOL) != bool(m["side"]):
                continue
            lay = column_layout(c)
            if lay:
                out.append({"vol": m["vol"], "page": m["page"], "col": c["no"] % NCOL + 1,
                            "dzg": f"{m['dzg_id']}h{m['side']}", **lay})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ws", default=os.environ.get("GUJI_WORKSPACE"))
    ap.add_argument("--out", default="corpus/daizhige/layout_slots.jsonl",
                    help="绝对路径，或相对 --ws；corpus/… 落在整理本目录（迁过中心库的工作区在数据目录）")
    ap.add_argument("--vols", default="", help="如 04,05；空 = 全部")
    a = ap.parse_args(argv)
    if not a.ws:
        ap.error("要 --ws 或 GUJI_WORKSPACE（四庫總目书目录）")
    ws = Path(a.ws)
    vols = {f"vol{v.zfill(2)}" for v in a.vols.split(",") if v} or None
    rows = build(ws, vols)
    rel = Path(a.out)
    if rel.is_absolute():
        out = rel
    elif rel.parts and rel.parts[0] == "corpus":
        out = _corpus(ws).joinpath(*rel.parts[1:])
    else:
        out = ws / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)} 列 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
