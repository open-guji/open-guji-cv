# -*- coding: utf-8 -*-
"""模型系统二期：模型文件按 sha256 进出 R2（设计 `doc/design/模型系统.md` 第四节）。

清单（`core/model_pack.py` 的 ``m<N>``）里每个文件都按内容寻址存进 R2（键 ``sha256/<前两位>/<sha>.txt``，
与语料大文件同一套，`datastore/scope.r2_key`）。取回时放回清单登记的位置（cv 仓 ``models/…`` 或数据目录
``config/groups/…``），所以各 Step 读模型的路径、代码、指纹一概不变——cv 仓以后不带 ``models/``，
起跑前按册钉的总号把文件取回即可。

- ``upload(ws, n, execute)``：把清单里的文件传进 R2（已有跳过）；缺省只演练。本机文件 sha 与清单不符拒传。
- ``fetch(ws, n)``：本机缺的文件从 R2 取回、放到登记位置；已有但内容不同的**不覆盖**，报出来
  （之后 `require_model_clean` 会拒跑）。
- ``ensure_model_pin(book)``：``guji pipeline``／``step`` 起跑前调，册钉了 ``model:`` 且有缺文件时自动取。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

EXT = "txt"          # R2 键后缀（Worker 按它定 content-type；与语料大文件同）


def _paths(ws: Path, man: dict) -> list[tuple[dict, Path]]:
    from ..core.model_pack import _base
    return [(it, _base(it["root"], ws) / it["path"]) for it in man.get("items") or []]


def upload(ws: Path, version: int | None = None, execute: bool = False) -> dict:
    from ..core import model_pack as mp
    v = version or (mp.versions(ws) or [None])[-1]
    if not v:
        raise FileNotFoundError("还没有模型清单（先 guji model build）")
    man = mp.load_manifest(ws, v)
    have, missing, stale = {}, [], []
    for it, p in _paths(ws, man):
        if not p.is_file():
            missing.append(it["path"])
        elif mp._sha256(p) != it["sha256"]:
            stale.append(it["path"])
        else:
            have[it["sha256"]] = p
    if stale:
        raise ValueError(f"本机文件内容与 m{v} 清单不符，不上传：{stale[:3]}（先 guji model verify）")
    plan = {"version": v, "files": len(man.get("items") or []), "local": len(have),
            "bytes": sum(p.stat().st_size for p in have.values()), "missing_local": missing, "executed": False}
    if execute:
        from ..datastore.r2 import upload_files
        plan["upload"] = upload_files(have, bucket="main", ext=EXT)
        plan["executed"] = True
    return plan


def fetch(ws: Path, version: int | None = None) -> dict:
    from ..core import model_pack as mp
    v = version or (mp.versions(ws) or [None])[-1]
    if not v:
        raise FileNotFoundError("还没有模型清单（先 guji model build）")
    man = mp.load_manifest(ws, v)
    todo, differ, ok = [], [], 0
    for it, p in _paths(ws, man):
        if not p.exists():
            todo.append((it, p))
        elif mp._sha_cached(p) == it["sha256"]:
            ok += 1
        else:
            differ.append(f'{it["root"]}:{it["path"]}')
    placed, absent = 0, []
    if todo:
        from ..datastore.client import BlobCache, WorkerSource
        cache = BlobCache()
        got = cache.ensure(WorkerSource(), sorted({it["sha256"] for it, _ in todo}), ext=EXT)
        absent = got["missing"]
        for it, p in todo:
            if cache.has(it["sha256"]):
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_name(p.name + ".part")
                shutil.copyfile(cache.path(it["sha256"]), tmp)
                tmp.replace(p)
                placed += 1
    return {"version": v, "already_ok": ok, "placed": placed, "differ_not_overwritten": differ,
            "not_in_r2": absent}


def ensure_model_pin(book) -> None:
    """册钉了模型总号：清单里有本机缺的文件就先从 R2 取回（取不到只提醒，起跑前校验会拒跑并说明）。"""
    v = getattr(book, "model", None)
    if not v:
        return
    from ..core import model_pack as mp
    from ..core.workspace import workspace_root
    ws = workspace_root()
    if ws is None:
        return
    try:
        man = mp.load_manifest(ws, v)
    except FileNotFoundError:
        return
    if all(p.exists() for _it, p in _paths(ws, man)):
        return
    try:
        r = fetch(ws, v)
        print(f"  模型 m{v}：从 R2 取回 {r['placed']} 个文件", flush=True)
        if r["not_in_r2"]:
            print(f"  ⚠️  R2 上没有 {len(r['not_in_r2'])} 个模型文件（先 guji model upload --execute）",
                  file=sys.stderr)
    except Exception as e:                     # noqa: BLE001 —— 没令牌、断网：交给起跑前校验报
        print(f"  ⚠️  模型 m{v} 缺文件，自动取回失败：{e}", file=sys.stderr)
