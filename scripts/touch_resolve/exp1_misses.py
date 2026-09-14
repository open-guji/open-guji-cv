# -*- coding: utf-8 -*-
"""实验一的漏网分析：真字对没进 fused 5×5 假设集的用例——是切坏、磨损、异体还是标签错？

    python scripts/touch_resolve/exp1_misses.py

读 out/exp1/per_case.json，列出漏网条目（gold 切法下 fused rank>5 或 None 的侧），
并出一张对照图 out/exp1/misses.png：每行一个用例 = 双格窗口 + 两半 + 文字（真字 / top3）。
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from common import Loader, OUT_ROOT, half_patch, seam_gold, side_masks, window


def main() -> int:
    out = OUT_ROOT / "exp1"
    per = json.loads((out / "per_case.json").read_text(encoding="utf-8"))
    L = Loader()
    by_id = {it.id: it for it in L.gold_items(need_chars=True)}

    misses = []
    for r in per:
        rk = r["rank"]["gold"]
        bad = [side for side in ("above", "below") if (rk[f"fused_{side}"] is None or rk[f"fused_{side}"] > 5)]
        if bad:
            misses.append((r, bad))
    print(f"gold 切法下 fused@5 漏网 {len(misses)}/{len(per)} 条")

    # 异体归一（有就用）
    try:
        from open_guji_cv.clustering.variants import VariantMap
        vm = VariantMap.load()
        sem = lambda ch: vm.semantic(ch) or ch
    except Exception as e:  # noqa: BLE001
        print("VariantMap 不可用：", e)
        sem = lambda ch: ch

    rows = []
    n_variant_ok = 0
    for r, bad in misses:
        c, _ = L.resolve(by_id[r["id"]])
        if c is None:
            continue
        img = L.image_of(c)
        win, y0, _ = window(c, img)
        above, below = side_masks(win.shape, seam_gold(c), y0)
        halves = [half_patch(win, above), half_patch(win, below)]
        txt = []
        for side, truth in (("above", c.char_above), ("below", c.char_below)):
            tk = r["topk"]["gold"].get(side)
            preds = tk["fused"][:3] if tk else []
            flag = ""
            if side in bad and preds and any(sem(p) == sem(truth) for p in preds):
                flag = "≈异体"
                n_variant_ok += 1
            txt.append(f"{side[0]}:{truth}→{''.join(preds)}{flag}")
        rows.append((c, win, halves, " ".join(txt), r["verdict"]))
        print(f"  {c.id:18s} {r['verdict']:8s} {' | '.join(txt)}")
    print(f"其中 top3 里有异体等价字的侧：{n_variant_ok}")

    # 出图
    if rows:
        S = 1
        cell_h = max(max(win.shape[0] for _, win, _, _, _ in rows), 1) * S + 4
        tiles = []
        for c, win, halves, txt, verdict in rows:
            parts = [cv2.cvtColor(win, cv2.COLOR_GRAY2BGR)]
            for hp in halves:
                if hp is None:
                    hp = np.full((10, 10), 255, np.uint8)
                parts.append(cv2.cvtColor(hp, cv2.COLOR_GRAY2BGR))
            w_total = sum(p.shape[1] + 6 for p in parts) + 10
            tile = np.full((cell_h, w_total, 3), 220, np.uint8)
            x = 4
            for p in parts:
                tile[: p.shape[0], x: x + p.shape[1]] = p
                x += p.shape[1] + 6
            tiles.append((tile, f"{c.id} {verdict} {txt}"))
        W = max(t.shape[1] for t, _ in tiles) + 420
        sheet = np.full((sum(t.shape[0] for t, _ in tiles), W, 3), 255, np.uint8)
        y = 0
        from PIL import Image, ImageDraw, ImageFont
        pil = Image.fromarray(sheet)
        draw = ImageDraw.Draw(pil)
        font = None
        for fp in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simsun.ttc", str(Path(__file__).resolve().parents[2] / "fonts/iming/I.Ming-8.10.ttf")):
            try:
                font = ImageFont.truetype(fp, 16); break
            except Exception:
                continue
        for t, label in tiles:
            pil.paste(Image.fromarray(t), (0, y))
            draw.text((t.shape[1] + 8, y + 6), label, fill=(0, 0, 0), font=font)
            y += t.shape[0]
        pil.save(out / "misses.png")
        print(f"→ {out / 'misses.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
