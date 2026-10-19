# -*- coding: utf-8 -*-
"""逐格识别：Step4 字块小图 → rapidocr 识别 top1，作「整理本不分行」对位的载体串。

    <装了 rapidocr-onnxruntime 的 python> cell_ocr.py --ws <沙箱工作区> --vol vol04 --out ocr_vol04.jsonl

只认 cell_type ≠ empty、有 patch_key 的格。一行一格：{"id", "ch", "score"}；识别不出 ch 为 ""。
生产里对位用的是 Step5 的字形库候选（`align_ref.slots_from_evidence`）。云端没有字形库，这里用通用 OCR 代替。
通用 OCR 认古籍刻本更差，所以这里的对位结果偏保守。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
from rapidocr_onnxruntime import RapidOCR


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws", required=True)
    ap.add_argument("--vol", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch", type=int, default=64)
    a = ap.parse_args()
    ws = Path(a.ws)
    eng = RapidOCR()
    patches = ws / "cache" / a.vol / "char_patch"
    todo = []
    for f in sorted((ws / "products" / a.vol / "cell_shrink").glob("p*.json")):
        for col in json.loads(f.read_text(encoding="utf-8"))["char_index"]["columns"]:
            for c in col["chars"]:
                if c.get("cell_type") != "empty" and c.get("patch_key"):
                    todo.append((c["id"], patches / f"{c['patch_key']}.png"))
    with open(a.out, "w", encoding="utf-8") as out:
        for i in range(0, len(todo), a.batch):
            chunk = todo[i:i + a.batch]
            imgs = [cv2.imread(str(p)) for _, p in chunk]
            ok = [j for j, im in enumerate(imgs) if im is not None]
            res, _ = eng.text_rec([imgs[j] for j in ok]) if ok else ([], 0)
            got = {ok[k]: r for k, r in enumerate(res)}
            for j, (cid, _) in enumerate(chunk):
                t, s = got.get(j, ("", 0.0))
                out.write(json.dumps({"id": cid, "ch": t[:1], "score": round(float(s), 3)}, ensure_ascii=False) + "\n")
    print(f"{len(todo)} 格 → {a.out}")


if __name__ == "__main__":
    main()
