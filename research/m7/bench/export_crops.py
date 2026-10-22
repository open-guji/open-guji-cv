"""字形判别台的数据底座：数据集 `labels/unified.jsonl` 里每个人裁刻形格（kind=shape、status=ok）配一张字块图。

已有图（`variant/*/crops`、`review/**`、`rr|ry|jys/crops`）直接用；没有的从中心库拉下的书
（`guji db pull` 后的 `feedback/`）按格找锚点：锚点带 `content_sha` 且 `anchor_patches/<册>/<sha前2>/<sha>.png` 在就用它
（与线上 Step4 字块同源），否则按锚点 bbox 从原图裁（`raw_page_px@top-right`，x'=W−1−x）再清边（同 `research/m7/lane1/build_whole_bank.clean`）。
输出 `<out>/<id 的 : 换 _>.png` 与 `<out>/index.jsonl`（id → 来源）。
用法：python export_crops.py <dataset char-groups 根> <feedback 根> <原图根(含 volNN/<页>.png)> <out>
"""
import glob
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lane1"))
from build_whole_bank import clean  # noqa: E402


def existing(root: Path) -> dict:
    out = {}
    for pat in ("variant/*/crops/*.png", "*/crops/*.png", "review/**/*.png"):
        for f in glob.glob(str(root / pat), recursive=True):
            out.setdefault(Path(f).stem, f)
    return out


def anchors(fb: Path) -> dict:
    out = {}
    for f in glob.glob(str(fb / "anchors" / "*.jsonl")):
        for line in open(f, encoding="utf-8"):
            try:
                x = json.loads(line)
            except ValueError:
                continue
            if x.get("anchor") and x.get("key"):
                out[x["key"]] = x["anchor"]
    for f in glob.glob(str(fb / "events" / "*.jsonl")):
        for line in open(f, encoding="utf-8"):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            t = e.get("target") or {}
            if t.get("key") and t.get("anchor"):
                out.setdefault(t["key"], t["anchor"])
    return out


def from_anchor(a: dict, key: str, fb: Path, raw: Path, cache: dict):
    book, page = key.split(":")[:2]
    sha = a.get("content_sha")
    pp = fb / "anchor_patches" / book / sha[:2] / f"{sha}.png" if sha else None
    if pp is not None and pp.exists():
        return cv2.imread(str(pp), cv2.IMREAD_GRAYSCALE), "anchor_patch"
    bb = a.get("bbox") or a.get("ink_bbox")
    if not bb:
        return None, None
    if (book, page) not in cache:
        cache.clear()
        cache[(book, page)] = cv2.imread(str(raw / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
    g = cache[(book, page)]
    if g is None:
        return None, None
    x0, y0, x1, y1 = bb
    w = g.shape[1]
    crop = g[max(0, int(y0)):int(y1), max(0, int(round(w - 1 - x1))):int(round(w - 1 - x0))]
    return (clean(crop), "raw_bbox") if crop.size else (None, None)


def main():
    root, fb, raw, out = (Path(x) for x in sys.argv[1:5])
    out.mkdir(parents=True, exist_ok=True)
    have, anc, cache = existing(root), anchors(fb), {}
    idx, miss = [], 0
    rows = sorted({json.loads(l)["id"] for l in open(root / "labels" / "unified.jsonl", encoding="utf-8")
                   if '"kind": "shape"' in l and '"status": "ok"' in l},
                  key=lambda k: [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in k.split(":")])
    for key in rows:
        stem = key.replace(":", "_")
        if stem in have:
            idx.append({"id": key, "src": "dataset:" + str(Path(have[stem]).relative_to(root))})
            continue
        g, src = from_anchor(anc[key], key, fb, raw, cache) if key in anc else (None, None)
        if g is None:
            miss += 1
            continue
        cv2.imwrite(str(out / f"{stem}.png"), g)
        idx.append({"id": key, "src": src})
    with open(out / "index.jsonl", "w", encoding="utf-8") as fh:
        for r in idx:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    from collections import Counter
    print("格", len(rows), "有图", len(idx), "缺", miss, Counter(r["src"].split(":")[0] for r in idx))


if __name__ == "__main__":
    main()
