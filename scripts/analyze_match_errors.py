# -*- coding: utf-8 -*-
"""5a same 档错例归因拼图（A23 2026-11-06）：每个错例一行——查询图 | 判成的字的库内最像刻例 ×2 | 金标字的库内最像刻例 ×2，
并打出各刻例的 provenance（admissions）、近似标记，方便看是「金标标错」「库标错」「同形异码」「真形近」还是「图本身有问题」。

    python scripts/analyze_match_errors.py <分片> <glyph.db> <rows.jsonl> <out.png> [<out.json>]
"""
import json
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_match_bench import build_matcher  # noqa: E402

FONT = Path(__file__).resolve().parents[1] / "fonts" / "iming" / "I.Ming-8.10.ttf"
S = 4  # 64px → 256px


def tile(img, label, w=S * 64):
    im = Image.fromarray(255 - (img * 255).astype(np.uint8)).resize((w, w), Image.NEAREST).convert("RGB")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w - 1, w - 1], outline=(180, 180, 180))
    d.text((3, 2), label, fill=(200, 0, 0), font=ImageFont.truetype(str(FONT), 18))
    return im


def main():
    shard, db, rows_path, out_png = sys.argv[1:5]
    out_json = sys.argv[5] if len(sys.argv) > 5 else None
    rows = [json.loads(x) for x in open(rows_path, encoding="utf-8")]
    errs = [r for r in rows if r["variant"] == "orig" and r["verdict"] == "same" and r["char"] != r["gold"]]
    ds = Path("../open-guji-dataset/char-clustering/samples") / shard
    exp = {x["instance_id"]: x for x in json.loads((ds / "expected.json").read_text(encoding="utf-8"))["instances"]}
    m, _ = build_matcher(db)
    full = getattr(m, "_full", m)
    L = np.asarray(full.library_matrix(), dtype=np.float32)
    con = sqlite3.connect(db)

    def prov(iid):
        r = con.execute("select provenance,evidence from admissions where instance_id=?", (iid,)).fetchone()
        a = con.execute("select label,note from approx_labels where instance_id=?", (iid,)).fetchone()
        return {"prov": r[0] if r else None, "approx": a[0] if a else None}

    Fnt = ImageFont.truetype(str(FONT), 20)
    sheet, info = [], []
    for r in errs:
        x = exp[r["id"]]
        q = (cv2.imread(str(ds / x["crop"]), 0) > 127).astype(np.uint8)
        feat = full._feature.extract(q[None, ...])[0]
        sims = L @ np.asarray(feat, dtype=np.float32)
        for j in full._same_cell_rows(r["id"]):
            sims[j] = -np.inf
        pic = {}
        for role, ch in (("判成", r["char"]), ("金标", r["gold"])):
            idx = [j for j in np.argsort(-sims)[:3000] if full._chars[j] == ch and not str(full._ids[j]).startswith("font:")][:2]
            pic[role] = idx
        tiles = [tile(q, f'查询 金标「{r["gold"]}」')]
        rec = {"id": r["id"], "gold": r["gold"], "claim": r["char"], "via": r["via"], "cov": r["cov"],
               "flags": r["flags"], "sc_flag": r["sc_flag"], "query_prov": prov(r["id"]), "ex": {}}
        for role in ("判成", "金标"):
            for j in pic[role]:
                iid = full._ids[j]
                p = prov(iid)
                tiles.append(tile(full._patches[j].astype(np.uint8), f'{role}「{full._chars[j]}」{p["prov"] or ""}'))
                rec["ex"].setdefault(role, []).append({"id": iid, **p})
            for _ in range(2 - len(pic[role])):
                tiles.append(Image.new("RGB", (S * 64, S * 64), (240, 240, 240)))
        row = Image.new("RGB", (S * 64 * 5 + 300, S * 64), (255, 255, 255))
        for k, t in enumerate(tiles):
            row.paste(t, (k * S * 64, 0))
        ImageDraw.Draw(row).text((S * 64 * 5 + 6, 6), f'{r["id"]}\n{r["via"] or "matcher"} cov{r["cov"]}\n{",".join(r["flags"])}\n{r["sc_flag"]}', fill=(0, 0, 0), font=Fnt)
        sheet.append(row)
        info.append(rec)
    H = sum(i.height for i in sheet)
    img = Image.new("RGB", (sheet[0].width, H), (255, 255, 255)) if sheet else None
    y = 0
    for row in sheet:
        img.paste(row, (0, y)); y += row.height
    if img:
        img.save(out_png)
    if out_json:
        Path(out_json).write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(errs), "errors →", out_png)


if __name__ == "__main__":
    main()
