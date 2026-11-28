"""一次性：把第四步 L4 的旧看图缓存（裁定库 `ctx_ruling`、`prompt_ver="vis1:<sha1 前 12 位>"`）转成第三步 `glyph_vis` 的
`vis_glyph` 记录（`legacy=true`），供 A/B（CV3／CV4 2026-11-28）。

    # 先看（缺省 dry-run，只报数不写）
    python scripts/rekey_vis1_to_glyph_vis.py -w <工作区>
    # 真写（只追加到本机 <feedback>/vis_glyph/，不推中心库、不改不删旧事件）
    python scripts/rekey_vis1_to_glyph_vis.py -w <工作区> --write

做法：逐条取 `payload.cell` 那一格**当前**的 `char_patch`（缓存里读灰度，同第四步 `_page_patch` 的离线读法），
算 `sha1(字节)[:12]`，与 ver 里的哈希相同才算同一张图（重切挪了格的自然对不上），再算新键 `img_sha`（含形状），写：
`prompt="vis1-legacy"`、`prompt_sha`＝旧 SYSTEM 的哈希、`cands`＝该组＋登记表共字组组员、`model`＝原 payload 的 model、
`legacy=true`、`source_event`＝原事件 id。同一原事件已转过的跳过（可重复跑）。

旧答案**看过前后文**（图＋文意一问），第三步缺省不认（`glyph_vis.accept_legacy: false`）；开了只读、只供 A/B。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_CELL = re.compile(r"^(?P<book>[^:]+):(?P<page>\d+):(?P<col>\d+):(?P<slot>\d+)(?P<sub>[a-z]?)$")


def parse_cell(cell: str | None):
    m = _CELL.match(cell or "")
    if not m:
        return None
    return m["book"], int(m["page"]), int(m["col"]), int(m["slot"]), (m["sub"] or None)


def legacy_prompt_sha() -> str:
    from open_guji_cv.groups import vis_llm
    return hashlib.sha256((vis_llm.VER + "\x1f" + vis_llm.SYSTEM).encode("utf-8")).hexdigest()[:16]


def legacy_cands(group: str) -> list[str]:
    """`_vis_try` 的口径：本组＋共字组组员（共字组按登记表 `overlaps` 全取；书的点名这里看不到）。"""
    from open_guji_cv.groups.registry import GROUPS
    if group not in GROUPS:
        return []
    mem = set(GROUPS[group].members)
    for h in GROUPS[group].overlaps:
        if h in GROUPS:
            mem |= set(GROUPS[h].members)
    return sorted(mem)


def cache_patch(book: str, page: int, col: int, slot: int, sub: str | None):
    """缓存里这一格当前的 char_patch（灰度）；没有 → None。"""
    import cv2

    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.utils.image_io import imread
    path = ImageCache().get(book, "char_patch", f"p{page:04d}c{col:02d}s{slot}{sub or ''}")
    if path is None:
        return None
    try:
        return imread(str(path), cv2.IMREAD_GRAYSCALE, strict=True)
    except Exception:  # noqa: BLE001
        return None


def vis1_events(feedback_root: Path | None):
    from open_guji_cv.feedback.events import replay_key
    from open_guji_cv.feedback.rulings import KIND, RulingLog
    log = RulingLog(feedback_root)
    evs = [e for e in log.iter_all(raw=True)
           if e.kind == KIND and str((e.payload or {}).get("prompt_ver") or "").startswith("vis1:")]
    return sorted(evs, key=replay_key)


def rekey(events, patch_of, store, *, write: bool = False) -> dict:
    """`events`：vis1 裁定事件；`patch_of(book, page, col, slot, sub)` → 当前字块｜None；`store`：`VisGlyphStore`。
    → 计数 {total, matched, written, already, no_cell, no_patch, changed}。`write=False` 只数不写。"""
    from open_guji_cv.feedback.vis_glyph import LEGACY_PROMPT
    from open_guji_cv.groups.vis_img import OTHER, img_sha
    psha = legacy_prompt_sha()
    done = store.legacy_sources()
    rep = {"total": 0, "matched": 0, "written": 0, "already": 0, "no_cell": 0, "no_patch": 0, "changed": 0}
    batch = f"glyph-vis-rekey-{time.strftime('%Y%m%d', time.gmtime())}"
    for e in events:
        p = e.payload or {}
        rep["total"] += 1
        c = parse_cell(p.get("cell"))
        if c is None:
            rep["no_cell"] += 1
            continue
        patch = patch_of(*c)
        if patch is None:
            rep["no_patch"] += 1
            continue
        import numpy as np
        old = str(p.get("prompt_ver")).split(":", 1)[1]
        if hashlib.sha1(np.ascontiguousarray(patch).tobytes()).hexdigest()[:12] != old:
            rep["changed"] += 1
            continue
        rep["matched"] += 1
        if e.id in done:
            rep["already"] += 1
            continue
        if write:
            store.put(img_sha=img_sha(patch), img_shape=patch.shape, patch="char_patch", prompt=LEGACY_PROMPT,
                      prompt_sha=psha, cands=legacy_cands(p.get("group") or ""),
                      char=OTHER if p.get("other") else p.get("char"), conf=p.get("conf"), why=p.get("why") or "",
                      model=p.get("model") or "", tok=p.get("tok") or {}, cell=p.get("cell"), legacy=True,
                      source_event=e.id, batch=batch)
            done.add(e.id)
            rep["written"] += 1
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-w", "--workspace", default=None, help="工作区（设 GUJI_WORKSPACE）")
    ap.add_argument("--feedback", type=Path, default=None, help="feedback 根（缺省按工作区）")
    ap.add_argument("--write", action="store_true", help="真写（缺省 dry-run）")
    a = ap.parse_args(argv)
    if a.workspace:
        os.environ["GUJI_WORKSPACE"] = a.workspace
    from open_guji_cv.feedback.vis_glyph import VisGlyphStore, default_root
    root = a.feedback or default_root()
    store = VisGlyphStore(root)
    rep = rekey(vis1_events(root), cache_patch, store, write=a.write)
    rep["dir"] = str(store.dir)
    rep["mode"] = "write" if a.write else "dry-run"
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
