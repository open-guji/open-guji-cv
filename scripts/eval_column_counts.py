# -*- coding: utf-8 -*-
"""逐列字数（char-segmentation/column-counts）：切分产物每列切出几个字，对不对得上金标。

金标是殿本 vol01–10 的「daizhige × release 双源一致」列（`label_origin=consensus`）加人裁过的列
（`human`），见 doc/design/19 §三 与分片 README。被测是现行 v2 链 `cell_shrink` 产物：
一列里 `cell_type == "char"` 的实例数（正文、夹注 a/b、單行小注都算一个字）。

报：总的全对率；按列型分层（正文 / 夹注 / 抬头）；按册；错列清单（前 N 条）。
**这是报告型评测，不设回归门**：金标有残错（抽检估计见分片 README），
凡要据此下结论的改动，把前后翻转的列出图人看（设计 §三.4）。

用法：PYTHONPATH=. python scripts/eval_column_counts.py <数据集根或分片目录> [--books vol04,vol05]
        [--pages-file pages.json] [--json-out report.json] [--no-ensure] [--show 30]
`--pages-file`：{册: [页…]}，只评这些页（例：研究文档测试 B 的 100 页）。
缺产物时默认用现有引擎补跑 Step1–4（`_v2_step4.V2Book.ensure`）；`--no-ensure` 则跳过缺页并报出来。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SHARD = "char-segmentation/column-counts"


def col_kind(exp: dict) -> str:
    if exp.get("note"):
        return "夹注列"
    if (exp.get("start") or 0) < 0:
        return "抬头列"
    return "正文列"


def load_gold(root: Path) -> list[dict]:
    """root 可以是数据集根，也可以直接是分片目录（registry 传的是后者）。"""
    f = root / SHARD / "items.jsonl"
    if not f.exists():
        f = root / "items.jsonl"
    out = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        it = json.loads(ln)
        if it.get("status", "active") == "active" and it.get("label_origin") in ("consensus", "human"):
            out.append(it)
    return out


def predicted_counts(pc) -> dict[int, int]:
    """PageChars → {列号: 字数}。"""
    out = {}
    for c in pc.columns:
        out[c.col] = sum(1 for r in c.chars if r.cell_type == "char")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--books", default="")
    ap.add_argument("--pages-file")
    ap.add_argument("--json-out")
    ap.add_argument("--no-ensure", action="store_true")
    ap.add_argument("--show", type=int, default=30)
    a = ap.parse_args()

    gold = load_gold(Path(a.dataset))
    books = set(filter(None, a.books.split(",")))
    only = json.loads(Path(a.pages_file).read_text()) if a.pages_file else None
    by_page: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for it in gold:
        b, p = it["anchor"]["book"], int(it["anchor"]["page"])
        if books and b not in books:
            continue
        if only is not None and p not in set(only.get(b, [])):
            continue
        by_page[(b, p)].append(it)
    if not by_page:
        print("没有可评的金标列——空跑，不算数")
        raise SystemExit(1)

    from _v2_step4 import V2Book
    vb: dict[str, V2Book] = {}
    pages_by_book: dict[str, set[int]] = defaultdict(set)
    for b, p in by_page:
        pages_by_book[b].add(p)
    missing: dict[str, list[int]] = {}
    for b, pgs in pages_by_book.items():
        vb[b] = V2Book(b)
        if a.no_ensure:
            miss = sorted(p for p in pgs if not vb[b].has_step4(p))
        else:
            miss = vb[b].ensure(sorted(pgs))
        if miss:
            missing[b] = miss

    T = Counter()
    kinds = defaultdict(Counter)
    per_book = defaultdict(Counter)
    wrong = []
    for (b, p), items in sorted(by_page.items()):
        if p in set(missing.get(b, [])):
            T["no_product_cols"] += len(items)
            continue
        pred = predicted_counts(vb[b].chars(p))
        for it in items:
            col = int(it["anchor"]["col"])
            n = int(it["expected"]["n"])
            got = pred.get(col, 0)
            k = col_kind(it["expected"])
            ok = got == n
            T["n"] += 1
            T["ok"] += ok
            kinds[k]["n"] += 1
            kinds[k]["ok"] += ok
            per_book[b]["n"] += 1
            per_book[b]["ok"] += ok
            if not ok:
                wrong.append({"id": it["id"], "kind": k, "pred": got, "gold": n,
                              "text": it["expected"].get("text", "")})

    def rate(c):
        return round(c["ok"] / c["n"], 4) if c["n"] else None

    rep = {"cols": T["n"], "ok": T["ok"], "acc": rate(T), "no_product_cols": T["no_product_cols"],
           "missing_pages": missing,
           "by_kind": {k: {"n": c["n"], "ok": c["ok"], "acc": rate(c)} for k, c in kinds.items()},
           "by_book": {b: {"n": c["n"], "ok": c["ok"], "acc": rate(c)} for b, c in sorted(per_book.items())},
           "over": sum(1 for w in wrong if w["pred"] > w["gold"]),
           "under": sum(1 for w in wrong if w["pred"] < w["gold"]),
           "wrong": wrong}
    print(f"逐列字数全对 {T['ok']}/{T['n']} = {rate(T)}（多切 {rep['over']} 列、少切 {rep['under']} 列）")
    for k, c in sorted(kinds.items()):
        print(f"  {k} {c['ok']}/{c['n']} = {rate(c)}")
    for b, c in sorted(per_book.items()):
        print(f"  {b} {c['ok']}/{c['n']} = {rate(c)}")
    if missing:
        print(f"缺产物（未评）：{missing}")
    for w in wrong[: a.show]:
        print(f"  ✗ {w['id']} {w['kind']} 切出 {w['pred']} / 金标 {w['gold']}  {w['text']}")
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
