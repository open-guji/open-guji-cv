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
#
# 【重标记录】图块内容一变，标签就得跟着重看，这是这个数据集的常态。
#
# 2026-08-22 第一轮：segment 加入列型分类，2771 个图块变化，本表命中 15 个
#   （12 个重标、3 个 ID 消失）。
# 2026-08-22 第四轮：segment 加页型闸门 + 列梳子夹逼 + 窄页按实际列数切。
#   只有 2 个图块变了（36:2:3、113:8:6，重看仍是 clean），1 个 ID 消失
#   （97:4:9，所在页改按 8 列切、列内序号前移）。样本 63 → 62。
# 2026-08-22 第三轮：segment 再加**界行定列距 + 书级列距共识**，61/63 个图块
#   内容变化（ID 一个没丢）。逐个重核：只有 4 个标签要动——
#   168:2:6 与 65:4:10 由 clean 转 contaminated（前者右缘吃进整条界行、
#   后者纵向吃进下一个字），113:8:6 与 188:8:3 由 contaminated 转 clean
#   （残余碎块与界行都没了）。缺陷数仍是 11。
# 2026-08-22 第二轮：segment 加入**残余错切校正 + 界行吸附**（列宽问题的
#   正解），几乎所有图块的坐标都动了——67 个里 59 个内容变化、4 个 ID 消失。
#   全部对着新输出重标。结论是切分又好了一截：缺陷从 17/67 降到 11/63，
#   原来 12 个 contaminated 里有 6 个（199:8:3 31:6:10 153:9:12 126:5:2
#   200:1:3 65:4:10）现在已经干净了——正是界行不再被圈进图块的直接结果。
#   代价：三个原本干净的格位因列相位平移落到了版框横线上（146:7:20
#   171:2:15 97:4:9），从 clean 变成 not_text；116:1:8 吃进了版框横线。
LABELS: dict[str, list[str]] = {
    "clean": [
        "138:1:5", "165:8:3", "77:8:13", "177:2:1", "201:5:3",
        "152:2:6", "154:8:6", "173:9:11", "84:6:7", "99:5:5", "18:6:4",
        "92:1:6", "42:5:9", "86:6:17", "95:3:0", "66:3:4", "194:1:2",
        "59:7:2", "122:6:0", "70:3:0", "111:5:1", "92:4:0", "90:9:5",
        "122:3:1", "124:6:1", "118:5:5", "130:5:2", "130:8:0", "118:8:2",
        "117:8:5", "72:6:7", "36:2:3", "154:8:3", "34:1:13", "63:1:8",
        "154:2:17", "18:3:18", "10:2:6", "67:5:17", "156:8:16", "189:7:2",
        "203:2:4", "203:8:3", "137:9:9", "137:8:9",
        # 本轮转干净：界行不再被圈进图块
        "199:8:3", "31:6:10", "153:9:12", "126:5:2", "200:1:3",
        # 第三轮转干净：残余碎块与界行都没了
        "113:8:6", "188:8:3",
    ],
    # 混入界行竖线 / 版框 / 上下邻字残余 / 隔壁列的字
    "contaminated": [
        "116:1:8",   # 底部整条版框横线
        "87:1:18",   # 顶部两块邻字残余
        "103:5:5",   # 左下一块邻字残余
        "90:2:6",    # 跨列：左「土」右「自」分属两列
        # 第三轮转入
        "168:2:6",   # 右缘整条界行竖线（13×132 满高连通体）
        "65:4:10",   # 纵向吃进下一个字（图块高 157px，格高才 114px）
    ],
    # 本字的墨被切掉一部分
    # 本批样本仍无截断实例（上一轮起就没有）。这不代表全书没有，只说明
    # 这 63 个样本覆盖不到，需另行抽样补充。
    "truncated": [],
    # 版框角/整条横线/空格位，根本不是字
    "not_text": [
        "135:5:20", "179:5:20",
        # 本轮转入：列相位平移后落到版框横线上的空格位
        "146:7:20", "171:2:15", "97:4:9",
    ],
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
