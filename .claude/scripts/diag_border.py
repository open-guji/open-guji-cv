#!/usr/bin/env python3
"""边框检测诊断脚本：分析指定页面的水平线聚类情况。

用法：
    python .claude/scripts/diag_border.py 1 31
    python .claude/scripts/diag_border.py 1 31,32,35
"""
import os, sys, argparse
import cv2, numpy as np
from pathlib import Path

os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from open_guji_cv.profile import BookProfile
from open_guji_cv.preprocessors import get_preprocessors
from open_guji_cv.detectors.lines import LineDetector
from border_detect import cluster_lines

PROFILE = BookProfile.from_dict({
    "color_mode": "bw", "page_type": "cut_half",
    "lines_per_page": 8, "border_style": "double",
    "border_wear": "medium", "chars_per_line": 21,
    "has_marginal_notes": False,
})
CE_DIRS = {
    1: "06064237.cn", 2: "06064238.cn", 3: "06064239.cn", 4: "06064240.cn",
    5: "06064241.cn", 6: "06064242.cn", 7: "06064243.cn", 8: "06064244.cn",
    9: "06064245.cn", 10: "06064246.cn",
}
WSL_BASE = Path("//wsl.localhost/Ubuntu/home/lishaodong/workspace/guji-resource")
BOOK = "欽定四庫全書簡明目錄·文淵閣本"

def diag_page(ce_num, page_num):
    img_dir = WSL_BASE / BOOK / "01_初始化" / "images" / CE_DIRS[ce_num] / "images"
    for f in sorted(img_dir.iterdir()):
        if f.suffix.lower() not in {".jpg", ".jpeg", ".png"}: continue
        try:
            pn = int(f.stem.split("_")[-1])
        except ValueError:
            continue
        if pn != page_num: continue
        
        buf = np.frombuffer(f.read_bytes(), dtype=np.uint8)
        image = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        
        pps = get_preprocessors(PROFILE)
        imgs = [image]
        for pp in pps:
            nxt = []
            for img in imgs:
                r = pp.process(img, PROFILE)
                nxt.extend(sub for _, sub in r) if isinstance(r, list) else nxt.append(r)
            imgs = nxt
        proc = imgs[0]
        h, w = proc.shape[:2]
        
        ld = LineDetector()
        lsd = ld.detect(proc)
        hlines = [ln for ln in lsd["lines"] if ln["type"] == "horizontal"]
        clusters = cluster_lines(hlines, "h", 15, 60)
        
        print(f"\n=== ce{ce_num:02d} page {page_num} | img: {h}x{w} ===")
        print(f"水平线: {len(hlines)} 条 → {len(clusters)} 聚类")
        cands = [c for c in clusters if c["total_length"] / w >= 0.3]
        print(f"候选(≥30%): {len(cands)}")
        print(f"\nAll clusters:")
        for i, c in enumerate(clusters):
            cov = c["total_length"] / w
            zone = "TOP" if c["intercept"] < h*0.15 else ("BOT" if c["intercept"] > h*0.85 else "mid")
            mark = " *** CANDIDATE ***" if cov >= 0.3 else (" (fallback top)" if zone=="TOP" and cov>=0.05 else (" (fallback bot)" if zone=="BOT" and cov>=0.05 else ""))
            print(f"  [{i:2d}] y={c['intercept']:7.1f} ({zone}) cov={cov*100:5.1f}% len={c['total_length']:5.0f} lines={c['line_count']}{mark}")
        return
    print(f"Page {page_num} image not found in ce{ce_num}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ce", type=int)
    parser.add_argument("pages", help="页码，如 31 或 31,32,35")
    args = parser.parse_args()
    page_list = [int(p) for p in args.pages.split(",")]
    for p in page_list:
        diag_page(args.ce, p)
