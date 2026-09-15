# -*- coding: utf-8 -*-
"""控制台 · 工作区切换（2026-09-15）。

## 为什么能热切

`core/workspace.py` 里每个路径函数（`products_root()` / `cache_root()` /
`glyph_db_path()` …）都是**调用时**读 `os.environ["GUJI_WORKSPACE"]`，不是导入时
定死的——当初就为「`GUJI_WORKSPACE` 可能在导入之后才设」留了这条路（见
`steps/glyph_match._default_db` 的注释）。所以换工作区不必换进程，改环境变量
再把进程内那几个**记住了根**的东西重建一遍就行。

记住了根的一共三处，少清一处就会读到上一个工作区的数据：

1. `deps` 的四个单例（`event_log` / `batch_store` / `gold_store` / `verdict_store`）
   ——构造时把根算进了实例，`deps.set_roots()` 负责重建；
2. `seeding._MATCHER_CACHE`——字形库的内存索引。键里带 `db_path`，换工作区后键
   自然不同、不会串味，但旧工作区那份还占着几百 MB 内存，顺手清掉；
3. `ProductStore` 的 manifest 缓存——它本来就「每次新建」（`deps.product_store()`
   的注释说明了为什么不能做成单例），不用管。

## 为什么跑批时不给切

`JobRunner` 的 worker 线程和 HTTP 请求在同一个进程里共享 `os.environ`。跑到一半
把工作区换掉，后半批的产物会落到**另一个工作区**的 `products/` 下——这种错不会
报错，只会安静地写错地方。所以有任务在跑就拒绝（409），让人先等它跑完或取消。
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import deps
from ...core.workspace import describe, workspace_root

router = APIRouter()


class SwitchBody(BaseModel):
    path: str
    """工作区仓根的绝对路径。空串 = 清掉 GUJI_WORKSPACE，退回仓内样本。"""


def _discover(current: Path | None) -> list[dict]:
    """能切到哪些工作区：扫当前工作区的**兄弟目录**，认「有 books/*.yaml 的」。

    引擎仓本身没有工作区注册表（它只认一个环境变量），也不该有——工作区是
    用户那边的数据仓，位置由 `GUJI_WORKSPACE` 说了算。所以这里不写死清单，
    按「跟当前工作区放在一起、且长得像工作区」去发现。`GUJI_WORKSPACE_DIRS`
    （分号/冒号分隔）可以显式指定，覆盖自动发现。"""
    env = os.environ.get("GUJI_WORKSPACE_DIRS")
    cands: list[Path] = []
    if env:
        cands = [Path(x).expanduser() for x in env.replace(";", os.pathsep).split(os.pathsep) if x.strip()]
    elif current is not None:
        cands = sorted(d for d in current.parent.iterdir() if d.is_dir())

    out: list[dict] = []
    for d in cands:
        books = d / "books"
        if not books.is_dir():
            continue
        ids = sorted(y.stem for y in books.glob("*.yaml"))
        if not ids and d != current:
            continue                      # 空工作区不列（当前这个除外，免得自己消失）
        out.append({"path": str(d), "name": d.name, "books": ids,
                    "current": current is not None and d.resolve() == current})
    return out


@router.get("/api/workspace")
def api_workspace_get() -> dict:
    """当前工作区、它解析出来的各个根、以及能切到哪些工作区。"""
    ws = workspace_root()
    return {"workspace": str(ws) if ws else None, "roots": describe(),
            "available": _discover(ws)}


@router.post("/api/workspace")
def api_workspace_switch(body: SwitchBody) -> dict:
    """热切工作区：改 `GUJI_WORKSPACE` + 重建进程内记住根的东西。不重启进程。"""
    job = deps.runner().running()
    if job is not None:
        # 见模块头：worker 线程与本请求共享 os.environ，切了会把后半批产物写到
        # 另一个工作区去，而且不报错。
        raise HTTPException(
            status_code=409,
            detail=f"有任务在跑（{job.id}：{job.spec.book} {job.spec.from_step}→{job.spec.to_step}），"
                   f"切换会把它后半程的产物写到另一个工作区。等它跑完，或先取消它。",
        )

    old = str(workspace_root() or "")
    path = (body.path or "").strip()
    if path:
        p = Path(path).expanduser()
        if not p.is_dir():
            raise HTTPException(status_code=400, detail=f"目录不存在：{p}")
        os.environ["GUJI_WORKSPACE"] = str(p.resolve())
    else:
        os.environ.pop("GUJI_WORKSPACE", None)

    # ① 四个记住了根的单例：传 None 让它们各自按新环境重新解析
    deps.reset_roots()
    # ② 字形库内存索引：键里带 db_path 不会串味，但旧库那份还占着内存
    from ...clustering.seeding import _MATCHER_CACHE
    _MATCHER_CACHE.clear()

    ws = workspace_root()
    return {"workspace": str(ws) if ws else None, "previous": old or None,
            "roots": describe(), "available": _discover(ws)}
