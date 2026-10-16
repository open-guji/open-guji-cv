#!/usr/bin/env python3
"""叠图复核脚本化（GUJI-208bh，把 208av 的手工「A 档叠图复核」做成脚本）。

输入：格 id 清单（每行一个 `vol:page:col:slot`，夹注格末尾带 a/b，`#` 后是注释）、原图根目录、cell_table。
输出（`--out` 目录下）：
  叠图/<id>.png          每格一张：[原字块局部（红框）| 原字块放大 | 放行字字形 | 字形半透明叠在原字块上]
  联系页NN.png           每页 ≤24 格（`--per`），4 列
  整页/<册>_<页>.png     整页总览（`--page-overview`）：该页上所有被点名的格画红框并标序号，高 1800 px，供整页判读
  联系页.md              索引：序号、格、放行字、通道、verdict、cov、doubts、所在页
  结论回填.jsonl         一行一格：{"id","ruling","note"}，**ruling 初始全为 "unsure"**，由人或模型改成 ok|wrong|unsure
  看图简表.tsv           同一批格的 s8_vision.py 简表（cell/verdict/char/shown/group/note），要导入 vision-gate 时用它
  （`ruling` 与简表 `verdict` 同义：ok=放行字对，wrong=放行字错，unsure=看不出）

用法（用 cv 仓的 venv 跑，需 `import open_guji_cv`）：
  export GUJI_PRODUCTS_DIR=<沙箱>/products            # 必设沙箱；脚本只读 products，不写事件／裁决／字形库
  <cv>/.venv/bin/python overlay_review.py --ws <工作区> --cells cells.txt \\
      --raw-root <原图根目录> --cell-table vol04_base.jsonl.gz [--cell-table vol07_base.jsonl.gz ...] --out <输出目录>
  可选：--run-missing  产物缺的页，用 `guji pipeline keben_body_v2 <册> --to cell_shrink --pages …` 在沙箱现跑（要求设了 GUJI_PRODUCTS_DIR）
        --font <ttf>   指定放行字字体（缺省按顺序试 cv 仓 fonts/iming、jigmo，哪个有这个字用哪个）

约定：
  * 原图根目录下按 `<册>/<页>.png` 找；找不到再退回册配置的 raw_dir。
  * `bbox_page` 的 x 是镜像坐标（W−x），本脚本已翻回再叠（见 s8_vision.mirror_x；用 ink_ratio 核对过）。
  * cell_table（Ethan 基线副本）只有字／通道／verdict／cov／doubts，**没有 bbox**，所以 bbox 取 cell_shrink 产物；
    cell_table 里没有的格照出图，放行字留空。
  * 字形等比缩放进框（不拉伸）；说明文字用 PIL 画，汉字能显示。
  * 叠图是看图的辅助：红框位置是引擎 cell_shrink 的框，放行字字形是字体里的字，不是库里的刻本字形。
  * 不写事件、不碰 products（`--run-missing` 除外且只写 GUJI_PRODUCTS_DIR 沙箱）。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ID_RE = re.compile(r"^(?P<book>[^:]+):(?P<page>\d+):(?P<col>\d+):(?P<slot>-?\d+)(?P<sub>[ab])?$")
FONT_CANDIDATES = ("iming/I.Ming-8.10.ttf", "jigmo/Jigmo.ttf", "jigmo/Jigmo2.ttf", "jigmo/Jigmo3.ttf")


def parse_ids(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        t = line.split("#")[0].strip()
        if t:
            if not ID_RE.match(t):
                sys.exit(f"格 id 不合格式：{t!r}（要 vol04:50:9:3）")
            out.append(t)
    return out


def load_cell_table(paths: list[str]) -> dict[str, dict]:
    tab: dict[str, dict] = {}
    for p in paths:
        op = gzip.open if str(p).endswith(".gz") else open
        with op(p, "rt", encoding="utf-8") as f:
            for l in f:
                d = json.loads(l)
                if d.get("header") or "id" not in d:
                    continue
                tab[d["id"]] = d
    return tab


def mirror_x(bbox, width: int):
    """`bbox_page` 的 x 是镜像（W−x），翻回原图坐标。"""
    return [int(width - bbox[2]), int(bbox[1]), int(width - bbox[0]), int(bbox[3])]


def pick_font(ch: str, cv_dir: Path, forced: str | None):
    from fontTools.ttLib import TTFont
    cands = [forced] if forced else [str(cv_dir / "fonts" / c) for c in FONT_CANDIDATES]
    for fp in cands:
        if not fp or not Path(fp).exists():
            continue
        try:
            cmap = TTFont(fp, fontNumber=0, lazy=True).getBestCmap()
        except Exception:  # noqa: BLE001
            continue
        if ord(ch) in cmap:
            return fp
    return None


def render_glyph(ch: str, size: int, font_path: str | None):
    """白底黑字的方块字形图（灰度，size×size）；没有这个字返回 None。"""
    from PIL import Image, ImageDraw, ImageFont
    if not ch or not font_path:
        return None
    font = ImageFont.truetype(font_path, int(size * 0.9))
    im = Image.new("L", (size, size), 255)
    d = ImageDraw.Draw(im)
    bb = d.textbbox((0, 0), ch, font=font)
    d.text(((size - (bb[2] - bb[0])) / 2 - bb[0], (size - (bb[3] - bb[1])) / 2 - bb[1]), ch, font=font, fill=0)
    return np.array(im)


CAPTION_FONT: str | None = None  # main() 里按 fonts/iming 设；OpenCV 的 putText 画不了汉字，说明文字一律走 PIL


def put_text(img, text, org, scale=0.5, color=(255, 0, 0)):
    """在 BGR 图上写字（含汉字）。org 是左上角，scale 约等于字号/32。"""
    from PIL import Image, ImageDraw, ImageFont
    size = max(10, int(32 * scale))
    font = ImageFont.truetype(CAPTION_FONT, size) if CAPTION_FONT else ImageFont.load_default()
    im = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    ImageDraw.Draw(im).text((org[0], org[1] - size + 3), text, font=font, fill=(color[2], color[1], color[0]))
    img[:] = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def build_tile(raw_gray, box, siblings, meta, cid, font_path, h=300):
    """一格的四联图。box=[x0,y0,x1,y1]（原图坐标，已镜像回来）。"""
    H, W = raw_gray.shape
    x0, y0, x1, y1 = box
    pad = int(0.35 * max(x1 - x0, y1 - y0))
    cx0, cy0, cx1, cy1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
    ctx = cv2.cvtColor(raw_gray[max(0, y0 - 2 * (y1 - y0)):min(H, y1 + 2 * (y1 - y0)),
                                 max(0, x0 - (x1 - x0)):min(W, x1 + (x1 - x0))], cv2.COLOR_GRAY2BGR)
    oy, ox = max(0, y0 - 2 * (y1 - y0)), max(0, x0 - (x1 - x0))
    for s in siblings:  # 同列其它格：浅蓝
        cv2.rectangle(ctx, (s[0] - ox, s[1] - oy), (s[2] - ox, s[3] - oy), (255, 160, 0), 2)
    cv2.rectangle(ctx, (x0 - ox, y0 - oy), (x1 - ox, y1 - oy), (0, 0, 255), 3)
    crop = cv2.cvtColor(raw_gray[cy0:cy1, cx0:cx1], cv2.COLOR_GRAY2BGR)
    sub = crop.copy()
    cv2.rectangle(sub, (x0 - cx0, y0 - cy0), (x1 - cx0, y1 - cy0), (0, 0, 255), 2)
    ch = meta.get("char") or ""
    gl = render_glyph(ch, max(8, y1 - y0), font_path) if ch else None
    if gl is not None:  # 字形半透明（红）叠在原字块上，缩放到框大小
        # 字形是正方形；等比缩放到框内（不拉伸，免得把宽扁的「曰」压成窄高的「日」），居中叠
        side = max(8, min(x1 - x0, y1 - y0))
        g = cv2.resize(gl, (side, side), interpolation=cv2.INTER_AREA)
        ov = crop.copy()
        gx0, gy0 = x0 - cx0 + (x1 - x0 - side) // 2, y0 - cy0 + (y1 - y0 - side) // 2
        roi = ov[gy0:gy0 + side, gx0:gx0 + side]
        roi[g[:roi.shape[0], :roi.shape[1]] < 128] = (0, 0, 255)
        crop2 = cv2.addWeighted(ov, 0.55, crop, 0.45, 0)
        glyph_panel = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    else:
        crop2 = crop.copy()
        glyph_panel = np.full((max(8, y1 - y0), max(8, x1 - x0), 3), 235, np.uint8)
        put_text(glyph_panel, "no glyph" if ch else "-", (4, 16), 0.4, (0, 0, 160))
    fit = lambda im: cv2.resize(im, (max(1, int(im.shape[1] * h / im.shape[0])), h), interpolation=cv2.INTER_AREA)
    panels = [fit(ctx), fit(sub), fit(glyph_panel), fit(crop2)]
    row = np.hstack([np.hstack([p, np.full((h, 6, 3), 255, np.uint8)]) for p in panels])
    cap = np.full((46, row.shape[1], 3), 255, np.uint8)
    put_text(cap, f"{cid}  admit={ch or '-'}  ch={meta.get('channel') or '-'}  v={meta.get('verdict') or '-'}  cov={meta.get('cov')}", (4, 16), 0.5)
    put_text(cap, f"doubts={','.join(meta.get('doubts') or []) or '-'}  iron={meta.get('iron')}", (4, 36), 0.45, (90, 90, 90))
    return np.vstack([cap, row])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ws", required=True, help="工作区（含 books/<册>.yaml）")
    ap.add_argument("--cells", required=True, help="格 id 清单文件")
    ap.add_argument("--raw-root", help="原图根目录（<册>/<页>.png）；缺省用册配置的 raw_dir")
    ap.add_argument("--cell-table", action="append", default=[], help="cell_table jsonl(.gz)，可多个")
    ap.add_argument("--out", required=True)
    ap.add_argument("--per", type=int, default=24, help="每张联系页放几格（≤24）")
    ap.add_argument("--font")
    ap.add_argument("--run-missing", action="store_true")
    ap.add_argument("--page-overview", action="store_true", help="另出整页总览图（目录页等格号不可靠、要整页判读时用）")
    a = ap.parse_args(argv)
    if a.per > 24:
        sys.exit("--per 最大 24")
    ws = Path(a.ws).resolve()
    os.environ.setdefault("GUJI_WORKSPACE", str(ws))
    import open_guji_cv.steps  # noqa: F401  注册产物种类
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.store import ProductStore
    cv_dir = Path(sys.modules["open_guji_cv"].__file__).resolve().parents[1]
    global CAPTION_FONT
    CAPTION_FONT = a.font or str(cv_dir / "fonts" / "iming" / "I.Ming-8.10.ttf")

    ids = parse_ids(Path(a.cells))
    table = load_cell_table(a.cell_table)
    out = Path(a.out)
    (out / "叠图").mkdir(parents=True, exist_ok=True)
    st = ProductStore()
    books: dict[str, object] = {}

    def book_of(b):
        if b not in books:
            books[b] = load_book(b)
        return books[b]

    def char_index(b, p):
        return st.read(b, "cell_shrink", page_key(p), "char_index")

    if a.run_missing:
        if not os.environ.get("GUJI_PRODUCTS_DIR"):
            sys.exit("--run-missing 要先设 GUJI_PRODUCTS_DIR（沙箱），不写正式 products/")
        need: dict[str, set[int]] = {}
        for cid in ids:
            m = ID_RE.match(cid)
            if char_index(m["book"], int(m["page"])) is None:
                need.setdefault(m["book"], set()).add(int(m["page"]))
        for b, pages in need.items():
            cmd = [sys.executable, "-m", "open_guji_cv.cli_v2", "pipeline", "keben_body_v2", b, "--to", "cell_shrink",
                   "--pages", ",".join(map(str, sorted(pages))), "-w", str(ws), "--jobs", "2"]
            print("$", " ".join(cmd), flush=True)
            subprocess.run(cmd, check=False, env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    tiles, rows, fails = [], [], []
    img_cache: dict = {}
    for cid in ids:
        m = ID_RE.match(cid)
        b, p, col, slot, sub = m["book"], int(m["page"]), int(m["col"]), int(m["slot"]), m["sub"] or ""
        meta = table.get(cid, {})
        ci = char_index(b, p)
        cc = ci.column(col) if ci else None
        tgt = next((c for c in (cc.chars if cc else []) if c.slot == slot and (c.sub or "") == sub), None)
        if tgt is None:
            fails.append((cid, "没有 cell_shrink 产物或没有这一格（加 --run-missing 现跑）"))
            continue
        if (b, p) not in img_cache:
            cand = [Path(a.raw_root) / b / f"{p}.png"] if a.raw_root else []
            cand.append(Path(book_of(b).raw_path(p)))
            img = next((cv2.imread(str(c), cv2.IMREAD_GRAYSCALE) for c in cand if c.exists()), None)
            img_cache[(b, p)] = img
        raw = img_cache[(b, p)]
        if raw is None:
            fails.append((cid, "原图读不出来"))
            continue
        W = raw.shape[1]
        box = mirror_x(tgt.bbox_page, W)
        sib = [mirror_x(c.bbox_page, W) for c in cc.chars if c is not tgt]
        ch = meta.get("char") or ""
        font = pick_font(ch, cv_dir, a.font) if ch else None
        tile = build_tile(raw, box, sib, meta, cid, font)
        cv2.imwrite(str(out / "叠图" / (cid.replace(":", "_") + ".png")), tile)
        tiles.append((cid, tile, meta, p))
        # 自检：镜像翻回后的框，原图里的墨量应≈产物记录的 ink_ratio；差太多说明框没叠对地方
        ink_raw = float((raw[box[1]:box[3], box[0]:box[2]] < 128).mean())
        ink_rec = float(tgt.ink_ratio)
        notes = []
        if abs(ink_raw - ink_rec) > 0.03:
            notes.append(f"⚠ 墨量对不上（记录 {ink_rec:.3f}／原图 {ink_raw:.3f}），框可能没叠对")
        if ch and not font:
            notes.append("字体里没有该字")
        rows.append((cid, meta, p, "；".join(notes), box, ink_rec, ink_raw))

    if a.page_overview:
        (out / "整页").mkdir(exist_ok=True)
        bypage: dict = {}
        for k, (cid, meta, p, note, box, ink_rec, ink_raw) in enumerate(rows):
            m = ID_RE.match(cid)
            bypage.setdefault((m["book"], p), []).append((k + 1, cid, box, meta))
        for (b, p), items in bypage.items():
            raw = img_cache.get((b, p))
            if raw is None:
                continue
            vis = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
            for n, cid, box, meta in items:
                cv2.rectangle(vis, (box[0], box[1]), (box[2], box[3]), (0, 0, 255), 5)
                put_text(vis, str(n), (box[0] + 4, max(40, box[1] - 4)), 1.4, (255, 0, 0))
            H, W = vis.shape[:2]
            cv2.imwrite(str(out / "整页" / f"{b}_{p}.png"), cv2.resize(vis, (int(W * 1800 / H), 1800), interpolation=cv2.INTER_AREA))

    # 联系页：每页 ≤per 格，4 列
    sheets = []
    for si in range(0, len(tiles), a.per):
        chunk = tiles[si:si + a.per]
        w = max(t[1].shape[1] for t in chunk)
        pad = lambda im: np.hstack([im, np.full((im.shape[0], w - im.shape[1], 3), 255, np.uint8)]) if im.shape[1] < w else im
        cols = 2  # 四联图本身很宽，一行放 2 格
        lines = []
        for r in range(0, len(chunk), cols):
            seg = [pad(t[1]) for t in chunk[r:r + cols]]
            while len(seg) < cols:
                seg.append(np.full_like(seg[0], 255))
            lines.append(np.hstack(seg))
        name = f"联系页{si // a.per + 1:02d}.png"
        cv2.imwrite(str(out / name), np.vstack(lines))
        sheets.append(name)

    md = [f"# 叠图复核联系页（{len(tiles)}/{len(ids)} 格成图，{len(sheets)} 页）", "",
          "每格四联图：原字块局部（红框＝目标格，浅蓝＝同列其它格）｜原字块放大｜放行字字形｜字形半透明叠在原字块上。", "",
          "| 序号 | 格 | 联系页 | 放行字 | 通道 | verdict | cov | doubts | 框（原图坐标） | ink 记录／原图 | 备注 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, (cid, meta, p, note, box, ink_rec, ink_raw) in enumerate(rows):
        md.append(f"| {k + 1} | `{cid}` | {sheets[k // a.per]} | {meta.get('char') or ''} | {meta.get('channel') or ''} | "
                  f"{meta.get('verdict') or ''} | {meta.get('cov') if meta.get('cov') is not None else ''} | {','.join(meta.get('doubts') or [])} | {box} | {ink_rec:.3f}／{ink_raw:.3f} | {note} |")
    for cid, why in fails:
        md.append(f"| — | `{cid}` | — | | | | | | | | ⚠ {why} |")
    (out / "联系页.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    with (out / "结论回填.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for cid, meta, p, note, *_ in rows:
            f.write(json.dumps({"id": cid, "ruling": "unsure", "note": ""}, ensure_ascii=False) + "\n")
    with (out / "看图简表.tsv").open("w", encoding="utf-8", newline="") as f:
        w_ = csv.writer(f, delimiter="\t", lineterminator="\n")
        w_.writerow(["cell", "verdict", "char", "shown", "group", "note"])
        for cid, meta, p, note, *_ in rows:
            w_.writerow([cid, "unsure", "", meta.get("char") or "", "", ""])
    print(f"叠图 {len(tiles)}/{len(ids)} 格，{len(sheets)} 页联系页 → {out}")
    for cid, why in fails:
        print(f"⚠ {cid}：{why}", file=sys.stderr)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
