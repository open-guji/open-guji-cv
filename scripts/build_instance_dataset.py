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
# 2026-08-23 第十一轮：rule_in_col 升级为触发条件 + edge_blob 加间隙条件。
#   18 个图块内容变化、ID 一个没丢，**没有标签要改**；3 个格序号又指向了
#   别的字（18:6:4 此→者、18:3:18 要→以、66:3:4 廣→一，页 18/66 正是被
#   rule_in_col 触发重扫的页），新指向的字都完整干净，仍是 clean。
#
# 2026-08-23 第十轮：界行检测改分带（检不出界行的页会静默退化）+ 内缩双侧
#   钳制 + 列参数传给后续 pass。24 个图块内容变化、1 个 ID 消失
#   （116:1:8，contaminated）。逐个重看**没有标签要改**，但有 2 个的
#   page:col:idx 又指向了别的字：109:9:5 从「臣」变成「裴」、
#   vol02/17:8:9 从「書」变成「隋」——新指向的字同样完整干净，仍是 clean。
#   样本 62 → 61。
#
# 2026-08-23 第九轮：书级格高改由**实测字距**定（+1.2% vol01 / +3.0% vol02），
#   全书格线位置都动了 —— 65 个图块里 49 个内容变化、3 个 ID 消失。
#   注意这一轮的漂移和以往不同：格高一变，**格序号对应的字就换了人**
#   （如 10:2:6 从「列」变成「冬」），不是同一个字裁得不一样。逐个重看：
#     87:1:18   contaminated → clean      顶部两块邻字残余没了
#     vol02/17:8:9  truncated → clean     「書」完整了
#     103:5:5   contaminated → truncated  外来墨没了，但只切到「式」的上半
#     105:5:2   truncated → contaminated  「筵」完整了，却吃进下一字「講」的头
#     vol02/185:4:20 truncated → not_text 该格位现在是空的，只剩一条框线残迹
#     135:5:20 / 179:5:20 / 146:7:20 三个 not_text 的 ID 消失
#       （它们是「空格位落在版框横线上」，格线一动就不存在了）
#   样本 65 → 62，缺陷 12 → 7。
#
# 2026-08-22 第八轮：cells_from_components 的闸门不再重判列型（职名页 2 格
#   拉开的官衔列过去被挡在门外，判了 elastic 却切不出来 → 回落刚性 → 字被
#   格线腰斩）。65 个图块内容一个没变，只有 95:1:17 消失——它所在的列正是
#   改判弹性的那种，列内序号重排。样本 66 → 65。
#
# 2026-08-22 第七轮：chars 的横向裁切边改成「从文字带往外扩到撞上界行为止」
#   （cell_bounds_from_rules）。66 个图块**全部**变宽（ID 一个没丢），
#   逐个重看只有 2 个标签要动：95:1:17 与 109:9:5 由 **truncated 转 clean**
#   ——正是那两个「臣」，右半边现在完整了。这两个恰好是上一轮专门为
#   「横向截断」补进来的样本，补样的目的达到了。其余 4 个 truncated 都不是
#   横向截断（三个是纵向切一半、一个是宽字左右都出框），照旧。
#   缺陷层没有任何图块新增确定层 flag——外扩没有把界行裹进来。
#
# 2026-08-22 第一轮：segment 加入列型分类，2771 个图块变化，本表命中 15 个
#   （12 个重标、3 个 ID 消失）。
# 2026-08-22 第五轮：segment 加**书级内缩共识**（列框不再贴着界行走）。
#   13 个图块变化、1 个 ID 消失（171:2:15）。重看只有 1 个标签要改：
#   168:2:6 由 contaminated 转 **truncated**——界行是不混了，但那一格的
#   格高只有 59px（书级 114），只切到「學」的下半。这也是本数据集**第一个
#   truncated 实例**，此前连续三轮都没有，截断检测能力终于有样本可验。
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
        # 第七轮转干净：图块改按界行外扩裁，「臣」的右半边回来了
        # 95:1:17 第八轮消失（所在列改判弹性，列内序号重排）
        "109:9:5",
        # 第九轮转干净（格高改由实测字距定之后）
        "87:1:18", "vol02/17:8:9",
    ],
    # 混入界行竖线 / 版框 / 上下邻字残余 / 隔壁列的字
    "contaminated": [
        # 116:1:8 第十轮消失（该格位在新网格下不存在）
        "90:2:6",    # 跨列：左「文」右「人」分属两列
        # 第三轮转入
        "65:4:10",   # 右缘整条界行竖线
        # 第九轮转入：本字完整了，却吃进下一字「講」的头
        "105:5:2",
    ],
    # 本字的墨被切掉一部分
    "truncated": [
        # 第五轮转入：那一格只切到「學」的下半。本数据集第一个截断实例。
        "168:2:6",
        # 第六轮补样（2026-08）：专为「截断」这一类补的，抽样线索是
        # 「**本字自己的**连通体越出格外的比例」——只保留主体（≥65%）在
        # 本格内的连通体，邻字不计。全书 5826 个有实质墨的格里该量中位
        # 0.009、99 分位 0.291；下面几个都在 0.32~0.35。
        # 其中「臣」的两个（95:1:17、109:9:5）在第七轮已修好，转入 clean。
        # 它们是同一种**系统性**失败：职名列的「臣」坐在格位右缘、一半在
        # 框外，不是随机噪声——所以值得为它专门改裁切规则。
        # 第九轮转入：外来墨没了，但只切到「式」的上半
        "103:5:5",
    ],
    # 版框角/整条横线/空格位，根本不是字
    "not_text": [
        # 第九轮转入：该格位现在是空的，只剩一条框线残迹
        "vol02/185:4:20",
        # 135:5:20 / 179:5:20 / 146:7:20 第九轮消失——它们都是「空格位落在
        # 版框横线上」，格高一改格线位置全变，这些格位不复存在
        # 97:4:9  第四轮消失（所在页改按 8 列切，列内序号前移）
        # 171:2:15 第五轮消失（所在页内缩改用书级共识，列内序号变化）
    ],
}

