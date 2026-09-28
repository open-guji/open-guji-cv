"""目标格 旧/新 图块对照。用法: patch_ab.py OUT.png id..."""
import sys, json, cv2, numpy as np
from pathlib import Path
import os
S = Path(os.environ.get("S266_DIR", "."))
def load(tag, pg):
    return json.loads((S / f"cs_{tag}" / f"p{pg:04d}.json").read_text())
def patch(tag, pg, col, slot):
    d = load(tag, pg)
    for c in d["columns"]:
        if c["col"] != col or not c["ok"]: continue
        for r in c["chars"]:
            if r["slot"] == slot and not r["sub"]:
                if not r["patch_key"]: return None, r
                f = S / f"cache_{tag}" / "vol03" / "char_patch" / f"{r['patch_key']}.png"
                return cv2.imread(str(f)), r
    return None, None
tiles = []
for t in sys.argv[2:]:
    pg, col, slot = map(int, t.split(":"))
    row = []
    for tag in ("base", "new"):
        im, r = patch(tag, pg, col, slot)
        tile = np.full((230, 200, 3), 255, np.uint8)
        if im is not None:
            h, w = im.shape[:2]; s = min(1.0, 200 / max(h, w)); im = cv2.resize(im, (max(1, int(w * s)), max(1, int(h * s))))
            tile[25:25 + im.shape[0], :im.shape[1]] = im
            cv2.rectangle(tile, (0, 25), (im.shape[1] - 1, 24 + im.shape[0]), (0, 160, 0) if tag == "new" else (0, 0, 220), 1)
        cv2.putText(tile, f"{t} {tag}", (2, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
        row.append(tile)
    tiles.append(np.hstack(row + [np.full((230, 20, 3), 255, np.uint8)]))
rows = [np.hstack(tiles[i:i + 4] + [np.full_like(tiles[0], 255)] * (4 - len(tiles[i:i + 4]))) for i in range(0, len(tiles), 4)]
cv2.imwrite(sys.argv[1], np.vstack(rows))
