# -*- coding: utf-8 -*-
"""重切之后，把库里「id 已指到别的字」的刻例挪回它现在所在的格（字形库 08，2026-09-26）。

    GUJI_WORKSPACE=<书目录> PYTHONPATH=. python scripts/glyph_rekey_drift.py <crosscheck.jsonl> [--apply]

输入是 `scripts/glyph_crosscheck.py --drift` 的输出（check=drift 那些）。

## 为什么要挪

刻例 id 是格号（`v2:<book>:页:列:格`）。重切一次，同一个字可能挪一格，id 就指到了邻字。
库里的图和字本身没错，但：

- 匹配时的留一法（`exclude_self`）按 id 摘自证：摘掉的是**别的字**，而这个字真正所在的格
  反而能查到自己那份刻例——自己证自己，cov≈1.0。新 Step7 拿「库里有完全同形的已定实例」当铁证，
  这正好是一条假铁证。
- 后来的人裁按**现在的**格号进库，与旧 id 对不上，同一个字在库里存成两份。

## 怎么找新格

在同页、同列 ±1、格号 ±4 的现有字块里找形状最像的：弹性覆盖率 ≥ 0.92，且比第二名高 0.03，
逐像素几乎相同（≥0.995）时不看第二名（常用字在邻列常有第二个 0.99）。
新格已被库里**同字**刻例占用 → 旧 id 这份是重复，撤掉；被别的字占用就不动。找不到就不动，只报出来。挪的时候用新格现在的字块
（上游切分改进的收益一并吃到），字、读法、来路照旧，证据里记 `rekeyed_from`。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402

from open_guji_cv.clustering.audit import evict_instance  # noqa: E402
from open_guji_cv.clustering.canonical import encode_png, to_canonical  # noqa: E402
from open_guji_cv.clustering.glyph_db import GlyphDB, _unpng  # noqa: E402
from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.verify import verify_pair_elastic  # noqa: E402
from open_guji_cv.core.workspace import glyph_db_path  # noqa: E402
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.utils.binarized import binarize_page  # noqa: E402

TH, MARGIN = 0.92, 0.03


def main() -> int:
    rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    # v2 人裁（v2:<格>）与播种/机器准入（<book>:<格>，同为 slot 坐标）都挪；v1 idx 坐标的不在 drift 里
    rows = [r for r in rows if r["check"] == "drift"]
    # 重切多是整列平移一格：按格号从小到大挪，前一格腾出来后一格才进得去（链式）
    def _k(r):
        b_, p_, c_, s_ = r["cell"].split(":")
        return (b_, int(p_), int(c_), int(s_.rstrip("ab")), s_)
    rows.sort(key=_k)
    apply = "--apply" in sys.argv
    cache = ImageCache()
    db = GlyphDB(str(glyph_db_path()))
    have = {r[0] for r in db.conn.execute("SELECT instance_id FROM instances")}
    cdir = None
    moved, stuck = [], []
    for r in rows:
        iid = r["instance_id"]
        b, pg, col, slot = r["cell"].split(":")
        row = db.conn.execute("SELECT d.data, a.char, a.provenance, a.evidence, i.label "
                              "FROM derived d JOIN admissions a ON a.instance_id=d.instance_id "
                              "JOIN instances i ON i.instance_id=d.instance_id "
                              "WHERE d.instance_id=? AND d.kind='norm'", (iid,)).fetchone()
        if not row:
            continue
        norm, reading, prov, ev, label = row
        mine = _unpng(norm)
        if cdir is None:
            # 按本列前几格探缓存目录：格号 1 可能是抬头/空格没出字块（四庫 5:7、vol03 17:3 实测）
            for s_ in range(1, 31):
                p0 = cache.get(b, "char_patch", f"p{int(pg):04d}c{int(col):02d}s{s_}")
                if p0:
                    cdir = Path(p0).parent
                    break
        if cdir is None:
            stuck.append((iid, "no cache dir"))
            continue
        cands = []
        for c in range(int(col) - 1, int(col) + 2):
            for f in cdir.glob(f"p{int(pg):04d}c{c:02d}s*.png"):
                m = re.fullmatch(r"p\d{4}c\d{2}s(\d+)([ab]?)", f.stem)   # 跳过 _below0 之类附图
                if not m or abs(int(m.group(1)) - int(slot.rstrip("ab"))) > 4:
                    continue
                s = m.group(1) + m.group(2)
                img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                canon = to_canonical(binarize_page(img, edge_margin=0))
                cov = float(verify_pair_elastic(mine, normalize_patch(canon)).f1)
                cands.append((cov, f"{b}:{int(pg)}:{c}:{s}", canon))
        cands.sort(key=lambda t: -t[0])
        if "--debug" in sys.argv:
            print(iid, [(round(x[0], 3), x[1]) for x in cands[:3]])
        # 逐像素几乎一样（≥0.995）就是同一格，不看第二名——常用字在邻列常有第二个 0.99
        exact = bool(cands) and cands[0][0] >= 0.995
        if not cands or cands[0][0] < TH or (not exact and len(cands) > 1
                                             and cands[0][0] - cands[1][0] < MARGIN):
            stuck.append((iid, f"best={cands[0][0]:.3f}@{cands[0][1]}" if cands else "no cand"))
            continue
        cov, new_cell, canon = cands[0]
        new_id = ("v2:" if iid.startswith("v2:") else "") + new_cell
        if new_id == iid:
            continue                     # 还在原格（图已刷新），不用挪
        if new_id in have and new_id != iid:
            other = db.conn.execute("SELECT label FROM instances WHERE instance_id=?", (new_id,)).fetchone()
            if other and other[0] == label:
                # 新格已按现在的格号进过库、字相同：旧 id 这份就是重复，撤掉
                moved.append((iid, f"dup-of {new_id}", label, round(cov, 3)))
                if apply:
                    evict_instance(db, iid)
                    have.discard(iid)
                continue
            stuck.append((iid, f"target {new_id} occupied by {other[0] if other else '?'}"))
            continue
        moved.append((iid, new_id, label, round(cov, 3)))
        if apply:
            try:
                evd = json.loads(ev) if ev else {}
            except ValueError:
                evd = {}
            evd = {**(evd if isinstance(evd, dict) else {}), "rekeyed_from": iid, "rekey_cov": round(cov, 3)}
            evict_instance(db, iid)
            _b, npg, ncol, nslot = new_cell.split(":")
            db.admit_instance(new_id, reading or label, encode_png(canon), provenance=prov,
                              shape=label, evidence=evd, page=npg, col=int(ncol),
                              idx=int(nslot.rstrip("ab")))
        have.discard(iid)          # 试算也推演占位，链式平移才算得对
        have.add(new_id)
    db.close()
    for m in moved:
        print("move", *m)
    for s in stuck:
        print("stuck", *s)
    print(f"{'已挪' if apply else '可挪'} {len(moved)}，挪不动 {len(stuck)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
