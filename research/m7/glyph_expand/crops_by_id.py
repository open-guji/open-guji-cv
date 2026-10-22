"""按格 id 从整册产物＋原图裁字块，拼成带标号的大图，便于看图。
用法：python crops_by_id.py <产物根> <原图根> <ids 用逗号分隔> <输出 png> [放大倍数]"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.core.anchor import crop_patch


def crop(prod: Path, imgs: Path, cid: str):
    book, page = cid.split(":")[:2]
    cs = json.load(open(prod / book / book / "cell_shrink" / f"p{int(page):04d}.json", encoding="utf-8"))["char_index"]["columns"]
    box = {ch["id"]: ch["bbox_page"] for col in cs for ch in col["chars"]}
    if cid not in box:
        return None
    return crop_patch(cv2.imread(str(imgs / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE), tuple(box[cid]))


def montage(patches, labels, cols=7, cell=120):
    rows = []
    for i in range(0, len(patches), cols):
        row = []
        for p, l in zip(patches[i:i + cols], labels[i:i + cols]):
            c = np.full((cell + 16, cell), 255, np.uint8)
            if p is not None:
                s = min((cell - 4) / p.shape[0], (cell - 4) / p.shape[1])
                q = cv2.resize(p, (max(1, int(p.shape[1] * s)), max(1, int(p.shape[0] * s))))
                c[16:16 + q.shape[0], 2:2 + q.shape[1]] = q
            cv2.putText(c, l[-14:], (2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.35, 0, 1)
            row.append(c)
        while len(row) < cols:
            row.append(np.full((cell + 16, cell), 255, np.uint8))
        rows.append(np.hstack(row))
    return np.vstack(rows)


if __name__ == "__main__":
    prod, imgs, ids, out = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].split(","), sys.argv[4]
    ps = [crop(prod, imgs, i) for i in ids]
    cv2.imwrite(out, montage(ps, ids))
