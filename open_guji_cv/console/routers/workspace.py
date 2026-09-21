# -*- coding: utf-8 -*-
"""控制台 · 工作区（2026-09-15）。

## 工作区是**浏览器的状态**，不是服务端的

用户定的形态：这个值只存在于浏览器，每个请求用 `X-Guji-Workspace` 头带过来
（`console/middleware.py` 收，塞进 contextvar）。这样开两个标签页可以各自在
不同工作区上干活；服务端不持有「当前工作区」，也就没有「A 切一下 B 跟着变」
的问题。

所以这里**只有 GET**：列出能切到哪些工作区、以及本请求解析出来的各个根。
没有「切换」接口——切换是前端改自己 localStorage 里的值，下一个请求自然就带
新的了，不需要通知服务端。

演进（留个记录，免得后人再走一遍）：第一版是「改进程的环境变量」，必须重启
控制台才生效；第二版改成热切（改环境变量 + 重建进程内单例），但那仍是服务端
全局状态，两个标签页会打架，而且跑批子进程会继承到「出队那一刻」的值；
第三版即现在这版，工作区归浏览器，跑批的工作区归工单（`JobSpec.workspace`）。

## 能切到哪些

不写死清单：扫当前工作区的**兄弟目录**，认「有 books/*.yaml 的」。
`GUJI_WORKSPACE_DIRS`（分号/冒号分隔）可以显式指定，覆盖自动发现。
引擎仓不该有工作区注册表——工作区是用户那边的数据仓。

这份清单同时是**白名单**：请求头里的工作区必须在其中，中间件才认。
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

from ...core.workspace import describe, workspace_root

router = APIRouter()


def _ws_id(d: Path) -> str:
    """工作区的 id——**URL 上露出来的就是这个**（`/<ws>/<book>/step/...`）。

    默认取目录名去掉 `-workspace` 后缀（`xx-workspace` → `xx`）：短、稳定。
    **`guji-workspace` 那套目录名是 `<book-index id>-<书名>`**，不以 `-workspace`
    结尾，退回来就是一整串中文——那种工作区**必须**放 `workspace.yaml` 写
    `id: 自定义` 覆盖（四庫總目写的是 `siku-zongmu`，与旧仓时期的 URL 一致）。
    """
    import yaml
    f = d / "workspace.yaml"
    if f.is_file():
        try:
            got = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("id")
            if got:
                return str(got)
        except Exception:
            pass                        # 写坏了就退回目录名，不让整个列表挂掉
    name = d.name
    return name[: -len("-workspace")] if name.endswith("-workspace") else name


def discover_workspaces(current: Path | None = None) -> list[dict]:
    """能切到哪些工作区。`current` 不给就按本请求解析出来的那个。"""
    if current is None:
        current = workspace_root()
    env = os.environ.get("GUJI_WORKSPACE_DIRS")
    cands: list[Path] = []
    if env:
        cands = [Path(x).expanduser() for x in env.replace(";", os.pathsep).split(os.pathsep)
                 if x.strip()]
    elif current is not None:
        cands = sorted(d for d in current.parent.iterdir() if d.is_dir())

    cur_res = current.resolve() if current else None
    out: list[dict] = []
    for d in cands:
        books = d / "books"
        if not books.is_dir():
            continue
        ids = sorted(y.stem for y in books.glob("*.yaml"))
        if not ids and d.resolve() != cur_res:
            continue                      # 空工作区不列（当前这个除外，免得自己消失）
        out.append({"id": _ws_id(d), "path": str(d.resolve()), "name": d.name,
                    "books": ids, "current": d.resolve() == cur_res})
    return out


def resolve_workspace_id(ws_id: str) -> str | None:
    """工作区 id → 绝对路径。认不出返回 None（中间件据此忽略，退回默认）。

    URL 里带的是 id，落到磁盘要变成路径；这一步同时**就是白名单校验**
    ——只有 `discover_workspaces()` 列出来的 id 才认，浏览器塞个别的进来
    解析不出路径，不会变成「让服务端读写任意目录」。
    """
    env = os.environ.get("GUJI_WORKSPACE")
    base = Path(env).expanduser().resolve() if env else None
    for w in discover_workspaces(base):
        if w["id"] == ws_id:
            return w["path"]
    return None


def allowed_workspaces() -> set[str]:
    """白名单：请求头里的工作区必须是这里面的。

    浏览器来的值不能当任意路径用——那等于开放「让服务端读写任意目录」。
    这里用**环境变量**那个工作区做发现的起点（不是本请求的覆盖，否则
    白名单会跟着请求头自己变，等于没有白名单）。"""
    env = os.environ.get("GUJI_WORKSPACE")
    base = Path(env).expanduser().resolve() if env else None
    return {w["path"] for w in discover_workspaces(base)}


@router.get("/api/workspace")
def api_workspace_get() -> dict:
    """本请求的工作区、它解析出来的各个根、以及能切到哪些。

    「本请求的」——如果带了 `X-Guji-Workspace` 头，这里回的就是那个。
    前端据此显示当前标签页在哪个工作区上。"""
    ws = workspace_root()
    return {"workspace": str(ws) if ws else None, "roots": describe(),
            "available": discover_workspaces(ws)}
