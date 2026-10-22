"""字形判法扩面：从整册产物里收「seed_admit 当前字落在某对字里」的格（放行与未放行都收），裁字块（同 `long_tail/build_bank.gather`）。

用法：python pool.py <产物根，含 volNN/volNN/> <原图根 data_full/zongmu> <字，如 衛衞> <输出 json>
输出每格：id 册 当前字 是否放行 通道 疑点；字块图另存 `<输出>.d/<id 的 : 换 _>.png`。
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import cv2

from open_guji_cv.core.anchor import crop_patch


def gather(prod: Path, imgs: Path, chars: str, out: Path | None = None):
    rows = []
    for vd in sorted(glob.glob(str(prod / "vol*"))):
        book = Path(vd).name
        by_page: dict = {}
        for f in glob.glob(f"{vd}/{book}/seed_admit/p*.json"):
            for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
                for r in col["chars"]:
                    if r["char"] and r["char"] in chars:
                        by_page.setdefault(int(Path(f).stem[1:]), []).append(r)
        for page, rs in sorted(by_page.items()):
            cs = json.load(open(f"{vd}/{book}/cell_shrink/p{page:04d}.json", encoding="utf-8"))["char_index"]["columns"]
            box = {ch["id"]: ch["bbox_page"] for col in cs for ch in col["chars"]}
            img = cv2.imread(str(imgs / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
            for r in rs:
                if box.get(r["id"]) is None:
                    continue
                g = crop_patch(img, tuple(box[r["id"]]))
                if g is None:
                    continue
                if out is not None:
                    cv2.imwrite(str(out / (r["id"].replace(":", "_") + ".png")), g)
                rows.append({"id": r["id"], "book": book, "char": r["char"], "admit": r["admit"],
                             "channel": r["channel"], "doubts": r["doubts"]})
    return rows


if __name__ == "__main__":
    prod, imgs, chars, dst = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
    d = dst.with_suffix(".d")
    d.mkdir(parents=True, exist_ok=True)
    rows = gather(prod, imgs, chars, d)
    dst.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    print(len(rows), Counter((r["char"], r["admit"]) for r in rows))
