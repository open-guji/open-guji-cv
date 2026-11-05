# -*- coding: utf-8 -*-
"""5b「验证整理本字」评测（长期规划 4.1，A23 11-05）。

问题：整理本给了这个字块的字 X（强假设），问「图是不是 X」。X 的 emb 分与机器自己最像的
**另一个字**比，够不够放行当「降人审的证据」（不直接入库）。

在三书人裁 5b 冻结集（`char-clustering/samples/00{4,5,6}-*/rare.jsonl`，
`scripts/build_book_human_shards.py` 建）上：

- **正例**：假设 X = 人裁金标字（整理本对了）；
- **负例**：假设 X' = emb 前 `--neg-k` 里**不是**金标的字（整理本错了、或与书上形近的另一字）。
  最难的一条是机器的错误首位，所以另报「只取最强错字」一档；
- 放行判据：`s(X) - max_{c∉fold(X)} s(c) >= m` 且 `s(X) >= t`（m 可为负＝允许 X 略低于首位）。
  `s` 是 `CnnCandidates.emb_topk_batch` 的分（含字体模板与 GW 变体形档，缺省口径），取前 `--k`；
  X 不在前 k 里按没够分处理；
- **第二路**：分类头 `cls`（只对类内字有信号）同意 X 在它前 `--cls-k` 里。类外字没有这一路，
  单独分层报，不能混着比。

读数：TAR（正例放行率）、FAR（负例放行率）、`prec@prior`（先验整理本正确率 p 下放行集的精度；
p 缺省 0.97）。己已巳、日曰两组评测内折叠（`scripts/eval_fold.py`）：同组字不算竞争者也不算错字。

只读评测脚本，不进包、不改任何 Step 指纹。

    python scripts/eval_ref_verify.py --shard 004-siku-v2-human --shard 005-shiji-human \
        --dataset ../open-guji-dataset/char-clustering --out ref_verify.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_fold import fold, same  # noqa: E402

MARGINS = (-0.10, -0.05, -0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03, 0.05, 0.08)
MINS = (0.0, 0.5, 0.6, 0.7, 0.8)


def competitor_best(cand: list[tuple[str, float]], x: str) -> float:
    """候选里不与 x 同折叠组的最高分（没有就 -1）。"""
    return max((v for c, v in cand if not same(c, x)), default=-1.0)


def score_of(cand: list[tuple[str, float]], x: str):
    return max((v for c, v in cand if same(c, x)), default=None)


def accept(cand, x, m, t, cls_ok=None) -> bool:
    s = score_of(cand, x)
    if s is None or s < t:
        return False
    if s - competitor_best(cand, x) < m:
        return False
    return cls_ok is None or cls_ok


def build_hypotheses(items, embs, neg_k):
    """(正例列表, 负例列表, 最强错字负例列表)；每项 (item_idx, 假设字)。"""
    pos, neg, neg1 = [], [], []
    for i, (it, cand) in enumerate(zip(items, embs)):
        g = it["char"]
        pos.append((i, g))
        wrong = [c for c, _ in cand[:neg_k] if not same(c, g)]
        seen = set()
        wrong = [c for c in wrong if not (fold(c) in seen or seen.add(fold(c)))]
        neg.extend((i, c) for c in wrong)
        if wrong:
            neg1.append((i, wrong[0]))
    return pos, neg, neg1


def sweep(items, embs, clsr, pos, neg, neg1, prior, use_cls, cls_k):
    rows = []

    def ok(i, x, m, t):
        c = None
        if use_cls:
            c = x in [ch for ch, _ in clsr[i][:cls_k]] or any(same(ch, x) for ch, _ in clsr[i][:cls_k])
        return accept(embs[i], x, m, t, c)

    for t in MINS:
        for m in MARGINS:
            tp = sum(ok(i, x, m, t) for i, x in pos)
            fp = sum(ok(i, x, m, t) for i, x in neg)
            fp1 = sum(ok(i, x, m, t) for i, x in neg1)
            tar = tp / len(pos) if pos else 0.0
            far = fp / len(neg) if neg else 0.0
            far1 = fp1 / len(neg1) if neg1 else 0.0
            den = tar * prior + far * (1 - prior)
            den1 = tar * prior + far1 * (1 - prior)
            rows.append({"t": t, "m": m, "tar": tar, "far": far, "far_top_wrong": far1,
                         "prec": tar * prior / den if den else None,
                         "prec_top_wrong": tar * prior / den1 if den1 else None})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", action="append", required=True)
    ap.add_argument("--dataset", default="../open-guji-dataset/char-clustering")
    ap.add_argument("--charset", default="unicode-cjk-ab")
    ap.add_argument("--k", type=int, default=50, help="emb 取前几（X 不在其中算没够分）")
    ap.add_argument("--neg-k", type=int, default=10, help="负例假设取 emb 前几的错字")
    ap.add_argument("--cls-k", type=int, default=5)
    ap.add_argument("--prior", type=float, default=0.97, help="整理本字本身正确率的先验")
    ap.add_argument("--no-flagged", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    import cv2
    from open_guji_cv.clustering.charset_spec import base_charset
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates

    cs = base_charset(a.charset)
    cnn = CnnCandidates(str(DEFAULT_CKPT))
    cnn._ensure()
    classes = set(cnn._classes)
    report = {}
    for shard in a.shard:
        d = Path(a.dataset) / "samples" / shard
        items = [json.loads(l) for l in (d / "rare.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        if a.no_flagged:
            items = [it for it in items if not it.get("selfcheck_flag")]
        if a.limit:
            items = items[:a.limit]
        imgs, kept = [], []
        for it in items:
            im = cv2.imread(str(d / it["png"]), cv2.IMREAD_GRAYSCALE)
            if im is None:
                continue
            imgs.append((im > 127).astype(np.uint8))
            kept.append(it)
        items = kept
        print(f"[{shard}] {len(items)} 条", flush=True)
        embs = cnn.emb_topk_batch(imgs, cs, k=a.k)
        clsr = cnn.topk_batch(imgs, cs, k=a.cls_k)
        groups = {"all": list(range(len(items)))}
        for i, it in enumerate(items):
            for st in it.get("strata", []):
                groups.setdefault(st, []).append(i)
        rep = {}
        for name, idx in groups.items():
            sub_items = [items[i] for i in idx]
            sub_emb = [embs[i] for i in idx]
            sub_cls = [clsr[i] for i in idx]
            pos, neg, neg1 = build_hypotheses(sub_items, sub_emb, a.neg_k)
            top1 = sum(1 for it, c in zip(sub_items, sub_emb) if c and same(c[0][0], it["char"]))
            in_cls = [i for i, it in enumerate(sub_items) if not classes or it["char"] in classes]
            rep[name] = {
                "n": len(idx), "emb_top1_folded": top1 / len(idx),
                "n_neg": len(neg), "n_neg_top_wrong": len(neg1),
                "emb_only": sweep(sub_items, sub_emb, sub_cls, pos, neg, neg1, a.prior, False, a.cls_k),
                "emb_and_cls": sweep(sub_items, sub_emb, sub_cls, pos, neg, neg1, a.prior, True, a.cls_k),
                "n_in_cls_vocab": len(in_cls),
            }
            print(f"\n  [{name}] n={len(idx)} 负例 {len(neg)}（最强错字 {len(neg1)}）emb 折叠后 top1={top1 / len(idx):.3f}")
            print(f'  {"路":<8} {"t":>4} {"m":>6} {"TAR":>6} {"FAR":>6} {"FAR*":>6} {"prec":>6} {"prec*":>6}')
            for route in ("emb_only", "emb_and_cls"):
                for r in rep[name][route]:
                    if r["t"] in (0.0, 0.7) and r["m"] in (-0.05, -0.02, 0.0, 0.02, 0.05):
                        p = f'{r["prec"]:.3f}' if r["prec"] is not None else "-"
                        p1 = f'{r["prec_top_wrong"]:.3f}' if r["prec_top_wrong"] is not None else "-"
                        print(f'  {route:<8} {r["t"]:4.1f} {r["m"]:6.2f} {r["tar"]:6.3f} {r["far"]:6.3f} '
                              f'{r["far_top_wrong"]:6.3f} {p:>6} {p1:>6}')
        report[shard] = rep
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n→ {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
