# -*- coding: utf-8 -*-
"""构建匹配**阈值标定**集（glyph-match/pairs）。

    PYTHONPATH=. python scripts/build_match_pairs_dataset.py \
        --clustering ../open-guji-dataset/char-clustering \
        --out ../open-guji-dataset/glyph-match/pairs

## 为什么要这个集

`glyph-match/triplets` 只量**排序**（同字要比形近异字更匹配），可判决用的
是**绝对阈值**（cov ≥ same 闸）。2026-08-24 换 elastic 判据那一轮，所有
的坑都在阈值上——排序明明大幅变好（hard 0.079→0.684），库匹配的 same 档
覆盖率却掉了三到四成，机理（软权对笔画密度敏感）是事后手工从 char-clustering
里刨出 42806 对才看清的。**那件事该有个正经数据集，而不是每次手工重来。**

## 测什么

一对归一图块 → `same` / `diff`，**用来定操作点**：在硬约束
`precision ≥ 0.999` 下，阈值能放行多少真同字对（recall）。

金标定义（标注与评测共用，把「不算什么」也写出来）：

> `same` = 两个图块的金标 surface char **严格相同**；`diff` = 不同。
> - 异体字 / 通假**不算** same（严格按 surface char），但单独打
>   `variant: true` 记账——语义精度是另一本账（见 eval_db_match）；
> - 图块质量**不影响标签**：degraded 的也照标，质量走 `tier` 分层报；
> - 两个实例任一金标有噪声，对标签就跟着有噪声——见 README 的
>   `label_noise`。

主指标对着**危害**，不是对着方便测的量：库匹配判错一对的代价是**把错标
写进库**（会沿簇批量扩散），所以 precision 是硬约束；判漏的代价只是这个
实例改走 OCR+上下文，慢一点而已。所以主输出是
**「硬约束下的最大 recall + 对应阈值」**，不是单一准确率。

## 对从哪来（三个来源分开报，偏置不同）

| origin | 怎么抽 | 为什么要它 |
|---|---|---|
| `knn` | HOG top-k 近邻对（册内 + 跨册）| **生产真正会去验的对群**，操作点必须在它上面标 |
| `random` | 与特征无关的随机配对（同字/异字）| knn 由被测栈自己的第 3 层选出，**有偏**；随机对才是 recall 的无偏估计 |
| `near_form` | `NEVER_MATCH_FAMILIES` 逐族配对 | 人裁来源的硬负例，异字对里最危险的一批 |

`knn` 那一层是**故意**用被测算法选样本的——阈值就是要在这批对上生效。
但它确实有偏（HOG 认为像的对被过采样），所以 `random` 层必须一起报，
两个数不一致本身就是信号。

## 分层（必须分层报，别合成一个数字）

`tier`（clean/degraded）、`ink_bucket`（笔画密度——elastic 的绝对分随它
走低，是这个集的头号用途）、`book`（册内/跨册，跨册＝不同刻工）、
`origin`。

图块冻结为**归一图**（与 char-clustering 同源同格式）：本集测的是第 4 层
判据，它的输入就是归一图。要测归一化本身请用 char-normalization。

评测：scripts/eval_match_pairs.py
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.clustering.features import get_feature  # noqa: E402
from open_guji_cv.clustering.match import NEVER_MATCH_FAMILIES  # noqa: E402

# 笔画密度分档：elastic 的绝对分随墨量走低（vol01 实测过闸率 ink<0.10
# 时 0.60、ink 0.18~0.25 时 0.025），本集的头号用途就是把这条曲线量出来。
INK_EDGES = (0.10, 0.14, 0.18, 0.25)

KNN_K = 10            # 册内近邻对：与生产 GlyphMatcher 的 k 对齐
CROSS_K = 5           # 跨册近邻对（cross-seed 协议的对分布）
N_RANDOM_SAME = 3000  # 无偏同字对（recall 的真实估计）
N_RANDOM_DIFF = 2000  # 无偏异字对（易负例地板）
N_FAMILY_PER = 40     # 每个形近族最多取多少对


def ink_bucket(ratio: float) -> str:
    lo = 0.0
    for e in INK_EDGES:
        if ratio < e:
            return f"{lo:.2f}-{e:.2f}"
        lo = e
    return f"{INK_EDGES[-1]:.2f}+"


def load_shard(shard_dir: Path) -> tuple[list[dict], np.ndarray]:
    data = json.loads((shard_dir / "expected.json").read_text(encoding="utf-8"))
    inst, pats = [], []
    for i in data["instances"]:
        img = cv2.imread(str(shard_dir / i["crop"]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise FileNotFoundError(shard_dir / i["crop"])
        pats.append((img > 127).astype(np.uint8))
        inst.append(i)
    return inst, np.asarray(pats)


def knn_pairs(feats: np.ndarray, k: int) -> set[tuple[int, int]]:
    sims = feats @ feats.T
    np.fill_diagonal(sims, -np.inf)
    out: set[tuple[int, int]] = set()
    for i in range(len(feats)):
        for j in np.argsort(-sims[i])[:k]:
            out.add((min(i, int(j)), max(i, int(j))))
    return out


def cross_knn(fq: np.ndarray, fd: np.ndarray, k: int) -> list[tuple[int, int]]:
    sims = fq @ fd.T
    return [(qi, int(j)) for qi in range(len(fq))
            for j in np.argsort(-sims[qi])[:k]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clustering", required=True, help="char-clustering 数据集目录")
    ap.add_argument("--out", required=True, help="输出目录（glyph-match/pairs）")
    ap.add_argument("--shards", nargs="*",
                    default=["001-vol01-body", "002-vol02-body"])
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    samples = Path(args.clustering) / "samples"
    out = Path(args.out)
    (out / "crops").mkdir(parents=True, exist_ok=True)

    feat = get_feature("hog")
    shards: dict[str, dict] = {}
    for name in args.shards:
        inst, pats = load_shard(samples / name)
        shards[name] = {"inst": inst, "pats": pats,
                        "feats": feat.extract(pats),
                        "book": json.loads((samples / name / "expected.json")
                                           .read_text(encoding="utf-8"))["book"]}
        print(f"[{name}] {len(inst)} 实例", flush=True)

    # ---- 实例表（去重后统一编号；图块冻结进本集，不跨集引用）----
    instances: list[dict] = []
    index: dict[str, int] = {}
    for name, sh in shards.items():
        for i, rec in enumerate(sh["inst"]):
            iid = rec["instance_id"]
            if iid in index:
                continue
            index[iid] = len(instances)
            instances.append({
                "instance_id": iid,
                "char": rec["char"],
                "book": sh["book"],
                "shard": name,
                "tier": rec.get("tier", "unknown"),
                "ink_ratio": rec.get("ink_ratio", 0.0),
                "ink_bucket": ink_bucket(rec.get("ink_ratio", 0.0)),
                "label_origin": rec.get("label_origin", "align"),
                "crop": f"crops/{iid.replace(':', '_')}.png",
            })
            cv2.imwrite(str(out / instances[-1]["crop"]), sh["pats"][i] * 255)

    char_of = {r["instance_id"]: r["char"] for r in instances}
    book_of = {r["instance_id"]: r["book"] for r in instances}

    pairs: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(a: str, b: str, origin: str) -> None:
        key = (a, b) if a < b else (b, a)
        if key in seen or a == b:
            return
        seen.add(key)
        pairs.append({
            "a": key[0], "b": key[1],
            "label": "same" if char_of[key[0]] == char_of[key[1]] else "diff",
            "origin": origin,
            "book": "same" if book_of[key[0]] == book_of[key[1]] else "cross",
        })

    # ---- 1. 册内 kNN：生产真正会验的对群 ----
    for name, sh in shards.items():
        ids = [r["instance_id"] for r in sh["inst"]]
        for i, j in sorted(knn_pairs(sh["feats"], KNN_K)):
            add(ids[i], ids[j], "knn")
        print(f"[{name}] kNN 对累计 {len(pairs)}", flush=True)

    # ---- 2. 跨册 kNN：cross-seed 协议的对分布（不同刻工）----
    names = list(shards)
    for qi in range(len(names)):
        for di in range(len(names)):
            if qi == di:
                continue
            q, d = shards[names[qi]], shards[names[di]]
            qids = [r["instance_id"] for r in q["inst"]]
            dids = [r["instance_id"] for r in d["inst"]]
            for a, b in cross_knn(q["feats"], d["feats"], CROSS_K):
                add(qids[a], dids[b], "knn")
    print(f"跨册 kNN 后累计 {len(pairs)}", flush=True)

    # ---- 3. 随机对：与特征无关，recall 的无偏估计 ----
    by_char: dict[str, list[str]] = defaultdict(list)
    for r in instances:
        by_char[r["char"]].append(r["instance_id"])
    multi = [c for c, v in by_char.items() if len(v) > 1]
    n_same = 0
    while n_same < N_RANDOM_SAME and multi:
        c = rng.choice(multi)
        a, b = rng.sample(by_char[c], 2)
        before = len(pairs)
        add(a, b, "random")
        n_same += len(pairs) - before
    all_ids = [r["instance_id"] for r in instances]
    n_diff = 0
    while n_diff < N_RANDOM_DIFF:
        a, b = rng.sample(all_ids, 2)
        if char_of[a] == char_of[b]:
            continue
        before = len(pairs)
        add(a, b, "random")
        n_diff += len(pairs) - before
    print(f"随机对后累计 {len(pairs)}", flush=True)

    # ---- 4. 形近族：人裁来源的硬负例 ----
    for x, y in NEVER_MATCH_FAMILIES:
        xs, ys = by_char.get(x, []), by_char.get(y, [])
        if not xs or not ys:
            continue
        cand = [(a, b) for a in xs for b in ys]
        rng.shuffle(cand)
        for a, b in cand[:N_FAMILY_PER]:
            add(a, b, "near_form")
    print(f"形近族后累计 {len(pairs)}", flush=True)

    src = json.loads((samples / args.shards[0] / "expected.json")
                     .read_text(encoding="utf-8"))
    payload = {
        "schema_version": 1,
        "source_item": "char-clustering 冻结分片（归一图与金标字同源）",
        "pipeline_version": src.get("pipeline_version"),
        "label_origin": "align",
        "seed": args.seed,
        "ink_edges": list(INK_EDGES),
        "instances": instances,
        "pairs_file": "pairs.jsonl",
        "n_pairs": len(pairs),
    }
    (out / "expected.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    with (out / "pairs.jsonl").open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    n_same = sum(1 for p in pairs if p["label"] == "same")
    print(f"\n→ {out}\n  实例 {len(instances)}  对 {len(pairs)}"
          f"（same {n_same} / diff {len(pairs) - n_same}）")
    for key in ("origin", "book"):
        c: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for p in pairs:
            c[p[key]][0 if p["label"] == "same" else 1] += 1
        print(f"  按 {key}: " + "  ".join(
            f"{k} same{v[0]}/diff{v[1]}" for k, v in sorted(c.items())))


if __name__ == "__main__":
    main()
