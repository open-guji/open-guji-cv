# -*- coding: utf-8 -*-
"""读真实数据的图像 IO 必须走 `utils/image_io`（非 ASCII 路径安全）。

2026-09-20 实锤：工作区迁进 `guji-workspace` 之后，书目录名带上了中文
（`96mid1ogzk-欽定四庫全書總目武英殿刻本`）。Windows 上 `cv2.imread` 对非 ASCII
路径**静默返回 None**——不抛异常、不打日志，调用方只看到"图是空的"。那天的
排查一度把"探针读不到图"误判成"产物坏了"，绕了好几圈才发现是路径编码。

`utils/image_io.imread` 早就处理了这件事（`imread` 失败就退回
`np.fromfile` + `cv2.imdecode`），`imwrite` 同理走 `imencode` + `tofile`。
本守卫挡住**新增**的直接调用：读仓内固定资源（fonts/、models/ 这类纯 ASCII 路径）
不受影响，白名单在 `_ALLOWED` 里，加之前先想清楚那条路径会不会跟着工作区走。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
PKG = REPO / "open_guji_cv"

#: 允许直接调 cv2.imread/imwrite 的文件——**只限路径永远是 ASCII 的**。
#: 想加新条目：先确认那条路径不可能落在工作区下（工作区目录名含书名，可能是中文）。
_ALLOWED = {
    "utils/image_io.py",            # 封装本体
    "clustering/extra_glyphs.py",   # 自己已用 imdecode 处理（见文件内注释）
    "clustering/glyph_db.py",       # 读的是 db 里的 bytes，不走文件路径
}


def _rel(p: pathlib.Path) -> str:
    return p.relative_to(PKG).as_posix()


def _direct_cv2_io_calls(path: pathlib.Path) -> list[tuple[int, str]]:
    """返回 [(行号, 'imread'|'imwrite')]——形如 `cv2.imread(...)` 的直接调用。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("imread", "imwrite"):
            continue
        val = node.func.value
        # cv2.imread(...) / _cv2.imread(...)——按名字结尾认，别漏了别名
        if isinstance(val, ast.Name) and val.id.lstrip("_") == "cv2":
            hits.append((node.lineno, node.func.attr))
    return hits


def test_no_direct_cv2_imread_outside_image_io():
    """`open_guji_cv/` 下不许直接调 `cv2.imread` / `cv2.imwrite`。"""
    offenders: list[str] = []
    for f in sorted(PKG.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        rel = _rel(f)
        if rel in _ALLOWED:
            continue
        for lineno, fn in _direct_cv2_io_calls(f):
            offenders.append(f"{rel}:{lineno} 直接调 cv2.{fn}")
    assert not offenders, (
        "这些地方直接调了 cv2 的图像 IO——Windows 上非 ASCII 路径（工作区目录名含书名）"
        "会**静默返回 None**。改成 `from ..utils.image_io import imread as cv_imread`；"
        "确属纯 ASCII 固定资源的，加进本测试的 _ALLOWED 并写明理由：\n  "
        + "\n  ".join(offenders))


def test_image_io_handles_non_ascii_path(tmp_path):
    """封装本身在含中文的路径上读得出来——守卫的前提得先成立。"""
    import cv2
    import numpy as np

    from open_guji_cv.utils.image_io import imread, imwrite

    # 目录名照抄工作区那套「<book-index id>-<书名>」的形状——非 ASCII 才是本测试的要害。
    # （不用真实的子目录名，免得撞上 test_suite_hygiene 的「仓内不出现工作区路径」护栏。）
    d = tmp_path / "96mid1ogzk-欽定四庫全書總目武英殿刻本" / "pages"
    d.mkdir(parents=True)
    f = d / "50.png"
    img = np.full((12, 20), 128, np.uint8)
    assert imwrite(str(f), img), "imwrite 应当能写进含中文的路径"
    assert f.exists() and f.stat().st_size > 0

    got = imread(str(f), cv2.IMREAD_GRAYSCALE)
    assert got is not None, "封装必须读得出非 ASCII 路径"
    assert got.shape == (12, 20)

    # 对照：裸 cv2.imread 在这条路径上正是读不到的那一个（Windows）。
    # 别的平台读得到，所以只在读不到时断言"封装比它强"，不反过来要求它必须失败。
    bare = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
    if bare is None:
        assert got is not None, "裸 imread 失败时封装仍应成功——这正是封装存在的理由"
