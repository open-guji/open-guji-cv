#!/usr/bin/env python3
"""GUJI-208it：给 Ezio 208is 抽样名单落盘（纯机械，不看图、不判字）。

来源（只读）：CV候选字挑选/计划/切分坏366格id-Enzo.tsv、非字123格id-Enzo.tsv
抽样：每类各自 random.Random(SEED).sample(列表, k)，两类各新建 Random，互不共享状态。
输出：scripts-Emi/208is抽样名单-Emi.tsv（重跑覆盖，同输入逐字节相同）。
"""
import random
from pathlib import Path

SEED = 20261014
PROG = Path(__file__).resolve().parent.parent          # 图片初步数字化/进度
PROJ = PROG.parents[1]                                  # 项目进展
PLAN = PROJ / "CV候选字挑选/计划"
CATS = [
    # (类别, 来源文件, 期望行数, 抽样数)
    ("切分坏", PLAN / "切分坏366格id-Enzo.tsv", 366, 60),
    ("非字", PLAN / "非字123格id-Enzo.tsv", 123, 50),
]
OUT = PROG / "scripts-Emi" / "208is抽样名单-Emi.tsv"


def read_ids(path):
    ids = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or s == "id":  # 跳过注释、空行、表头
                continue
            ids.append(s)
    return ids


def main():
    head = []
    rows = []
    for name, path, expect, k in CATS:
        ids = read_ids(path)
        if len(ids) != expect:
            raise SystemExit(f"停：{path.name} 得到 {len(ids)} 格，不是 {expect}，请问 Mila，不硬抽")
        picked = random.Random(SEED).sample(ids, k)
        head.append(f"# 来源：{path.relative_to(PROJ)}（{len(ids)} 格，id 列）；类别={name}，抽 {k}")
        for i, cid in enumerate(picked, 1):
            rows.append(f"{name}\t{i}\t{cid}")
    head.append(f"# 种子：{SEED}（每类各自 random.Random({SEED}).sample）；脚本 scripts-Emi/208is_sample.py")
    OUT.write_text("\n".join(head + ["类别\t序号\t格号"] + rows) + "\n", encoding="utf-8")
    print(f"已写 {OUT}：{len(rows)} 行")


if __name__ == "__main__":
    main()
