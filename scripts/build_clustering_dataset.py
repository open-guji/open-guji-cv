"""生成保守聚类 purity 数据集（open-guji-dataset/char-clustering）。

三个分片，两种标注来源，**分层评测靠的就是这个分层**：

| 分片 | 来源 | label_origin | 用途 |
|---|---|---|---|
| 001-vol01-body | vol01 正文页整理本对齐 | align | 规模够大，看趋势 |
| 002-vol02-body | vol02 正文页整理本对齐 | align | 跨册泛化（同版不同册刻工有差异）|
| 003-book9all-human | glyph_store 人工确认簇 | human | purity 硬约束卡的是**这个数** |

三条抽样纪律（making-datasets.md 第四步）：

1. **只收正文页**：页型取 `page-type` 金标的 `body`，不用管线自己判
   （它把 roster/toc 全归 body）。
2. **按整页抽，不按字抽**：随机挑页直到凑够 `--max-instances`。按字抽会
   悄悄改变字频分布——而 purity 是按实例加权的，字频一变数字就不可比。
3. **难例对的抽样线索必须与判据不同**（第四步第 4 条）。所以 `diff` 对取
   自**转写混淆表**（OCR+LM 认错的那些字对），`same` 对取自**墨色两极**
   （`ink_ratio` 来自 extractor）——两者都与 `verify_pair` 的 F1 无关。
   用 F1 挑难例再拿 F1 去判，是自证。

字块**冻结成归一图存进数据集**：金标挂在图上就不会随上游漂
（making-datasets.md 第一步）。features.npz 不存——特征是冻结图的纯函数，
存了反而多一份会过期的副本。

**--pipeline-rev**：本数据集必须从 `PIPELINE_REV` 那一版产物重建——上游在
a435d7b 重跑了全部切分（格高改由实测字距定），但 phase6 转写没重跑，而且
「格高一变，page:col:idx 指向的字本身就换了人」（instances 第九轮重标的
实测结论），结构指纹相同也保证不了字没换。所以旧转写对新图块做对齐 =
系统性错标。重建时脚本自动从 git 取那一版的 phase4/phase6；要迁到新切分，
必须先在新 phase4 上重跑 label/refine，再改这个常量。

**tier 分层**（2026-08 起）：每个实例在**原始图块**上跑 `crop_quality`
分成 clean（完整、无残留）/ degraded（有残留或被切）。算法目标分两档：
干净层 purity 是硬约束里的硬约束；退化层单独报，能不崩、可标记即可。
分级不能在冻结的归一图上做——那已经过了归一化自己的清理，量不出输入的脏。

用法：
    python scripts/build_clustering_dataset.py --dataset ../open-guji-dataset/char-clustering
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.align_label import (BLANK_INK, carrier_slots,
                                                 clean_labels, label_book,
                                                 summarize)
from open_guji_cv.clustering.crop_quality import assess_crop
from open_guji_cv.clustering.normalize import (MARGIN_RATIO, NOISE_AREA,
                                               NORM_SIZE, normalize_patch)

SOURCE_ITEM = "06061300.cn"        # 武英殿刻本《欽定四庫全書總目》卷首（page-type 同源）
PIPELINE_REV = "502fa04d0c"        # 冻结的上游产物版本（见文件头 --pipeline-rev）
FEATURE_BACKEND = "hog"
MAX_CONFUSION_PAIRS = 40
MAX_INK_PAIRS = 40
def materialize_rev(rev: str, books: tuple[str, ...] = ("vol01", "vol02")) -> Path:
    """从 git 把 rev 那一版的 phase4/phase6 铺到临时目录，返回 output 根。"""
    root = Path(tempfile.gettempdir()) / f"guji-output-{rev}"
    marker = root / ".complete"
    if marker.exists():
        return root / "output"
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for b in books:
        paths += [f"output/{b}/phase4_chars", f"output/{b}/phase6_labels"]
    subprocess.run(f"git archive {rev} {' '.join(paths)} | tar -x -C {root}",
                   shell=True, check=True)
    marker.touch()
    return root / "output"


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       text=True).strip()
    except Exception:                                    # pragma: no cover
        return "unknown"


def margins_of(rec: dict) -> tuple[int, int]:
    """核心区（bbox 去 padding）到图块边缘的像素距离，量 tier 用。"""
    bh = rec["bbox"][3] - rec["bbox"][1]
    bw = rec["bbox"][2] - rec["bbox"][0]
    return (max(0, int(round((bh - rec["height"]) / 2))),
            max(0, int(round((bw - rec["width"]) / 2))))


def crop_name(instance_id: str) -> str:
    """instance_id → 文件名。冒号在 Windows 上不能做文件名，换下划线。"""
    return instance_id.replace(":", "_") + ".png"


def norm_params() -> dict:
    return {"size": NORM_SIZE, "margin_ratio": MARGIN_RATIO,
            "noise_area": NOISE_AREA, "stroke_width": 3}


def save_norm(gray: np.ndarray, path: Path) -> None:
    cv2.imwrite(str(path), normalize_patch(gray) * 255)


# ── 抽样 ────────────────────────────────────────────────────────────

def pick_pages(labels, max_instances: int, seed: int) -> set[str]:
    """随机挑整页直到凑够 max_instances（按页抽，见文件头第 2 条）。"""
    per_page: dict[str, int] = defaultdict(int)
    for x in labels:
        per_page[x.page] += 1
    pages = sorted(per_page)
    random.Random(seed).shuffle(pages)
    chosen: set[str] = set()
    total = 0
    for p in pages:
        if total >= max_instances:
            break
        chosen.add(p)
        total += per_page[p]
    return chosen


# ── 难例对 ──────────────────────────────────────────────────────────

# 聚类实测漏网的形近家族（g3g4_error_analysis.md：在 coverage 判据较宽松的
# 操作点下真实发生过错并的字对）。进永久回归：verify 判据每次改动，这些
# `diff` 对都必须保持不同簇。线索来源是**聚类自己的失败记录**，与转写混淆
# 表互补——两者都独立于当前判据的打分。
CLUSTER_LEAK_FAMILIES = [
    ("諭", "論"), ("遺", "還"), ("圓", "圖"), ("大", "太"), ("廣", "贋"),
    ("候", "侯"), ("間", "問"), ("已", "巳"), ("曾", "會"), ("選", "過"),
    ("人", "入"), ("未", "末"), ("面", "而"), ("夬", "夫"), ("彖", "象"),
    # 彖/象：502fa04 轮实测混簇（易类文本 彖曰/象曰 都高频）。注意 彖 在
    # PP-OCR 字表之外（G5 的 1.20% 结构性天花板名单），OCR 载体永远发不出
    # equal 的 彖 实例，这对在载体升级前不会物化——名单先挂上。
]
MAX_LEAK_PAIRS_PER_FAMILY = 3


def leak_diff_pairs(labels) -> list[dict]:
    """漏网家族 → `diff` 难例对。两端只取 `equal` 实例（标签最干净）。"""
    by_char: dict[str, list[str]] = defaultdict(list)
    for x in labels:
        if x.op == "equal":
            by_char[x.char].append(x.instance_id)
    for v in by_char.values():
        v.sort()
    out = []
    for c1, c2 in CLUSTER_LEAK_FAMILIES:
        a_ids, b_ids = by_char.get(c1, []), by_char.get(c2, [])
        for k in range(min(MAX_LEAK_PAIRS_PER_FAMILY, len(a_ids), len(b_ids))):
            out.append({"a": a_ids[k], "b": b_ids[k], "relation": "diff",
                        "origin": "cluster_leak",
                        "note": f"聚类实测漏网家族 {c1}/{c2}"})
    return out


def confusion_diff_pairs(labels, limit: int = MAX_CONFUSION_PAIRS) -> list[dict]:
    """`diff` 难例对：转写把 A 认成了 B → 取一个真 A、一个真 B，判定不得同簇。

    线索是转写混淆（OCR 候选 + LM 排序的产物），与配准 F1 无关。
    对的两端只取 `equal` 实例：它们的标签被转写与语料同时印证，最干净——
    难例对本身要是带噪声，报出来的 hard_pair_accuracy 就没法看了。
    """
    by_char: dict[str, list[str]] = defaultdict(list)
    for x in labels:
        if x.op == "equal":
            by_char[x.char].append(x.instance_id)
    for v in by_char.values():
        v.sort()

    confusions: dict[tuple[str, str], int] = defaultdict(int)
    for x in labels:
        if x.op == "replace" and x.hyp != x.char:
            key = (x.hyp, x.char) if x.hyp < x.char else (x.char, x.hyp)
            confusions[key] += 1

    out: list[dict] = []
    for (a_char, b_char), n in sorted(confusions.items(), key=lambda kv: (-kv[1], kv[0])):
        if len(out) >= limit:
            break
        if not by_char.get(a_char) or not by_char.get(b_char):
            continue
        out.append({"a": by_char[a_char][0], "b": by_char[b_char][0],
                    "relation": "diff", "origin": "align/confusion",
                    "note": f"转写混淆 {a_char}↔{b_char} ×{n}"})
    return out


def ink_extreme_same_pairs(labels, ink_of: dict[str, float],
                           limit: int = MAX_INK_PAIRS) -> list[dict]:
    """`same` 难例对：同一个字，墨色最淡与最浓的两个实例，判定应当同簇。

    线索是 extractor 的 `ink_ratio`（切分阶段的量），与聚类判据无关。
    刻本着墨浓淡是同字不同形的第一大来源，这批对正是笔宽归一要扛的东西。
    """
    by_char: dict[str, list[str]] = defaultdict(list)
    for x in labels:
        if x.op == "equal" and x.instance_id in ink_of:
            by_char[x.char].append(x.instance_id)

    cand = []
    for ch, ids in by_char.items():
        if len(ids) < 2:
            continue
        ids = sorted(ids, key=lambda i: ink_of[i])
        spread = ink_of[ids[-1]] - ink_of[ids[0]]
        cand.append((spread, ch, ids[0], ids[-1]))
    cand.sort(key=lambda t: (-t[0], t[1]))

    return [{"a": lo, "b": hi, "relation": "same", "origin": "align/ink_extreme",
             "note": f"{ch} 墨色 {ink_of[lo]:.3f}→{ink_of[hi]:.3f}"}
            for spread, ch, lo, hi in cand[:limit]]


# ── 分片构建 ────────────────────────────────────────────────────────

def build_align_shard(book: str, out_dir: Path, output_root: Path,
                      corpus: Path, body_pages: set[str],
                      max_instances: int, seed: int, commit: str,
                      carrier: Path | None = None) -> dict:
    slots = carrier_slots(carrier) if carrier else None
    labels, stats = label_book(book, output_root / book, corpus,
                               pages=body_pages, slots_by_page=slots)
    page_stats = summarize(stats)

    index = {}
    with open(output_root / book / "phase4_chars" / "index.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            index[r["id"]] = r
    ink_all = {i: r["ink_ratio"] for i, r in index.items()}

    labels, dropped = clean_labels(labels, index)
    chosen = pick_pages(labels, max_instances, seed)
    picked = [x for x in labels if x.page in chosen]
    ink_of = {x.instance_id: ink_all[x.instance_id]
              for x in picked if x.instance_id in ink_all}

    crops = out_dir / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    for old in crops.glob("*.png"):
        old.unlink()

    instances = []
    for x in sorted(picked, key=lambda x: (int(x.page), x.instance_id)):
        rec = index.get(x.instance_id)
        if rec is None:                       # 结构校验已挡住，兜底不致命
            continue
        gray = cv2.imread(str(output_root / book / "phase4_chars" / rec["patch_path"]),
                          cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        name = crop_name(x.instance_id)
        save_norm(gray, crops / name)
        q = assess_crop(gray, margins=margins_of(rec))
        instances.append({"instance_id": x.instance_id, "crop": f"crops/{name}",
                          "char": x.char, "label_origin": "align",
                          "align_op": x.op, "align_run": x.op_run,
                          "page": x.page, "ink_ratio": rec["ink_ratio"],
                          # 粗分块要用的原始纵横比：归一图是正方形，问不出来
                          "hw_ratio": round(rec["height"] / max(rec["width"], 1e-6), 4),
                          "tier": q.tier, "tier_detail": q.to_dict()})

    have = {i["instance_id"] for i in instances}
    pairs = [p for p in (confusion_diff_pairs(picked)
                         + ink_extreme_same_pairs(picked, ink_of)
                         + leak_diff_pairs(picked))
             if p["a"] in have and p["b"] in have]
    # 同一对实例可能同时来自混淆表与漏网表，去重（保留先出现的）
    seen_ab, uniq_pairs = set(), []
    for p in pairs:
        key = (p["a"], p["b"]) if p["a"] < p["b"] else (p["b"], p["a"])
        if key in seen_ab:
            continue
        seen_ab.add(key)
        uniq_pairs.append(p)
    pairs = uniq_pairs

    expected = {
        "source_item": SOURCE_ITEM,
        "book": book,
        "pipeline_version": commit,
        "label_origin": "align",
        "shard_id": f"{book}/body-{len(chosen)}pages",
        "carrier": "rapidocr-top1-s2t" if carrier else "phase6-ranked",
        "feature_backend": FEATURE_BACKEND,
        "norm_params": norm_params(),
        "pages": sorted(chosen, key=int),
        "cleaning": {"rules": ["非汉字金标（语料换行）",
                               f"replace 且 ink_ratio<{BLANK_INK}（近空格位）",
                               "replace 且 frame_bars（版框横线格位）"],
                     "dropped_book_wide": dropped},
        "instances": instances,
        "hard_pairs": pairs,
        "schema_version": 1,
    }
    _write_json(out_dir / "expected.json", expected)
    return {"shard": out_dir.name, "page_stats": page_stats, "cleaned": dropped,
            "n_instances": len(instances), "n_pages": len(chosen),
            "n_chars": len({i["char"] for i in instances}),
            "n_equal": sum(1 for i in instances if i["align_op"] == "equal"),
            "n_replace": sum(1 for i in instances if i["align_op"] == "replace"),
            "n_hard_pairs": len(pairs),
            "tiers": {t: sum(1 for i in instances if i["tier"] == t)
                      for t in ("clean", "degraded", "empty")}}


# ── 人工层复核表（2026-08-23，逐张目视 94/94）─────────────────────
#
# glyph_store 里的标签全部是 `label_status: propagated`：人工在审查界面确认了
# **一个簇是什么字**，标签再传播给簇内每个成员。**簇里混进来的字就跟着背上
# 了错标**——这正是保守聚类要防的那件事（脏簇批量扩散错误标签），在这份
# 「人工」金标里原样体现了一遍：94 个逐张看下来 11 个对不上，噪声 11.7%。
#
# 所以这一层在进数据集之前必须逐张复核。复核只做两件事，不猜：
#   - 字形毫无歧义的 → 改标（RELABEL），错标实例留在集里，它们正是脏簇的证据；
#   - 两个字之间是硬币两面、或整块根本不是单字的 → 丢掉（DROP），
#     理由写在表上。宁可少，不可脏。
RELABEL: dict[str, tuple[str, str]] = {
    # instance_id: (原标签 → 新标签, 依据)
    "book9all:10:5:17":  ("圖", "守"),    # 宀+寸，与 圖 无一笔相同
    "book9all:150:9:7":  ("圖", "守"),    # 同上，同一个簇错标了两个
    "book9all:148:3:7":  ("論", "確"),    # 石+隺
    "book9all:65:9:5":   ("廢", "札"),    # 木+乚
    "book9all:67:6:7":   ("興", "融"),    # 鬲+虫
    "book9all:75:1:6":   ("書", "盧"),    # 虍+田+皿
    "book9all:98:6:5":   ("識", "林"),    # 双木；左缘另有一条界行残线，字本身清楚
    "book9all:105:1:18": ("筵", "熊"),    # 能+灬，下缘被切了一点
}
DROP: dict[str, str] = {
    "book9all:45:6:18": "标 爲，实为一条横画+界行竖线；「一」与栏线分不开，判不准",
    "book9all:66:6:3":  "标 一，实为氵旁字；沿/治两可，判不准",
    "book9all:89:9:3":  "标 薈，实为四个残字拼在一格，不是单字",
}


def build_human_shard(out_dir: Path, store: Path, commit: str) -> dict:
    """人工确认层：glyph_store 里已冻结图块的实例 + 人工同字对。

    **29 条 impure（`diff`）对全部用不了**：反馈事件只导出了 confirm 的图块，
    impure 那些实例既没有冻结图，编号又指向早已重跑过的 book9all 产物
    （`page:col:idx` 会漂，见 making-datasets.md 第一步）。这条写进
    known_limitation，同时也是给审查导出流程的一个待办：impure 对的两端
    也要落图。
    """
    records = [json.loads(l) for l in
               (store / "instances" / "book9all.jsonl").read_text(
                   encoding="utf-8").splitlines() if l.strip()]
    patches = store / "patches"

    crops = out_dir / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    for old in crops.glob("*.png"):
        old.unlink()

    instances = []
    n_relabeled = 0
    for r in sorted(records, key=lambda r: r["instance_id"]):
        iid = r["instance_id"]
        if iid in DROP:
            continue
        src = patches / crop_name(iid)
        if not src.exists():
            continue
        gray = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        char, status = r["label"], "propagated+reviewed"
        if iid in RELABEL:
            was, char = RELABEL[iid]
            status = f"relabeled(was {was})"
            n_relabeled += 1
        name = crop_name(iid)
        save_norm(gray, crops / name)
        bbox = json.loads(r["bbox"]) if isinstance(r["bbox"], str) else r["bbox"]
        q = assess_crop(gray, margins=margins_of(
            {"bbox": bbox, "height": r["height"], "width": r["width"]}))
        instances.append({"instance_id": iid, "crop": f"crops/{name}",
                          "char": char, "label_origin": "human",
                          "label_status": status,
                          "page": r["page"], "ink_ratio": r["ink_ratio"],
                          "hw_ratio": round(r["height"] / max(r["width"], 1e-6), 4),
                          "tier": q.tier, "tier_detail": q.to_dict()})

    char_of = {i["instance_id"]: i["char"] for i in instances}
    pairs, dropped, flipped = [], 0, 0
    for l in (store / "pairs.jsonl").read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        p = json.loads(l)
        a, b = p["inst_a"], p["inst_b"]
        if a not in char_of or b not in char_of:
            dropped += 1
            continue
        # 复核改标之后，原来的 confirm_same 对可能已经不是同一个字了。
        # 这种对**不能丢**：它就是那个簇当初混进了别的字的直接证据，
        # 正好补上 29 条 impure 对丢失后缺的那类硬负例。
        rel = "same" if char_of[a] == char_of[b] else "diff"
        if rel != p["relation"]:
            flipped += 1
        pairs.append({"a": a, "b": b, "relation": rel,
                      "origin": f"human/{p['origin']}"
                                + ("+review-correction" if rel != p["relation"] else "")})

    # 漏网家族对（人工标签是三个分片里最干净的两端）。P3 轮实锤：
    # 151:8:3(論)×40:2:4(諭) 对级 same（cov=0.9987, wmax=1）在新旧归一图上
    # 都成立——此前 human 分片 purity 1.0 只是合并顺序的运气。钉死进回归。
    by_char_h: dict[str, list[str]] = defaultdict(list)
    for i in instances:
        by_char_h[i["char"]].append(i["instance_id"])
    seen_pairs = {frozenset((p["a"], p["b"])) for p in pairs}
    pinned = [("book9all:151:8:3", "book9all:40:2:4",
               "諭/論 对级漏网实锤（cov=0.9987, wmax=1，穿透完美档）"),
              ("book9all:151:8:3", "book9all:43:5:19",
               "諭/論 对级漏网实锤（cov=0.9930, wmax=9）")]
    for a, b, note in pinned:
        if a in char_of and b in char_of and frozenset((a, b)) not in seen_pairs:
            seen_pairs.add(frozenset((a, b)))
            pairs.append({"a": a, "b": b, "relation": "diff",
                          "origin": "cluster_leak", "note": note})
    for c1, c2 in CLUSTER_LEAK_FAMILIES:
        a_ids, b_ids = sorted(by_char_h.get(c1, [])), sorted(by_char_h.get(c2, []))
        for k in range(min(MAX_LEAK_PAIRS_PER_FAMILY, len(a_ids), len(b_ids))):
            if frozenset((a_ids[k], b_ids[k])) in seen_pairs:
                continue
            seen_pairs.add(frozenset((a_ids[k], b_ids[k])))
            pairs.append({"a": a_ids[k], "b": b_ids[k], "relation": "diff",
                          "origin": "cluster_leak",
                          "note": f"聚类实测漏网家族 {c1}/{c2}"})

    expected = {
        "source_item": SOURCE_ITEM,
        "book": "book9all",
        "pipeline_version": commit,
        "label_origin": "human",
        "shard_id": "book9all/reviewed",
        "review": {"date": "2026-08-23", "method": "逐张目视复核 94/94",
                   "relabeled": {k: v[1] for k, v in RELABEL.items()},
                   "dropped": DROP,
                   "propagated_label_error_rate": round(
                       (len(RELABEL) + len(DROP)) / max(1, len(records)), 4)},
        "feature_backend": FEATURE_BACKEND,
        "norm_params": norm_params(),
        "instances": instances,
        "hard_pairs": pairs,
        "schema_version": 1,
    }
    _write_json(out_dir / "expected.json", expected)
    return {"shard": out_dir.name, "n_instances": len(instances),
            "n_chars": len({i["char"] for i in instances}),
            "n_hard_pairs": len(pairs), "n_pairs_dropped_no_image": dropped,
            "review": {"n_seen": len(records), "n_relabeled": n_relabeled,
                       "n_dropped": len(DROP), "n_pairs_flipped_to_diff": flipped},
            "tiers": {t: sum(1 for i in instances if i["tier"] == t)
                      for t in ("clean", "degraded", "empty")}}


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def write_info(out_dir: Path, info: dict) -> None:
    _write_json(out_dir / "info.json", info)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="../open-guji-dataset/char-clustering")
    ap.add_argument("--pipeline-rev", default=PIPELINE_REV,
                    help="从 git 的这一版取 phase4/phase6（transcription 与切分必须同版）；"
                         "传空串则用工作区 output/")
    ap.add_argument("--carrier-dir", default=None,
                    help="OCR 载体目录（含 carrier_{book}.jsonl，"
                         "由 scripts/build_ocr_carrier.py 生成）。给定时不再依赖 phase6 转写")
    ap.add_argument("--corpus", default="corpus/zongmu_wuyingdian_reference.txt")
    ap.add_argument("--page-type", default="../open-guji-dataset/page-type/expected.json")
    ap.add_argument("--glyph-store", default="glyph_store")
    ap.add_argument("--max-instances", type=int, default=3000, help="每个对齐分片的实例上限")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    dataset = Path(args.dataset)
    if args.pipeline_rev:
        output_root = materialize_rev(args.pipeline_rev)
        commit = args.pipeline_rev
    else:
        output_root = Path("output")
        commit = git_commit()
    page_gold = json.loads(Path(args.page_type).read_text(encoding="utf-8"))

    report = {"pipeline_version": commit, "shards": []}
    for book, name in (("vol01", "001-vol01-body"), ("vol02", "002-vol02-body")):
        body = {g["page"] for g in page_gold
                if g["book"] == book and g["page_type"] == "body"}
        out_dir = dataset / "samples" / name
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.carrier_dir:
            carrier = Path(args.carrier_dir) / f"carrier_{book}.jsonl"
        else:
            # 默认找产物目录里的载体（build_ocr_carrier.py 的推荐落点：
            # 与 phase4 同目录，materialize_rev 会连带取到，天然同版）。
            # 载体入库晚于 PIPELINE_REV 时 archive 里没有 → 回落工作区
            # output/（载体本来就是对 PIPELINE_REV 的切分构建的）。
            carrier = None
            for cand in (output_root / book / "phase4_chars" / "ocr_carrier.jsonl",
                         Path("output") / book / "phase4_chars" / "ocr_carrier.jsonl"):
                if cand.exists():
                    carrier = cand
                    break
            if carrier is None:
                print(f"  警告：{book} 无 OCR 载体，回落 phase6 转写（可能全 <unk>）")
        st = build_align_shard(book, out_dir, output_root, Path(args.corpus),
                               body, args.max_instances, args.seed, commit,
                               carrier=carrier)
        write_info(out_dir, {
            "id": name, "source": SOURCE_ITEM, "source_item": SOURCE_ITEM,
            "book": book,
            "description": f"{book} 正文页整理本对齐标注，{st['n_instances']} 实例 / "
                           f"{st['n_chars']} 字类 / {st['n_pages']} 页",
            "tags": ["align", "body", book],
            "sampling": "page-type 金标 body 页 → 结构一致且锚定成功 → 随机整页抽到上限",
            "bias": "只覆盖能锚定的页（整理本收录 + 转写够好），非全书真实分布",
        })
        report["shards"].append(st)
        print(json.dumps(st, ensure_ascii=False))

    name = "003-book9all-human"
    out_dir = dataset / "samples" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    st = build_human_shard(out_dir, Path(args.glyph_store), commit)
    write_info(out_dir, {
        "id": name, "source": SOURCE_ITEM, "source_item": SOURCE_ITEM,
        "book": "book9all",
        "description": f"人工审查确认的实例，{st['n_instances']} 实例 / "
                       f"{st['n_chars']} 字类 / {st['n_hard_pairs']} 条人工同字对",
        "tags": ["human", "review-feedback", "book9all"],
        "sampling": "第一轮人工审查（27 条事件）confirm 的簇成员，图块已冻结在 glyph_store",
        "bias": "标签是簇级确认后传播到成员的（label_status=propagated），"
                "覆盖的是当时聚类挑出来的簇，不是随机字",
    })
    report["shards"].append(st)
    print(json.dumps(st, ensure_ascii=False))

    _write_json(dataset / "build_report.json", report)


if __name__ == "__main__":
    main()
