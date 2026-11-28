"""3b 方法公用的：模型目录解析、字块预处理、模型目录／字对／组指纹、书级刻例库钉版指纹、`score` 调用壳、校准表读取。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from pathlib import Path

import numpy as np


REPO = Path(__file__).resolve().parents[3]


SIZE = 64


def resolve_dir(path: str) -> Path:
    """模型目录：绝对路径原样；相对路径先找数据目录（随中心库走），再找仓根（模型表 `repo` 类，`models/…`）。"""
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    from ...core.workspace import data_root
    droot = data_root()
    if droot is not None and (droot / p).exists():
        return droot / p
    return REPO / p


def prep_patch(gray: np.ndarray) -> np.ndarray:
    """灰度裁块 → 64×64（白底补成正方形再双线性缩放），与训练时的 `extract.py` 同一做法。"""
    from PIL import Image
    im = Image.fromarray(np.asarray(gray, dtype=np.uint8))
    w, h = im.size
    m = max(w, h)
    canvas = Image.new("L", (m, m), 255)
    canvas.paste(im, ((m - w) // 2, (m - h) // 2))
    return np.asarray(canvas.resize((SIZE, SIZE), Image.BILINEAR), dtype=np.uint8)


def vol_number(book_id: str) -> int | None:
    m = re.search(r"(\d+)\s*$", str(book_id or ""))
    return int(m.group(1)) if m else None


def _dir_fingerprint(d: Path) -> str:
    """模型目录里全部文件（名＋内容）的短哈希；给的是单个模型文件时只算它和同名校准表（`<去 .json>.calib.json`）。"""
    if d.is_file():
        h = hashlib.sha256()
        for f in (d, _sibling_calib(d)):
            if f.is_file():
                h.update(f.name.encode())
                h.update(hashlib.sha256(f.read_bytes()).digest())
        return h.hexdigest()[:16]
    h = hashlib.sha256()
    for f in sorted(d.iterdir()) if d.exists() else []:
        if f.is_file():
            h.update(f.name.encode())
            h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()[:16] if d.exists() else "missing"


def _sibling_calib(f: Path) -> Path:
    return f.with_name(f.name[:-5] + ".calib.json" if f.name.endswith(".json") else f.name + ".calib.json")


def _accepts(fn, name: str) -> bool:
    try:
        ps = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in ps or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in ps.values())


def score(m, patches: list, book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
    """调方法的 `score`：方法认 `ctx`／`cells` 才传（老方法只收 `patches, book_id`，照旧调）。"""
    kw = {}
    if _accepts(m.score, "ctx"):
        kw["ctx"] = ctx
    if _accepts(m.score, "cells"):
        kw["cells"] = cells
    return m.score(patches, book_id, **kw)


def _load_calib(p: Path) -> dict | None:
    """方法的校准表：给目录时是目录里的 `calib.json`，给文件时是同名 `<去 .json>.calib.json`；没有 → None。"""
    cal = p / "calib.json" if p.is_dir() else _sibling_calib(p)
    d = json.loads(cal.read_text(encoding="utf-8")) if cal.is_file() else None
    if d is not None and d.get("format") != "near-calib/1":
        raise ValueError(f"{cal} format 不是 near-calib/1：{d.get('format')!r}")
    return d


def _pair_fingerprint(path: Path, pair) -> str:
    """{path, pair} 写法的指纹：模型文件（＋同名校准表）的指纹与这一对（按码位排，次序不论）合起来的 sha256 短哈希。"""
    h = hashlib.sha256()
    h.update(_dir_fingerprint(path).encode())
    h.update(("|pair:" + "".join(sorted(str(c) for c in pair))).encode())
    return h.hexdigest()[:16]


def lib_fingerprint(src) -> str:
    """书级刻例库（book_knn／near_knn 的模型文件：本书已放行格当刻例的 PCA 库）钉好的那一版的指纹：文件内容 sha256 前 16 位。

    `src` 是库文件路径（`str`／`Path`；相对路径照 `resolve_dir` 先找数据目录再找仓根；给目录时取目录里的 `model.json`）。
    与第四步参数指纹 `bk`／`nk` 段（`book_knn.fingerprint`／`near_knn.fingerprint`）**同算法同值**；3b 把它写进 `methods_sha`
    （`<组>:book_knn=<指纹>`），4d 拿它现用的那份库（`group_flow_book_knn[组]`，已解析成绝对路径）调同一个函数比对，
    不一致时本地现算。文件不在 → `""`（同 `book_knn.fingerprint`）。"""
    p = resolve_dir(str(src))
    if p.is_dir():
        p = p / "model.json"
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else ""


def _group_fingerprint(path: Path, group: str) -> str:
    """{path, group} 写法的指纹：模型文件（＋同名校准表）的指纹与组名合起来的 sha256 短哈希。"""
    h = hashlib.sha256()
    h.update(_dir_fingerprint(path).encode())
    h.update(("|group:" + str(group)).encode())
    return h.hexdigest()[:16]
