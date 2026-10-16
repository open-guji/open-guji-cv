# -*- coding: utf-8 -*-
"""读回判官输出，按册报大模型单用成绩，并看两遍一致 / 高把握子集。
用法：llm_eval.py <llm_dir> <tag> [<tag2> ...]   （tag 对应 <tag>_NN.out.json）
"""
import glob, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common


def load(d: str, tag: str) -> dict[str, dict]:
    out = {}
    for f in sorted(glob.glob(f"{d}/{tag}_*.out.json")):
        for r in json.loads(Path(f).read_text(encoding="utf-8")):
            out[r["id"].replace("_", ":")] = r
    return out


if __name__ == "__main__":
    d, tags = sys.argv[1], sys.argv[2:]
    rows = common.strong(common.load_items())
    runs = [load(d, t) for t in tags]
    for t, r in zip(tags, runs):
        pred = {k: v["char"] for k, v in r.items()}
        print("==", t, len(r), common.fmt(common.metrics(rows, pred)))
        for b, m in common.by_book(rows, pred).items(): print("  ", b, common.fmt(m))
        hi = {k: v["char"] for k, v in r.items() if v["conf"] == "high"}
        print("   仅 high：", common.fmt(common.metrics(rows, hi)))
    if len(runs) >= 2:
        both = {k: runs[0][k]["char"] for k in runs[0] if k in runs[1] and runs[0][k]["char"] == runs[1][k]["char"]}
        print("== 两遍一致", common.fmt(common.metrics(rows, both)))
