"""切线金标坐标整体平移：Step2 列窗上界变了，把金标搬到当前坐标系。

**为什么能整体平移**（2026-09-19，vol02 实测 1674 列，零例外）：
`refine_top_by_frame`（`94f1a67f1d`，Step2 列窗上界按版框修正）只动 `top_y`，
`bottom_y` 一条没动，且「列图高度增量 == top_y 上移量」逐列成立。列图是从
`top_y` 起裁的，所以旧坐标系里的 y 换到新坐标系就是

    y_new = y_old + (col_h_new - col_h_old)

—— 一个纯平移，不需要人重裁。这跟 2026-09-14 那次不同：那次列图是被下版框余量、
三段折线等多处重矫正，形变不是单一平移，只能靠控制台 drift 档一张张重判
（见 overview `进度/Step3-逐字切分/09-切线金标坐标过期重标.md`）。

**用之前必须先验**（`--check`）：脚本会逐条量「平移后落点的墨比平移前干净吗」。
更脏的条目会单独列出来——`seam_ok` 带折线的条目 y 只是折线的代表点，墨读数本来
就飘，少量更脏是正常的；但如果大批更脏，说明形变不是纯平移，**不要用这个脚本**。

用法：
    python scripts/reshift_cutline_gold.py --book vol02 --check      # 只看，不写
    python scripts/reshift_cutline_gold.py --book vol02 --apply      # 写回 items.jsonl
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import cv2

SHARD = Path(r"D:\workspace\open-guji-dataset\char-segmentation\touching-cuts\items.jsonl")
#: 切线几何字段是一次判定的整体（同 `consumers.CUTLINE_KEYS` 的纪律）：
#: 平移要么全改、要么都不改，不能只改 y 留下旧折线——2026-09-14 吃过这个亏。
GEOM_KEYS = ("y", "y_old", "polyline", "col_h")


def col_image(workspace: Path, book: str, page: int, col: int) -> Path:
    return workspace / "cache" / book / "column_image" / f"p{page:04d}c{col:02d}.png"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--workspace", default=r"D:\workspace\siku-zongmu-workspace")
    ap.add_argument("--shard", default=str(SHARD))
    ap.add_argument("--apply", action="store_true", help="真的写回（默认只看）")
    ap.add_argument("--max-shift", type=float, default=80.0,
                    help="单条位移超过这个值就拒绝（防止对上了错的列图）")
    ap.add_argument("--pages", default="",
                    help="只平移这些页（如 1-30）。**只该填这一轮真重跑过的页**——"
                         "别的页上的漂移是别的轮次留下的，成因不同，不能套这个纯平移假设。")
    a = ap.parse_args()
    ws = Path(a.workspace)
    shard = Path(a.shard)

    want_pages: set[int] | None = None
    if a.pages:
        want_pages = set()
        for part in a.pages.split(","):
            if "-" in part:
                lo, hi = part.split("-"); want_pages |= set(range(int(lo), int(hi) + 1))
            else:
                want_pages.add(int(part))

    lines = [json.loads(ln) for ln in shard.read_text(encoding="utf-8").splitlines() if ln.strip()]
    heights: dict[tuple[int, int], int | None] = {}
    todo, skip_no_img, skip_no_geom, too_big = [], 0, 0, []
    for o in lines:
        an = o.get("anchor", {})
        if an.get("book") != a.book:
            continue
        if want_pages is not None and an.get("page") not in want_pages:
            continue
        ex = o.get("expected", {})
        if "col_h" not in ex or "y" not in ex:
            skip_no_geom += 1
            continue
        key = (an["page"], an["col"])
        if key not in heights:
            p = col_image(ws, a.book, *key)
            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None
            heights[key] = None if img is None else int(img.shape[0])
        h = heights[key]
        if h is None:
            skip_no_img += 1
            continue
        d = h - int(ex["col_h"])
        if d == 0:
            continue
        if abs(d) > a.max_shift:
            too_big.append((o["id"], d))
            continue
        todo.append((o, d, h))

    print(f"{a.book}: 待平移 {len(todo)} 条；无图 {skip_no_img}；无坐标(A/B 盲裁) {skip_no_geom}；"
          f"位移超 {a.max_shift:.0f}px 拒绝 {len(too_big)}")
    if too_big:
        print("  拒绝的:", too_big[:10])

    # 验：平移后落点是不是更干净
    better = worse = same = 0
    worse_rows = []
    profs: dict[tuple[int, int], object] = {}
    for o, d, h in todo:
        an = o["anchor"]; ex = o["expected"]
        key = (an["page"], an["col"])
        if key not in profs:
            img = cv2.imread(str(col_image(ws, a.book, *key)), cv2.IMREAD_GRAYSCALE)
            profs[key] = (img < 128).mean(axis=1) if img is not None else None
        prof = profs[key]
        if prof is None:
            continue
        yo, yn = int(round(ex["y"])), int(round(ex["y"] + d))
        io_ = float(prof[yo]) if 0 <= yo < len(prof) else -1.0
        inew = float(prof[yn]) if 0 <= yn < len(prof) else -1.0
        if inew < io_ - 0.005:
            better += 1
        elif inew > io_ + 0.005:
            worse += 1
            worse_rows.append((o["id"], d, round(io_, 3), round(inew, 3),
                               ex.get("verdict"), "polyline" in ex))
        else:
            same += 1
    print(f"验：平移后更干净 {better} / 更脏 {worse} / 不变 {same}")
    for r in worse_rows[:15]:
        print("   更脏:", r)

    if not a.apply:
        print("\n（只看模式。确认无误后加 --apply 写回）")
        return 0

    bak = shard.with_suffix(f".jsonl.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(shard, bak)
    print(f"\n已备份 → {bak}")

    ids = {id(o): d for o, d, _ in todo}
    hh = {id(o): h for o, _, h in todo}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    for o in lines:
        d = ids.get(id(o))
        if d is None:
            continue
        ex = o["expected"]
        ex["y"] = float(ex["y"]) + d
        if "y_old" in ex and ex["y_old"] is not None:
            ex["y_old"] = float(ex["y_old"]) + d
        if "polyline" in ex and ex["polyline"]:
            ex["polyline"] = [[x, y + d] for x, y in ex["polyline"]]
        ex["col_h"] = hh[id(o)]
        o.setdefault("history", []).append(
            {"change": "reshift", "ts": now,
             "why": f"Step2 列窗上界变动，坐标整体平移 {d:+d}px（reshift_cutline_gold.py）"})
        n += 1
    shard.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in lines) + "\n",
                     encoding="utf-8")
    print(f"已写回 {n} 条 → {shard}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