DEFAULT_BOOK = "vol01"


def split_key(k: str) -> tuple[str, str]:
    """键可写成 "page:col:idx"（默认 vol01）或 "vol02/page:col:idx"。"""
    if "/" in k:
        book, rest = k.split("/", 1)
        return book, rest
    return DEFAULT_BOOK, k


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="数据集输出目录")
    ap.add_argument("--sample-meta", default=None,
                    help="抽样元数据 JSON（含 seed/layout）")
    args = ap.parse_args()

    meta = {}
    if args.sample_meta and Path(args.sample_meta).exists():
        for s in json.loads(Path(args.sample_meta).read_text(encoding="utf-8")):
            # 键要和 LABELS 里的写法一致，否则 vol02 的样本查不到自己的
            # layout/seed，会被当成默认的 rigid
            rest = f"{s['page']}:{s['col']}:{s['idx']}"
            book = s.get("book", DEFAULT_BOOK)
            meta[rest if book == DEFAULT_BOOK else f"{book}/{rest}"] = s

    index: dict[tuple[str, str], dict] = {}
    for book in ("vol01", "vol02"):
        idx_path = Path("output") / book / "phase4_chars" / "index.jsonl"
        if not idx_path.exists():
            continue
        for line in idx_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            index[(book, f"{r['page']}:{r['col']}:{r['idx']}")] = r

    out = Path(args.out)
    (out / "patches").mkdir(parents=True, exist_ok=True)

    items: list[InstanceQuality] = []
    for quality, keys in LABELS.items():
        for k in keys:
            book, rest = split_key(k)
            if (book, rest) not in index:
                print(f"跳过 {k}（当前切分结果中不存在）")
                continue
            page, col, idx = rest.split(":")
            m = meta.get(k, {})
            items.append(InstanceQuality(
                book=book, page=page, col=int(col), idx=int(idx),
                quality=quality, layout=m.get("layout", "rigid"),
                seed=m.get("seed")))
            rec = index[(book, rest)]
            src = Path("output") / book / "phase4_chars" / rec["patch_path"]
            img = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                cv2.imwrite(str(out / "patches"
                                / f"{book}_{page}_{col}_{idx}.png"), img)

    save_dataset(items, out / "expected.json")
    from collections import Counter
    print(f"写出 {len(items)} 个实例 → {out}")
    print(" 质量:", dict(Counter(i.quality for i in items)))
    print(" 列型:", dict(Counter(i.layout for i in items)))


if __name__ == "__main__":
    main()
