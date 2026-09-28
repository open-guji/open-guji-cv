# -*- coding: utf-8 -*-
"""控制台 · 字形库「待纳入」：还没进库的候选刻例，按字分组给人裁收不收（2026-09-28，overview#176）。

来由：H #62 扫出四庫 vol03/vol04 30 个形近字薄刻例候选格（澤/河/仕/猶），都有
整理本对齐 + Step6 margin≥0.70 双证，但控制台没地方裁「还没进库的候选」——体检
（`/api/glyphlib/audit`）只出 `exemplars` 里已有的实例。

清单格式与裁决回读在 `feedback/candidates.py`（领域逻辑不放 console/）。这里**只读**：

- `GET /api/glyphlib/candidates`：工作区 `feedback/candidates/` 下有哪些清单、各裁了多少；
- `GET /api/glyphlib/candidates/{清单 id}`：一份清单按字分组，每组带库里同字的已有刻例。

**写入不在这里**：前端照常 `POST /api/events`（`kind=admit_candidate`，批次
`candidates-<清单 id>`）。路由表不给这个 kind 配消费者——控制台只写事件，进库由 H 道
的重放完成，本道**不写 glyph_store / glyph.db**。

候选格的图走现成的 `/api/cache/{book}/char_patch/{key}.png?src=bin`（没有缓存时现算），
库里刻例的图走 `/api/glyphlib/patch/{instance_id}.png`，这里不另开图片接口。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from .. import deps
from ..auth import require_reviewer
from ..errors import maps_http
from ...feedback import candidates as cand

router = APIRouter(dependencies=[Depends(require_reviewer)])


def _root() -> Path:
    # 跟着事件日志的根走（`deps` 在测试里会把 feedback 根指到临时目录）
    return deps.event_log().root / "candidates"


def _lib_exemplars(char: str, refs: list[str], limit: int) -> tuple[int | None, list[dict]]:
    """库里同字的已有刻例：(总数, 前 limit 条)。清单点名的对照刻例排最前，其次人裁。
    本工作区没有库 → (None, [])，页面照样能裁（只是没有对照）。"""
    from ...clustering.glyph_ledger import char_detail
    from ...core.workspace import glyph_db_path
    db = glyph_db_path()
    if not Path(db).exists():
        return None, []
    ex = [e for e in char_detail(db, char)["exemplars"] if not e.get("duplicate")]
    ref_rank = {r: i for i, r in enumerate(refs)}
    ex.sort(key=lambda e: (ref_rank.get(e["instance_id"], len(refs)),
                           0 if e.get("provenance") == "human" else 1, e["instance_id"]))
    for e in ex:
        e["is_ref"] = e["instance_id"] in ref_rank
    return len(ex), ex[:limit]


@router.get("/api/glyphlib/candidates")
@maps_http
def api_candidate_lists() -> dict:
    """清单一览：[{id, title, n, tally, n_problems}]。目录不存在就是空表，不报错。"""
    root = _root()
    out = []
    for lid in cand.list_ids(root):
        meta, rows, problems = cand.load_list(root / f"{lid}.jsonl")
        dec = cand.decisions(deps.event_log(), lid)
        out.append({"id": lid, "title": meta.get("title") or lid, "source": meta.get("source"),
                    "n": len(rows), "tally": cand.tally(rows, dec), "n_problems": len(problems)})
    return {"dir": str(root), "lists": out}


@router.get("/api/glyphlib/candidates/{list_id}")
@maps_http
def api_candidate_list(list_id: str, lib: int = 8) -> dict:
    """一份清单按字分组（按清单里首次出现的顺序）。每格带图块键与已落裁决，
    每组带库里同字的已有刻例（前 `lib` 条）与总数。"""
    try:
        path = cand.list_path(list_id, _root())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not path.exists():
        raise HTTPException(404, f"没有这份候选清单：{path}")
    meta, rows, problems = cand.load_list(path)
    dec = cand.decisions(deps.event_log(), list_id)
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r["char"], {"char": r["char"], "cells": [], "refs": []})
        g["cells"].append({**r, **cand.parse_cell(r["cell_id"]),
                           "decision": dec.get(r["cell_id"])})
        g["refs"] += [x for x in r["ref_instances"] if x not in g["refs"]]
    for g in groups.values():
        g["n_lib"], g["lib"] = _lib_exemplars(g["char"], g.pop("refs"), lib)
    return {"id": list_id, "meta": meta, "problems": problems, "batch": cand.batch_of(list_id),
            "kind": cand.KIND, "step": cand.STEP, "verdicts": list(cand.VERDICTS),
            "tally": cand.tally(rows, dec), "groups": list(groups.values())}
