"""生成归一化 golden 回归集（open-guji-dataset/char-normalization）。

golden 是**当前归一化的输出，逐张目视确认之后**才冻结的。确认这一步不能省：
不看就冻，等于把当前的缺陷焊成金标，以后修好了反而报「回归失败」。
所以本脚本产出两层（见 `VERDICTS`）：

- `verified`：目视确认输出正确 → 进严格回归门；
- `known_defect`：输出本身就是错的 → 只记录当前行为，不进门。

**抽样线索全部来自归一化之外**（making-datasets.md 第四步第 4 条：线索不能
就是判据）：`ink_ratio` 与 `flags` 是 extractor 的量，`human_*` 那一档直接取
char-segmentation/instances 的人工标签。归一化好不好，用它自己的中间量去
挑样本就是自证。

    python scripts/build_normalization_dataset.py --dataset ../open-guji-dataset/char-normalization
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.align_label import clean_labels, label_book
from open_guji_cv.clustering.normalize import (MARGIN_RATIO, NOISE_AREA,
                                               NORM_SIZE, normalize_patch,
                                               skeletonize)

SOURCE_ITEM = "06061300.cn"
PER_CUE = 6
TOLERANCE = {"pixel_diff_ratio": 0.01, "binary_iou_min": 0.98,
             "skeleton_endpoint_delta_max": 2}

# ── 目视确认结果（2026-08-23，35/35 逐张看「原图 | 归一图 | 骨架」）──────
#
# 判据只有一条：**归一化有没有做它该做的事**（去残余 / 居中缩放 / 笔宽归一）。
# 输入本身是坏切分（跨列、纵向吃进邻字、被腰斩）不算归一化的错——那是
# char-segmentation 的账，这里只把当前行为锁住，理由记在 NOTES 里。
#
# 改判定只改这两张表。
VERDICTS: dict[str, str] = {
    "024": "界行竖线没去掉。实测这条竖条 x=133 w=6 h=123/132（高占 93%），"
           "但左右都不贴边（x+bw=139 < 146）——remove_edge_specks 的 vline "
           "判据要求 `x==0 or x+bw>=w`，内缩 7px 就整条漏网，归一图里它成了"
           "独立的一竖，外接框被撑宽、字被压窄。",
    "025": "轻微：邻字残点未去，归一图下方留了一个孤立小点。"
           "点在字的外接框内，没撑大 bbox，对聚类影响小，但按「去残余」的"
           "职责这是没做到。",
    "031": "邻字残画没去：金标字是「一」，图块上半还留着邻字底部的两笔，"
           "归一化把三笔一起当本字缩放，「一」被压到下半——这类是"
           "外接框被残余撑大的典型。",
}

# 输入本身有缺陷、归一化无从判断的样本：进回归门，但要说清楚测的是什么。
NOTES: dict[str, str] = {
    "032": "输入跨列（左「土」右「自」分属两列，char-segmentation 已人工标为 "
           "contaminated）。归一化没有拆字的职责，此样本只锁定当前行为。",
    "033": "输入纵向吃进了下一个字。同上，只锁定当前行为。",
    "035": "输入被腰斩（人工标 truncated）。归一化对残字照常处理即为正确。",
}

COVER_OVERRIDE: dict[str, list[str]] = {}   # sample_id -> 目视确认的 cover 标签


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       text=True).strip()
    except Exception:                                    # pragma: no cover
        return "unknown"


def load_index(book: str, output_root: Path) -> list[dict]:
    rows = []
    with open(output_root / book / "phase4_chars" / "index.jsonl",
              encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def ink_darkness(gray: np.ndarray) -> float:
    """墨色深浅 = **墨迹像素**的平均灰度（Otsu 分出墨迹）。越小越黑。

    量「着墨浓淡」不能用 `ink_ratio`——那是墨**覆盖比例**，笔画少的字天然低。
    第一轮就栽在这上面：ink_ratio 最低的 6 个样本 5 个是「一」「二」「三」，
    量到的是笔画数。第二轮改用「最暗 15% 像素的均值」还是不行：笔画少的字
    这 15% 里混着一半背景，照样被算成「淡」（捞上来 子/七/于/士/元）。
    只对墨迹像素求均值才与笔画数无关。

    用 Otsu 而不是归一化里的 Sauvola：抽样线索不能与被测判据同源。
    """
    thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = gray[gray < thr]
    return float(ink.mean()) if ink.size else 255.0


def pick(rows: list[dict], cue: str, n: int, seed: int,
         patch_root: Path, sample_pool: int = 400) -> list[dict]:
    """按线索挑样本。线索都是归一化之外的量（extractor 的 flags / 原图灰度）。

    所有档次都先要求**这一格有对齐金标字**（调用方已过滤）：不加这条，
    `rule_bar` / `edge_blob` 捞上来的全是纯版框横条与空格位——第一轮 18 个
    带 flag 的样本里 11 个根本不是字。测「字块带残余怎么归一化」，
    样本得先是个字。
    """
    rng = random.Random(seed)
    clean = [r for r in rows if not r["flags"]]
    if cue in ("ink_heavy", "ink_light"):
        pool = [r for r in clean if r["ink_ratio"] >= 0.12]   # 排除笔画极少的字
        rng.shuffle(pool)
        pool = pool[:sample_pool]
        scored = []
        for r in pool:
            g = cv2.imread(str(patch_root / r["patch_path"]), cv2.IMREAD_GRAYSCALE)
            if g is not None:
                scored.append((ink_darkness(g), r))
        scored.sort(key=lambda t: t[0])
        return [r for _, r in (scored[:n] if cue == "ink_heavy" else scored[-n:])]
    if cue == "border_residue":
        pool = [r for r in rows if {"rule_bar", "frame_bars"} & set(r["flags"])]
    elif cue == "neighbor_intrusion":
        pool = [r for r in rows if "edge_blob" in r["flags"]]
    elif cue == "typical":
        pool = [r for r in clean if 0.10 <= r["ink_ratio"] <= 0.22]
    else:
        raise ValueError(cue)
    rng.shuffle(pool)
    return pool[:n]


def human_seeds(instances_gold: Path, book_rows: dict[str, list[dict]],
                n: int) -> list[tuple[dict, str]]:
    """char-segmentation/instances 的人工标签：最硬的一档独立线索。"""
    gold = json.loads(instances_gold.read_text(encoding="utf-8"))
    by_id = {f"{b}:{r['page']}:{r['col']}:{r['idx']}": r
             for b, rows in book_rows.items() for r in rows}
    out = []
    for g in gold:
        if g["quality"] not in ("contaminated", "truncated"):
            continue
        key = f"{g['book']}:{g['page']}:{g['col']}:{g['idx']}"
        rec = by_id.get(key)
        if rec is not None:
            out.append((rec, g["quality"]))
    return out[:n]


def write_sample(out_dir: Path, rec: dict, book: str, output_root: Path,
                 cover: list[str], cue: str, commit: str,
                 char: str | None = None) -> dict:
    gray = cv2.imread(str(output_root / book / "phase4_chars" / rec["patch_path"]),
                      cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(rec["patch_path"])
    norm = normalize_patch(gray)
    skel = skeletonize(norm)

    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / "input.png"), gray)
    cv2.imwrite(str(out_dir / "golden.png"), norm * 255)
    cv2.imwrite(str(out_dir / "golden_skeleton.png"), skel * 255)

    sid = out_dir.name
    defect = VERDICTS.get(sid)
    expected = {
        "source_item": SOURCE_ITEM,
        "pipeline_version": commit,
        "label_origin": "human",          # golden 逐张目视确认后冻结
        "instance_id": rec["id"],
        "book": book,
        "input": "input.png",
        "golden": "golden.png",
        "golden_skeleton": "golden_skeleton.png",
        "tolerance": dict(TOLERANCE),
        "cover": COVER_OVERRIDE.get(sid, cover),
        "char": char,                     # 仅供人工检视，不参与指标
        "status": "known_defect" if defect else "verified",
        "sampling_cue": cue,
        "extractor_flags": rec["flags"],
        "ink_ratio": rec["ink_ratio"],
        "norm_params": {"size": NORM_SIZE, "margin_ratio": MARGIN_RATIO,
                        "noise_area": NOISE_AREA, "stroke_width": 3},
        "schema_version": 1,
    }
    if defect:
        expected["defect"] = defect
    if sid in NOTES:
        expected["note"] = NOTES[sid]
    (out_dir / "expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "info.json").write_text(json.dumps({
        "id": sid, "source": SOURCE_ITEM, "source_item": SOURCE_ITEM,
        "book": book, "instance_id": rec["id"],
        "description": f"{cue} 线索抽样；flags={rec['flags']}；"
                       f"ink_ratio={rec['ink_ratio']}",
        "tags": [cue, book] + expected["cover"],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return expected


CUE_COVER = {
    "ink_heavy": ["ink_heavy"],
    "ink_light": ["ink_light", "broken_stroke"],
    "border_residue": ["border_residue"],
    "neighbor_intrusion": ["neighbor_intrusion"],
    "typical": [],
    "human_contaminated": ["border_residue", "neighbor_intrusion"],
    "human_truncated": ["broken_stroke"],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="../open-guji-dataset/char-normalization")
    ap.add_argument("--output", default="output")
    ap.add_argument("--page-type", default="../open-guji-dataset/page-type/expected.json")
    ap.add_argument("--instances-gold",
                    default="../open-guji-dataset/char-segmentation/instances/expected.json")
    ap.add_argument("--corpus", default="corpus/zongmu_wuyingdian_reference.txt")
    ap.add_argument("--per-cue", type=int, default=PER_CUE)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    dataset = Path(args.dataset)
    output_root = Path(args.output)
    commit = git_commit()
    page_gold = json.loads(Path(args.page_type).read_text(encoding="utf-8"))

    rows_by_book, char_of, all_by_book = {}, {}, {}
    for book in ("vol01", "vol02"):
        body = {g["page"] for g in page_gold
                if g["book"] == book and g["page_type"] == "body"}
        index = {r["id"]: r for r in load_index(book, output_root)}
        # human_* 那一档不要求有对齐金标：人工的 contaminated/truncated 标签
        # 本身就证明了那一格是个（带残余或被切残的）字。
        all_by_book[book] = [r for r in index.values()
                             if r["page"] in body and r["cell_type"] == "char"]
        labels, _ = clean_labels(
            label_book(book, output_root / book, Path(args.corpus), pages=body)[0],
            index)
        char_of.update({x.instance_id: x.char for x in labels})
        rows_by_book[book] = [index[x.instance_id] for x in labels
                              if index[x.instance_id]["cell_type"] == "char"]

    picked: list[tuple[dict, str, str]] = []       # (记录, 册, 线索)
    for cue in ("typical", "ink_heavy", "ink_light",
                "border_residue", "neighbor_intrusion"):
        for book in ("vol01", "vol02"):            # 两册均分，别只测一册
            half = args.per_cue // 2
            patch_root = output_root / book / "phase4_chars"
            for rec in pick(rows_by_book[book], cue, half, args.seed, patch_root):
                picked.append((rec, book, cue))

    gold_path = Path(args.instances_gold)
    if gold_path.exists():
        for rec, quality in human_seeds(gold_path, all_by_book, args.per_cue):
            picked.append((rec, rec["book"], f"human_{quality}"))

    samples_dir = dataset / "samples"
    for old in sorted(samples_dir.glob("[0-9][0-9][0-9]")):
        if old.name != "000-example":
            for f in old.iterdir():
                f.unlink()
            old.rmdir()

    written = []
    for n, (rec, book, cue) in enumerate(picked, start=1):
        out_dir = samples_dir / f"{n:03d}"
        written.append(write_sample(out_dir, rec, book, output_root,
                                    CUE_COVER.get(cue, []), cue, commit,
                                    char_of.get(rec["id"])))

    summary = {
        "pipeline_version": commit,
        "n_samples": len(written),
        "n_verified": sum(1 for w in written if w["status"] == "verified"),
        "n_known_defect": sum(1 for w in written if w["status"] == "known_defect"),
        "by_cue": {c: sum(1 for w in written if w["sampling_cue"] == c)
                   for c in sorted({w["sampling_cue"] for w in written})},
        "by_book": {b: sum(1 for w in written if w["book"] == b)
                    for b in sorted({w["book"] for w in written})},
    }
    (dataset / "build_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
