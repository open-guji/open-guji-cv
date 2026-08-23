"""生成归一化 golden 回归集（open-guji-dataset/char-normalization）。

**双层结构**（2026-08 起）：上游切分做不到完美，图块天然分两类，归一化的
目标也分两档——

| tier | 定义 | 对算法的要求 |
|---|---|---|
| `clean` | 字完整、无外来残留 | **必须做得非常好**：缺陷零容忍 |
| `degraded` | 有邻字/界行残留，或本字被切 | 能不崩、残留尽量去掉；缺陷记账、按优先级修 |

分层判据是 `crop_quality.assess_crop`（在原始图块上用 Otsu + 连通体结构量
「完整性 / 残留」，与归一化的 Sauvola 不同源；对 instances 人工金标校准：
缺陷检出 5/7、clean 误报 2/55），**最终 tier 以逐张目视为准**——机器分级
只是抽样线索，`TIER_OVERRIDE` 记录目视改判。

golden 仍是**当前归一化输出，逐张目视确认后**冻结，分两种状态：

- `verified`：输出正确 → 进严格回归门；
- `known_defect`：输出错了 → 只记录当前行为，不进门（把错的输出冻成
  golden 等于把缺陷焊死）。clean 层出现 known_defect 是 P0 信号。

产物取自**工作区当前 output/**（a435d7b 之后的新切分）。本集不需要对齐
金标字——归一化回归只看像素，字义无关；样本是不是真字由逐张目视把关
（不是字的进 `DROP`）。

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

from open_guji_cv.clustering.crop_quality import assess_crop
from open_guji_cv.clustering.normalize import (MARGIN_RATIO, NOISE_AREA,
                                               NORM_SIZE, normalize_patch,
                                               skeletonize)

SOURCE_ITEM = "06061300.cn"
TOLERANCE = {"pixel_diff_ratio": 0.01, "binary_iou_min": 0.98,
             "skeleton_endpoint_delta_max": 2}

# ── 目视确认结果（2026-08-23，对 502fa04 新切分产物重验）──────────────
#
# 判据：**归一化有没有做它该做的事**（去残余 / 居中缩放 / 笔宽归一）。
# 输入本身是坏切分不算归一化的错，但会记进 NOTES 说明测的是什么。
# 改判定只改这几张表。上游切分每次重跑，四张表必须清空重验。
VERDICTS: dict[str, str] = {           # sample_id -> 缺陷说明（进 known_defect 层）
    # 四个同根因（与上一轮一致）：残留不贴图块边缘时 remove_edge_specks
    # 够不着。036 最典型：界行竖线**贯穿字身**但不贴左右边，整条留下。
    "031": "「指」下方两条版框横线（不贴下边）未去，golden 原样保留。",
    "033": "字底部的邻行残带未去（输入本身被切 + 残带，残带是可去的那部分）。",
    "034": "「造」下方一条横线（邻格边线，不贴边）未去。",
    "036": "贯穿「妙」的界行竖线：中位不贴左右边，vline 判据够不着，整条留下。",
}
NOTES: dict[str, str] = {              # sample_id -> 输入本身的说明（仍进回归门）
    "025": "「美」底横压边（轻度截断），照常处理即正确。",
    "027": "顶部截断的密字，照常处理即正确。",
    "035": "「易」顶部被切（instances 人工标 contaminated），照常处理即正确。",
}
DROP: dict[str, str] = {               # sample_id 占位 -> 目视发现不是字，剔除
    # 全部是列尾格（idx 18~20）：版框线/邻行残带占格。该由页型/切分层拦，
    # 不该测归一化。列尾格是 residue/truncated 线索的重灾区，抽样时
    # 高分排序天然捞到它们——known_limitation 记一条。
    "017": "典字顶部残条 + 版框双线，不是完整字",
    "018": "纯版框横线 + 墨渍",
    "023": "竖点残列 + 底部残带，不是字",
    "024": "残字碎片 + 框线，判不准",
    "028": "纯底部残带",
    "032": "近空白格 + 框线，「一」与框线判不准",
}
TIER_OVERRIDE: dict[str, str] = {      # sample_id -> 目视改判的 tier
    # frame_bars flag 命中但目视完整干净（「撫」，框线在 padding 带外缘）
    "030": "clean",
}


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


def margins_of(rec: dict) -> tuple[int, int]:
    bh = rec["bbox"][3] - rec["bbox"][1]
    bw = rec["bbox"][2] - rec["bbox"][0]
    return (max(0, int(round((bh - rec["height"]) / 2))),
            max(0, int(round((bw - rec["width"]) / 2))))


def ink_darkness(gray: np.ndarray) -> float:
    """墨色深浅 = **墨迹像素**的平均灰度（Otsu 分出墨迹）。越小越黑。

    量「着墨浓淡」不能用 `ink_ratio`——那是墨**覆盖比例**，笔画少的字天然低
    （第一版捞上来全是「一」「二」「三」）；「最暗 15% 像素均值」也不行——
    笔画少的字这 15% 里混着一半背景。只对墨迹像素求均值才与笔画数无关。
    """
    thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = gray[gray <= thr]
    return float(ink.mean()) if ink.size else 255.0


def assessed(rows: list[dict], patch_root: Path, pool: int, seed: int):
    """随机取 pool 个实例并跑 crop_quality，返回 [(rec, gray, quality)]。"""
    rng = random.Random(seed)
    rows = [r for r in rows if r["cell_type"] == "char"]
    rng.shuffle(rows)
    out = []
    for r in rows:
        if len(out) >= pool:
            break
        gray = cv2.imread(str(patch_root / r["patch_path"]), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        out.append((r, gray, assess_crop(gray, margins=margins_of(r))))
    return out


def pick(pool, cue: str, n: int):
    """从 assessed 池子里按线索挑。clean 档全部要求机器分级 clean。"""
    if cue == "typical":
        cand = [(r, g, q) for r, g, q in pool
                if q.tier == "clean" and not r["flags"]
                and 0.10 <= r["ink_ratio"] <= 0.22]
        return cand[:n]
    if cue in ("ink_heavy", "ink_light"):
        cand = [(r, g, q) for r, g, q in pool
                if q.tier == "clean" and not r["flags"] and r["ink_ratio"] >= 0.12]
        cand.sort(key=lambda t: ink_darkness(t[1]))
        return cand[:n] if cue == "ink_heavy" else cand[-n:]
    if cue == "residue":
        cand = [(r, g, q) for r, g, q in pool if q.residue]
        cand.sort(key=lambda t: -t[2].foreign_core_px)     # 残留最重的优先
        return cand[:n]
    if cue == "truncated":
        cand = [(r, g, q) for r, g, q in pool if q.truncated and not q.residue]
        cand.sort(key=lambda t: -t[2].edge_ink_px)
        return cand[:n]
    if cue == "flagged":
        # extractor 确定层 flag（rule_bar/frame_bars/edge_blob）：与 crop_quality
        # 不同源的第二条退化线索，防止退化层只覆盖自家判据认得出的那种脏
        cand = [(r, g, q) for r, g, q in pool
                if {"rule_bar", "frame_bars", "edge_blob"} & set(r["flags"])]
        return cand[:n]
    raise ValueError(cue)


def human_seeds(instances_gold: Path, rows_by_book, patch_roots, n: int):
    """char-segmentation/instances 的人工缺陷标签：最硬的退化层线索。"""
    gold = json.loads(instances_gold.read_text(encoding="utf-8"))
    by_id = {f"{b}:{r['page']}:{r['col']}:{r['idx']}": (b, r)
             for b, rows in rows_by_book.items() for r in rows}
    out = []
    for g in gold:
        if g["quality"] not in ("contaminated", "truncated"):
            continue
        hit = by_id.get(f"{g['book']}:{g['page']}:{g['col']}:{g['idx']}")
        if hit is None:
            continue
        b, r = hit
        gray = cv2.imread(str(patch_roots[b] / r["patch_path"]),
                          cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        out.append((r, gray, assess_crop(gray, margins=margins_of(r)), b,
                    f"human_{g['quality']}"))
    return out[:n]


def write_sample(out_dir: Path, rec: dict, gray, quality, book: str,
                 tier: str, cue: str, commit: str) -> dict:
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
        "tier": TIER_OVERRIDE.get(sid, tier),
        "tier_detail": quality.to_dict(),
        "char": None,                     # 像素回归不看字义
        "status": "known_defect" if defect else "verified",
        "sampling_cue": cue,
        "extractor_flags": rec["flags"],
        "ink_ratio": rec["ink_ratio"],
        "norm_params": {"size": NORM_SIZE, "margin_ratio": MARGIN_RATIO,
                        "noise_area": NOISE_AREA, "stroke_width": 3},
        "schema_version": 2,
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
        "description": f"tier={expected['tier']}；线索 {cue}；flags={rec['flags']}",
        "tags": [expected["tier"], cue, book],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return expected


CLEAN_CUES = (("typical", 3), ("ink_heavy", 3), ("ink_light", 3))
DEGRADED_CUES = (("residue", 3), ("truncated", 3), ("flagged", 2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="../open-guji-dataset/char-normalization")
    ap.add_argument("--output", default="output")
    ap.add_argument("--page-type", default="../open-guji-dataset/page-type/expected.json")
    ap.add_argument("--instances-gold",
                    default="../open-guji-dataset/char-segmentation/instances/expected.json")
    ap.add_argument("--pool", type=int, default=500, help="每册随机评估池大小")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    dataset = Path(args.dataset)
    output_root = Path(args.output)
    commit = git_commit()
    page_gold = json.loads(Path(args.page_type).read_text(encoding="utf-8"))

    rows_by_book, pools, patch_roots = {}, {}, {}
    for book in ("vol01", "vol02"):
        body = {g["page"] for g in page_gold
                if g["book"] == book and g["page_type"] == "body"}
        rows_by_book[book] = [r for r in load_index(book, output_root)
                              if r["page"] in body]
        patch_roots[book] = output_root / book / "phase4_chars"
        pools[book] = assessed(rows_by_book[book], patch_roots[book],
                               args.pool, args.seed)

    picked = []                            # (rec, gray, quality, book, tier, cue)
    for cue, per_book in CLEAN_CUES:
        for book in ("vol01", "vol02"):
            for r, g, q in pick(pools[book], cue, per_book):
                picked.append((r, g, q, book, "clean", cue))
    for cue, per_book in DEGRADED_CUES:
        for book in ("vol01", "vol02"):
            for r, g, q in pick(pools[book], cue, per_book):
                picked.append((r, g, q, book, "degraded", cue))
    gold_path = Path(args.instances_gold)
    if gold_path.exists():
        for r, g, q, book, cue in human_seeds(gold_path, rows_by_book,
                                              patch_roots, 6):
            picked.append((r, g, q, book, "degraded", cue))

    # 去重（human seeds 可能与线索抽样撞车）
    seen, uniq = set(), []
    for item in picked:
        if item[0]["id"] in seen:
            continue
        seen.add(item[0]["id"])
        uniq.append(item)

    samples_dir = dataset / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    for old in sorted(samples_dir.iterdir()):
        if old.is_dir():
            for f in old.iterdir():
                f.unlink()
            old.rmdir()

    written = []
    n = 0
    for rec, gray, quality, book, tier, cue in uniq:
        n += 1
        sid = f"{n:03d}"
        if sid in DROP:
            continue
        written.append(write_sample(samples_dir / sid, rec, gray, quality,
                                    book, tier, cue, commit))

    summary = {
        "pipeline_version": commit,
        "n_samples": len(written),
        "n_verified": sum(1 for w in written if w["status"] == "verified"),
        "n_known_defect": sum(1 for w in written if w["status"] == "known_defect"),
        "by_tier": {t: sum(1 for w in written if w["tier"] == t)
                    for t in ("clean", "degraded")},
        "by_cue": {c: sum(1 for w in written if w["sampling_cue"] == c)
                   for c in sorted({w["sampling_cue"] for w in written})},
        "by_book": {b: sum(1 for w in written if w["book"] == b)
                    for b in sorted({w["book"] for w in written})},
        "defects_by_tier": {t: sum(1 for w in written
                                   if w["tier"] == t and w["status"] == "known_defect")
                            for t in ("clean", "degraded")},
    }
    (dataset / "build_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
