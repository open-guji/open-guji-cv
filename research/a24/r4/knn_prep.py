"""殿本 book_knn 训练集准备（A24 第 4 轮）：从 cells.json（dump_cells.py 的输出）抽刻例＋背景＋待审格，导出字块。

    python knn_prep.py <组> <cells.json> <工作目录> [--per 10] [--bg 3000]
输出：<工作目录>/<组>/{cells.json, bg.json, pend.json, patches/}；然后
    python research/char_groups/book_knn_train.py <组> <工作目录>/<组>/cells.json <工作目录>/<组>/patches <出.json> --bg <工作目录>/<组>/bg.json
"""
import argparse, collections, json, os, random, subprocess, sys
from pathlib import Path
from open_guji_cv.groups.registry import FLOW_GROUPS
ap = argparse.ArgumentParser()
ap.add_argument("group"); ap.add_argument("cells"); ap.add_argument("work")
ap.add_argument("--per", type=int, default=10); ap.add_argument("--bg", type=int, default=3000)
ap.add_argument("--pend", default="", help="待审格号文件（一行一个），导出字块给评测用")
a = ap.parse_args()
random.seed(1104)
mem = FLOW_GROUPS[a.group].members
cells = json.load(open(a.cells))
buck = collections.defaultdict(list)
for c in cells:
    if c["admit"] and c["char"] in mem and c["channel"] != "human":
        buck[(c["vol"], c["char"])].append(c)
sel = []
for k, v in buck.items():
    random.shuffle(v); sel += v[:a.per]
bgp = [c for c in cells if c["admit"] and c["char"] not in mem and c["channel"] != "human" and c["char"]]
random.shuffle(bgp); bg = bgp[:a.bg]
out = Path(a.work) / a.group; (out / "patches").mkdir(parents=True, exist_ok=True)
json.dump(sel, open(out / "cells.json", "w"), ensure_ascii=False)
json.dump(bg, open(out / "bg.json", "w"), ensure_ascii=False)
ids = [c["id"] for c in sel + bg]
if a.pend:
    ids += [l.strip() for l in open(a.pend) if l.strip()]
(out / "ids.txt").write_text("\n".join(ids))
print(a.group, "刻例", len(sel), "背景", len(bg), file=sys.stderr)
here = Path(__file__).parent
subprocess.run([sys.executable, str(here / "dump_patches.py"), str(out / "ids.txt"), str(out / "patches")], check=True)
