# -*- coding: utf-8 -*-
"""控制台 · 字形库抽检：按来路（provenance）随机抽刻例，逐条判对错（2026-09-27）。

来由：H 道要往全唐文自有库进 4367 条机器高可信刻例（`provenance='auto'`，#115），
其中 1664 个新字种的错率没有人裁实测；用户要在控制台随机抽约 100 条判对错
（CV 总管派 C 道，overview#110 评论）。现有字形库页（总览 / 字表→单字页 / 体检）
不能按来路过滤、也不能随机抽，所以补这一个**只读**接口。

**写入一律不在这里**：前端对每条的裁决直接调 H 现成的
`POST /api/glyphlib/audit/decide`（`glyph_audit` 事件，批次 `glyphlib-audit`）——
对 = `ok`（只记账）、错→撤库 = `evict`、错→改成某字 = `relabel`。卡片 key 统一
`spot:<实例 id>`，与体检卡（selfcheck 的 key）分开，裁决账同一份 `decisions.jsonl`，
本接口读它回显「这条抽检过没有」。

随机性：`seed` 固定就可复现同一批（刷新页面不换样本）；换 `seed` 换一批。
"""
from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_reviewer
from ..errors import maps_http

router = APIRouter(dependencies=[Depends(require_reviewer)])

SPOT_PREFIX = "spot:"


def sample_exemplars(db_path: str | Path, provenance: str = "auto", batch: str = "",
                     n: int = 100, seed: int = 0) -> dict:
    """库里 `admissions.provenance` 归到 `provenance` 的活刻例（在 `exemplars` 里）里
    随机抽 `n` 条。`batch` 非空时只抽证据里 `batch` 等于它的（如 `qtw-auto-20260927`）。
    `provenance='human'` 也收 `human_stale_*` 这类历史标记（同 `glyph_ledger._prov_class`）。
    纯读，只读打开。→ {n_pool, batches, items:[{instance_id, char, provenance, batch, evidence}]}"""
    c = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    try:
        rows = c.execute(
            "SELECT e.instance_id, g.char, a.provenance, a.evidence "
            "FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id "
            "JOIN admissions a ON a.instance_id=e.instance_id "
            "WHERE g.edition_tag NOT LIKE 'font:%' ORDER BY e.instance_id").fetchall()
    finally:
        c.close()
    pool, batches = [], {}
    seen: set[str] = set()
    for iid, ch, prov, ev in rows:
        cls = "human" if (prov or "").startswith("human") else (prov or "unknown")
        if cls != provenance or iid in seen:
            continue
        try:
            evd = json.loads(ev) if ev else {}
        except ValueError:
            evd = {}
        b = (evd.get("batch") if isinstance(evd, dict) else None) or ""
        batches[b] = batches.get(b, 0) + 1
        if batch and b != batch:
            continue
        seen.add(iid)
        pool.append({"instance_id": iid, "char": ch, "provenance": prov, "batch": b,
                     "evidence": {k: evd[k] for k in ("channel", "verdict", "cov", "page", "book")
                                  if isinstance(evd, dict) and k in evd}})
    items = random.Random(seed).sample(pool, min(n, len(pool)))
    return {"n_pool": len(pool), "batches": dict(sorted(batches.items())), "items": items}


@router.get("/api/glyphlib/spotcheck")
@maps_http
def api_glyphlib_spotcheck(provenance: str = "auto", batch: str = "", n: int = 100,
                           seed: int = 0) -> dict:
    """抽检样本 + 每条已有的裁决（`decisions.jsonl` 里 key=`spot:<实例>` 的最后一条）。"""
    from ...clustering.glyph_selfcheck import decisions
    from ...core.workspace import glyph_db_path
    db = glyph_db_path()
    if not Path(db).exists():
        raise HTTPException(404, f"这个工作区没有字形库：{db}")
    n = max(1, min(int(n), 1000))
    out = sample_exemplars(db, provenance, batch, n, seed)
    dec = decisions(Path(db).parent / "glyph_selfcheck")
    for it in out["items"]:
        it["key"] = SPOT_PREFIX + it["instance_id"]
        d = dec.get(it["key"])
        it["decision"] = ({"v": d.get("v"), "char": d.get("char"), "ts": d.get("ts")}
                          if d else None)
    # 累计账（不随样本变）：撤库的刻例会从池里消失，同一 seed 刷新后样本会变，
    # 所以错率按全部 `spot:` 裁决算，不按「这一屏」算。
    tally: dict[str, int] = {}
    for k, d in dec.items():
        if k.startswith(SPOT_PREFIX):
            tally[d.get("v") or "?"] = tally.get(d.get("v") or "?", 0) + 1
    out.update({"provenance": provenance, "batch": batch, "seed": seed, "tally": tally})
    return out
