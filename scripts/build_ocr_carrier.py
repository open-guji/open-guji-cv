"""生成 OCR 对齐载体：逐图块 RapidOCR top-1 + s2t → carrier jsonl。

**为什么需要它**：整理本对齐要一份「大致正确」的页文本把页锚到语料位置。
以前用 phase6 转写当载体，但 881d777 的全流程重跑没带 OCR 源，新转写
全是 `<unk>`——切分一重跑载体就作废。本脚本直接对当前 phase4 图块跑
RapidOCR（PP-OCRv4 ONNX，模型随包分发、离线可用），使载体与切分**永远
同版**，对齐标注不再被 label 步骤的重跑节奏卡住。

载体只求「够锚定」不求全对（n-gram 投票对噪声鲁棒）。G5 在 book9 金标
上的实测：rapidocr top1 + s2t 88.75%——比旧转写载体（86.4%）还高。
s2t 用 opencc 逐字转换：PP-OCR 是简体模型，语料是传承字形，不转的话
说/說 这类全算 miss，锚定窗口白白变碎。

**单进程顺序跑**：4 核环境实测单进程 ~21ms/块（onnxruntime 内部已并
行），多进程互相踩踏反而慢一个量级。支持断点续跑（追加写，已有 id 跳过）。

    python scripts/build_ocr_carrier.py vol01 --out carrier_vol01.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("--output", default="output")
    ap.add_argument("--page-type", default="../open-guji-dataset/page-type/expected.json")
    ap.add_argument("--pages", default="body",
                    help="body=只跑金标正文页；all=全书")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import cv2
    import opencc

    from open_guji_cv.clustering.candidates import RapidOcrSource

    root = Path(args.output) / args.book / "phase4_chars"
    pages = None
    if args.pages == "body":
        gold = json.loads(Path(args.page_type).read_text(encoding="utf-8"))
        pages = {g["page"] for g in gold
                 if g["book"] == args.book and g["page_type"] == "body"}

    out_path = Path(args.out)
    done: set[str] = set()
    if out_path.exists():                     # 断点续跑
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["id"])

    jobs = []
    with open(root / "index.jsonl", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if pages is not None and r["page"] not in pages:
                continue
            if r["id"] in done:
                continue
            jobs.append((r["id"], str(root / r["patch_path"])))
    print(f"{args.book}: 待跑 {len(jobs)} 块（已完成 {len(done)}）", flush=True)

    src = RapidOcrSource()
    src._ensure()
    cc = opencc.OpenCC("s2t")

    with open(out_path, "a", encoding="utf-8") as f:
        for n, (rec_id, patch_path) in enumerate(jobs, 1):
            gray = cv2.imread(patch_path, cv2.IMREAD_GRAYSCALE)
            if gray is None:
                continue
            topk = src.rec_topk(gray)
            if not topk:
                row = {"id": rec_id, "char": "", "prob": 0.0}
            else:
                ch, prob = topk[0]
                row = {"id": rec_id, "char": cc.convert(ch)[:1] or ch,
                       "prob": round(prob, 4)}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if n % 5000 == 0:
                f.flush()
                print(f"  {n}/{len(jobs)}", flush=True)
    print(f"→ {out_path}")


if __name__ == "__main__":
    main()
