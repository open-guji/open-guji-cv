"""生成单字图块质量数据集（char-segmentation/instances）。

金标为人工目视：每个图块渲染成「原图带图块边界 + 连通体着色」的对照图，
按 clean / contaminated / truncated / not_text 四类给实例级标签。

**抽样有意偏置**：一半样本从历史人工审查标记过的问题位置抽（那些位置
值得复查），另一半从刚性/弹性列随机抽。因此各类占比**不是全书真实比例**，
只能用于比较不同算法在同一批样本上的表现。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from open_guji_cv.clustering.instance_quality import (InstanceQuality,
                                                      save_dataset)

# 人工目视标注结果（2026-08，vol01）。改标注只改这里。
LABELS: dict[str, list[str]] = {
    "clean": [
        "168:2:6", "138:1:5", "165:8:3", "77:8:13", "200:1:3", "177:2:1",
        "146:7:20", "201:5:3", "152:2:6", "154:8:6", "173:9:11", "84:6:7",
        "99:5:5", "18:6:4", "92:1:6", "42:5:9", "86:6:17", "95:3:0",
        "66:3:4", "171:2:15", "194:1:2", "59:7:2", "122:6:0", "70:3:0",
        "111:5:1", "92:4:0", "97:4:9", "116:1:8", "90:9:5", "122:3:1",
        "124:6:1", "118:5:5", "130:5:2", "130:8:0", "118:8:2", "117:8:5",
        "72:6:7", "36:2:3", "154:8:3", "34:1:13", "63:1:8", "154:2:17",
        "18:3:18", "10:2:6", "67:5:17", "156:8:16",
    ],
    # 混入界行竖线 / 版框 / 上下邻字残余
    "contaminated": [
        "199:8:3", "31:6:10", "188:8:3", "189:7:2", "87:1:18", "91:3:0",
        "113:8:6", "90:2:6", "102:9:4", "176:5:6", "153:9:12", "103:5:5",
        "126:5:2", "65:4:10", "203:2:4", "159:6:5",
    ],
    # 本字的墨被切掉一部分
    "truncated": ["203:8:3", "137:9:9"],
    # 版框角/整条横线/空格位，根本不是字
    "not_text": ["135:5:20", "130:7:0", "137:8:9", "179:5:20", "189:5:7",
                 "205:9:0"],
}

BOOK = "vol01"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="数据集输出目录")
    ap.add_argument("--sample-meta", default=None,
                    help="抽样元数据 JSON（含 seed/layout）")
    args = ap.parse_args()

    meta = {}
    if args.sample_meta and Path(args.sample_meta).exists():
        for s in json.loads(Path(args.sample_meta).read_text(encoding="utf-8")):
            meta[f"{s['page']}:{s['col']}:{s['idx']}"] = s

    index = {}
    idx_path = Path("output") / BOOK / "phase4_chars" / "index.jsonl"
    for line in idx_path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        index[f"{r['page']}:{r['col']}:{r['idx']}"] = r

    out = Path(args.out)
    (out / "patches").mkdir(parents=True, exist_ok=True)

    items: list[InstanceQuality] = []
    for quality, keys in LABELS.items():
        for k in keys:
            if k not in index:
                print(f"跳过 {k}（当前切分结果中不存在）")
                continue
            page, col, idx = k.split(":")
            m = meta.get(k, {})
            items.append(InstanceQuality(
                book=BOOK, page=page, col=int(col), idx=int(idx),
                quality=quality, layout=m.get("layout", "rigid"),
                seed=m.get("seed")))
            src = Path("output") / BOOK / "phase4_chars" / index[k]["patch_path"]
            img = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                cv2.imwrite(str(out / "patches" / f"{page}_{col}_{idx}.png"), img)

    save_dataset(items, out / "expected.json")
    from collections import Counter
    print(f"写出 {len(items)} 个实例 → {out}")
    print(" 质量:", dict(Counter(i.quality for i in items)))
    print(" 列型:", dict(Counter(i.layout for i in items)))


if __name__ == "__main__":
    main()
