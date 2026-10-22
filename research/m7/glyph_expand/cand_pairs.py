"""补采样候选格：整册产物里，seed_admit 字／库候选／整理本对位字任一落在某对字里、且数据集还没有人裁的格。

用法：python cand_pairs.py <产物根> <原图根> <dataset unified.jsonl> <输出目录> 蒙𫎇 點㸃 …
输出 `<输出目录>/cands.json`（每格：id、对、seed 字、库前二、整理本字、是否放行）和 `crops/<id>.png`。
"""
import glob
import json
import sys
from pathlib import Path

import cv2

from open_guji_cv.core.anchor import crop_patch


def gather(prod: Path, imgs: Path, pairs, labeled: set, out: Path):
    (out / "crops").mkdir(parents=True, exist_ok=True)
    rows = []
    for vd in sorted(glob.glob(str(prod / "vol*"))):
        book = Path(vd).name
        pages = sorted(glob.glob(f"{vd}/{book}/seed_admit/p*.json"))
        for f in pages:
            page = int(Path(f).stem[1:])
            sa = {r["id"]: r for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"] for r in col["chars"]}
            ar = {}
            p = f"{vd}/{book}/align_ref/p{page:04d}.json"
            if Path(p).exists():
                ar = {c["id"]: c.get("align_char") for c in json.load(open(p, encoding="utf-8"))["align_ref"]["chars"]}
            gm = {}
            p = f"{vd}/{book}/glyph_match/p{page:04d}.json"
            if Path(p).exists():
                gm = {c["id"]: [x[0] for x in c.get("candidates", [])[:2]] for col in json.load(open(p, encoding="utf-8"))["glyph_match"]["columns"] for c in col["chars"]}
            hits = []
            for cid, r in sa.items():
                if cid in labeled:
                    continue
                for pr in pairs:
                    if any(c and c in pr for c in (r["char"], ar.get(cid), *gm.get(cid, []))):
                        hits.append((cid, pr, r))
            if not hits:
                continue
            cs = json.load(open(f"{vd}/{book}/cell_shrink/p{page:04d}.json", encoding="utf-8"))["char_index"]["columns"]
            box = {ch["id"]: ch["bbox_page"] for col in cs for ch in col["chars"]}
            img = cv2.imread(str(imgs / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
            for cid, pr, r in hits:
                if box.get(cid) is None:
                    continue
                g = crop_patch(img, tuple(box[cid]))
                if g is None:
                    continue
                cv2.imwrite(str(out / "crops" / (cid.replace(":", "_") + ".png")), g)
                rows.append({"id": cid, "pair": pr, "seed": r["char"], "admit": r["admit"], "ref": ar.get(cid), "top2": gm.get(cid, [])})
    return rows


if __name__ == "__main__":
    prod, imgs, uni, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
    labeled = {json.loads(l)["id"] for l in open(uni, encoding="utf-8") if json.loads(l).get("form")}
    rows = gather(prod, imgs, sys.argv[5:], labeled, out)
    (out / "cands.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    print(len(rows), Counter((r["pair"], r["seed"], r["ref"]) for r in rows).most_common(40))
