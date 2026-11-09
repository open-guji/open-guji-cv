"""图源文本层取字（R02「参校本没字」的第二见证；A24 2026-11，sheldon/ZM 11-09 同意，GUJI-758）。

新图源（如 siku-qiefen-v2）自带逐页文本层：每页一串字＋逐字框（`x,y,w,hgt`，文本层自己的像素系）。整理本在某一位没字
（坐标对位无条目）时，用文本层的字当第二个独立见证。文本层的字就是文意读法（刻形「雨」、文意「兩」就是「兩」，口径 sheldon 11-09）。

数据目录（`seed_admit.textlayer_ref_gap` 指向它）：
- `pagemap.json` 或 `pagemap.json.gz`：`{册号: [{"our": 本册页号, "their": [章, 章内页号]}, …]}`（无文本层的页没有 `their`）；
- `<章>/text.jsonl.gz`：每行 `{"p": 页号, "c": 字串, "x": […], "y": […], "w": […], "hgt": […]}`。

取字办法：本页 seed 字串与文本层字串（页号 ±3 页里取最像的）difflib 对出相同字，两边字框中心配对，最小二乘拟合
格框中心→文本层坐标的 2×3 仿射（≥`min_pairs` 对、三轮去离群；换图后坐标不是简单翻转，不能直接叠），再把缺字格的框变过去取重叠面积最大的字。
本模块只做取数与几何，护栏（私用码、形近字对）与放行由 `seed_admit._textlayer_ref_gap_pass` 做。"""
from __future__ import annotations

import difflib
import functools
import gzip
import hashlib
import json
import os
from pathlib import Path

VER = "tl1"


def resolve(path: str) -> Path:
    """相对路径按 `$GUJI_DATA_HOME/config/textlayer/` 找；绝对路径照用。"""
    p = Path(path)
    if p.is_absolute():
        return p
    home = os.environ.get("GUJI_DATA_HOME")
    return Path(home) / "config" / "textlayer" / p if home else p


def _open(p: Path):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def _pagemap_file(d: Path) -> Path | None:
    for n in ("pagemap.json.gz", "pagemap.json"):
        if (d / n).is_file():
            return d / n
    return None


@functools.lru_cache(maxsize=8)
def _pagemap(d: str) -> dict:
    f = _pagemap_file(Path(d))
    if f is None:
        return {}
    with _open(f) as fh:
        return json.load(fh)


@functools.lru_cache(maxsize=64)
def _chapter(d: str, ch: str) -> dict:
    f = Path(d) / str(ch) / "text.jsonl.gz"
    if not f.is_file():
        return {}
    out = {}
    with _open(f) as fh:
        for line in fh:
            r = json.loads(line)
            out[r["p"]] = r
    return out


def fingerprint(path: str) -> str:
    """数据目录指纹：页映射内容＋各章文本层文件名与大小（不读全文，快）。目录缺了记 `missing`。"""
    d = resolve(path)
    f = _pagemap_file(d)
    if f is None:
        return VER + "missing"
    h = hashlib.sha256(f.read_bytes())
    for t in sorted(d.glob("*/text.jsonl.gz")):
        h.update(f"{t.parent.name}:{t.stat().st_size}".encode())
    return VER + h.hexdigest()[:12]


def page_text(path: str, book_id: str, page: int, ours: str, near: int = 3):
    """本册第 page 页对应的文本层页：在 ±`near` 页里取与 `ours` 字串最像的。→ (相似度, 页记录) 或 None。"""
    d = str(resolve(path))
    rec = [a for a in _pagemap(d).get(book_id, []) if a.get("our") == page]
    if not rec or "their" not in rec[0]:
        return None
    ch, pg = rec[0]["their"]
    T = _chapter(d, str(ch))
    best = None
    for dp in range(-near, near + 1):
        r = T.get(pg + dp)
        if not r:
            continue
        ra = difflib.SequenceMatcher(None, ours, r["c"], autojunk=False).ratio()
        if best is None or ra > best[0]:
            best = (ra, r)
    return best


def fit_affine(ours: str, ids: list[str], box: dict, r: dict, min_pairs: int = 20):
    """seed 字串（`ids[i]` 是第 i 个字的格 id）与文本层页 r 相同字配对，拟合 格框中心→文本层中心 的仿射。
    → (A 3×2 矩阵, 保留配对数, 中位残差 px) 或 None。"""
    import numpy as np
    P, Q = [], []
    for a, b, n in difflib.SequenceMatcher(None, ours, r["c"], autojunk=False).get_matching_blocks():
        for i in range(n):
            bx, k = box.get(ids[a + i]), b + i
            if not bx or k >= len(r["x"]):
                continue
            P.append(((bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2))
            Q.append((r["x"][k] + r["w"][k] / 2, r["y"][k] + r["hgt"][k] / 2))
    if len(P) < min_pairs:
        return None
    P, Q = np.array(P), np.array(Q)
    M = np.c_[P, np.ones(len(P))]
    keep = np.ones(len(P), bool)
    for _ in range(3):
        A = np.linalg.lstsq(M[keep], Q[keep], rcond=None)[0]
        err = np.abs(M @ A - Q).max(axis=1)
        keep = err < max(6.0, 3 * float(np.median(err[keep])))
        if keep.sum() < 15:
            return None
    return A, int(keep.sum()), float(np.median(err[keep]))


def char_at(r: dict, A, bbox) -> tuple[str, float] | None:
    """把格框（bbox_page 四角）变到文本层坐标，取重叠面积最大的字。→ (字, 重叠面积÷格框面积) 或 None（<0.3）。"""
    import numpy as np
    x0, y0, x1, y1 = bbox
    pts = np.array([[x0, y0, 1], [x1, y1, 1], [x0, y1, 1], [x1, y0, 1]]) @ A
    l, rr, t, bt = pts[:, 0].min(), pts[:, 0].max(), pts[:, 1].min(), pts[:, 1].max()
    best = None
    for k, c in enumerate(r["c"]):
        if k >= len(r["x"]):
            break
        bx, by, bw, bh = r["x"][k], r["y"][k], r["w"][k], r["hgt"][k]
        a = max(0, min(rr, bx + bw) - max(l, bx)) * max(0, min(bt, by + bh) - max(t, by)) / max(1, (rr - l) * (bt - t))
        if best is None or a > best[1]:
            best = (c, a)
    return (best[0], round(float(best[1]), 3)) if best and best[1] > 0.3 else None


def lookup(path: str, book_id: str, page: int, ours: str, ids: list[str], box: dict, targets: list[str],
           min_pairs: int = 20) -> dict[str, dict]:
    """→ {格 id: {"char", "area", "ratio", "pairs", "resid"}}（只含取到字的目标格；页对不上、拟合失败返回空）。"""
    b = page_text(path, book_id, page, ours)
    if not b:
        return {}
    ratio, r = b
    f = fit_affine(ours, ids, box, r, min_pairs)
    if not f:
        return {}
    A, n, res = f
    out = {}
    for cid in targets:
        bx = box.get(cid)
        got = char_at(r, A, bx) if bx else None
        if got:
            out[cid] = {"char": got[0], "area": got[1], "ratio": round(ratio, 3), "pairs": n, "resid": round(res, 1)}
    return out
