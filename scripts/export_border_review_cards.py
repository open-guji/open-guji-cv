# -*- coding: utf-8 -*-
"""为 Step1 的三个金标标注页一次性备料（探测跑一遍，出三种卡片素材）。

`detect_borders()` 一页要 10~40s，三个页面各跑一遍太浪费，所以合成一个导出器：
抽样正文页 → 跑一次探测 → 同时切出三种图，落盘到 `output/border_review/`。

三种卡片：

1. **列探测**（`cols`）——整页缩图 + 探到的界行叠上去。判「线是不是都落在字缝
   上」。这是文档里记的**准确率封顶因素**：40 页里 13 页没把列切对，下游
   Step2/Step3 全部连坐。
2. **抬头**（`head`）——上版框那一条横带的裁图，**不叠任何探测结果**。判「这页
   顶上有没有抬头（版框线本身有没有台阶）」。不叠是故意的：要量的是召回率，
   卡上印了机器的判断人就顺着点了，测出来的是机器自己。
3. **外框外延**（`outer`）——上/下版框那一条横带，叠**一条**算法量出来的外条
   外延线。判「这条线在不在外条最外沿上」。确认过的线就直接是金标值——外延这
   个口径能自动量准，缺的是有人认一遍，不是让人重新拖一条。

卡片 id 落 `cards.jsonl` **冻住**：重出一版页面照旧读它，否则 id 一变上一轮的
裁决就对不上号了。

跑法：
    python scripts/export_border_review_cards.py --sample 30 --jobs 8
    python scripts/export_border_review_cards.py --sample 30 --out output/border_review
原图路径用 GUJI_RAW 覆盖（默认 /home/user/rebuild_src）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from open_guji_cv.utils.border_geometry import detect_borders  # noqa: E402

RAW = Path(os.environ.get("GUJI_RAW", "/home/user/rebuild_src"))
PAGE_TYPE = ROOT.parent / "open-guji-dataset" / "page-type" / "expected.json"

PAGE_W = 660          # 列探测整页缩图宽
HEAD_W = 900          # 抬头带缩图宽（比整页宽，好让那条横带别太扁）
HEAD_UP, HEAD_DN = 250, 45     # 抬头带：上版框上方/下方各取多少 px
STRIP_W, STRIP_ZOOM = 480, 2   # 外延带：横向取多少 px、纵向放大几倍
STRIP_PAD = 42        # 外延带上下各留多少 px——留窄了看不出线是压在沿上还是进去了
JPEG_Q = 72


def _enc(img, q=JPEG_Q) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return buf.tobytes() if ok else b""


def _outer_edge(binm, L, w, h, xs, sign):
    """外条外延（半高交点）与峰值墨，量不到返回 (None, 0)。"""
    base = np.array([L.y_at((w - 1) - x) for x in xs])
    pr = {}
    for o in range(8, 121):
        yy = np.rint(base + o * sign).astype(int)
        ok = (yy >= 0) & (yy < h)
        pr[o] = float(binm[yy[ok], xs[ok]].mean()) if ok.any() else 0.0
    c = max(pr, key=pr.get)
    if pr[c] < 0.30:
        return None, pr[c]
    half = pr[c] / 2.0
    b = c
    while b + 1 in pr and pr[b + 1] >= half:
        b += 1
    if b + 1 not in pr:
        return float(b) * sign, pr[c]
    p0, p1 = pr[b], pr[b + 1]
    e = float(b) if p0 == p1 else b + (p0 - half) / (p0 - p1)
    return e * sign, pr[c]


def one_page(args) -> list[dict]:
    book, page = args
    gray = cv2.imread(str(RAW / book / f"{page}.tif"), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return []
    try:
        res = detect_borders(gray, expected_cols=9)
    except Exception:
        return []
    if not res.verticals or res.top is None or res.bottom is None:
        return []
    h, w = gray.shape
    binm = (gray < 128).astype(np.uint8)
    vx = sorted((w - 1) - v.x_at(h / 2.0) for v in res.verticals)
    xs = np.arange(int((w - 1) - vx[-1] + 20), int((w - 1) - vx[0] - 20), 2)
    if len(xs) < 50:
        return []
    out = []

    # ---- 1. 列探测：整页缩图 + 界行 ----
    sc = PAGE_W / w
    thumb = cv2.cvtColor(cv2.resize(gray, (PAGE_W, int(h * sc)), interpolation=cv2.INTER_AREA),
                         cv2.COLOR_GRAY2BGR)
    for V in res.verticals:
        for yy in range(0, thumb.shape[0], 3):
            y_old = yy / sc
            x = int(round(((w - 1) - V.x_at(y_old)) * sc))
            for dx in (0, 1):        # 画 2px 宽，1px 在缩图上几乎看不见
                if 0 <= x + dx < PAGE_W:
                    thumb[yy, x + dx] = (0, 40, 235)
    out.append(dict(kind="cols", id=f"cols:{book}:{page}", book=book, page=page,
                    n_cols=len(res.verticals), jpg=_enc(thumb, 74)))

    # ---- 2. 抬头带：上版框附近，不叠任何探测结果 ----
    ytop = int(res.top.y_at((w - 1) - w // 2))
    lo, hi = max(0, ytop - HEAD_UP), min(h, ytop + HEAD_DN)
    x0, x1 = int(xs[0]) - 30, int(xs[-1]) + 30
    if hi - lo > 60 and x1 - x0 > 200:
        band = gray[lo:hi, max(0, x0):min(w, x1)]
        band = cv2.resize(band, (HEAD_W, int(band.shape[0] * HEAD_W / band.shape[1])),
                          interpolation=cv2.INTER_AREA)
        out.append(dict(kind="head", id=f"head:{book}:{page}", book=book, page=page,
                        jpg=_enc(band, 76)))

    # ---- 3. 外框外延：上/下各一张，叠一条算法量出来的外延线 ----
    for kind, L, sign in (("top", res.top, -1.0), ("bottom", res.bottom, 1.0)):
        e, pk = _outer_edge(binm, L, w, h, xs, sign)
        if e is None:
            continue
        cx = (int(xs[0]) + int(xs[-1])) // 2 - STRIP_W // 2
        ymid = L.y_at((w - 1) - (cx + STRIP_W // 2))
        top_y = int(ymid + min(0, e) - STRIP_PAD)
        bot_y = int(ymid + max(0, e) + STRIP_PAD)
        if top_y < 0 or bot_y > h or cx < 0 or cx + STRIP_W > w:
            continue
        strip = cv2.cvtColor(gray[top_y:bot_y, cx:cx + STRIP_W], cv2.COLOR_GRAY2BGR)
        for i in range(STRIP_W):
            if (i // 11) % 2:
                continue
            y = int(round(L.y_at((w - 1) - (cx + i)) + e)) - top_y
            if 0 <= y < strip.shape[0]:
                strip[y, i] = (0, 40, 235)
        strip = cv2.resize(strip, (STRIP_W * STRIP_ZOOM, strip.shape[0] * STRIP_ZOOM),
                           interpolation=cv2.INTER_NEAREST)
        out.append(dict(kind="outer", id=f"outer:{book}:{page}:{kind}", book=book,
                        page=page, side=kind, offset=round(e, 2), peak=round(pk, 3),
                        jpg=_enc(strip, 80)))
    return out


def body_pages(books, sample):
    rows = json.loads(PAGE_TYPE.read_text(encoding="utf-8"))
    pages = [(r["book"], r["page"]) for r in rows
             if r["book"] in set(books) and r.get("page_type") == "body"]
    out = []
    for b in books:
        bp = [p for p in pages if p[0] == b]
        step = max(1, len(bp) // sample) if sample else 1
        out += bp[::step][:sample] if sample else bp
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--books", default="vol01,vol02")
    ap.add_argument("--sample", type=int, default=30, help="每册抽多少页正文页")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--out", default=str(ROOT / "output" / "border_review"))
    a = ap.parse_args()
    books = [b.strip() for b in a.books.split(",")]
    jobs = body_pages(books, a.sample)
    out = Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)
    print(f"探测 {len(jobs)} 页（{', '.join(books)}），{a.jobs} 并行…")
    cards = []
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for i, rs in enumerate(ex.map(one_page, jobs, chunksize=1), 1):
            for r in rs:
                jpg = r.pop("jpg")
                fn = r["id"].replace(":", "_") + ".jpg"
                (out / "img" / fn).write_bytes(jpg)
                r["img"] = fn
                cards.append(r)
            if i % 10 == 0:
                print(f"  {i}/{len(jobs)} 页，已出 {len(cards)} 张卡")
    # id 冻住：重出页面照旧读这个文件
    (out / "cards.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cards) + "\n", encoding="utf-8")
    n = {}
    for c in cards:
        n[c["kind"]] = n.get(c["kind"], 0) + 1
    sz = sum(f.stat().st_size for f in (out / "img").glob("*.jpg"))
    print(f"\n出卡 {len(cards)} 张：" + "、".join(f"{k} {v}" for k, v in sorted(n.items()))
          + f"　图片合计 {sz/1024/1024:.1f} MB")
    print(f"写出 {out}/cards.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
