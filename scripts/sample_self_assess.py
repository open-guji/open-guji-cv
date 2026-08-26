"""分层抽样出「切分正确率」判读样本（无偏 rand 层 + 定向富集层）。

为什么要定期重抽：定向审查（用户朱批、各专项闸）只看得见**已知病灶**，
报不出「现在整体多准」。全书正确率只有 rand 层（正文页均匀随机）能估，
上一次是 2026-08-24 的 93.0%（n=143），此后 70 个提交动过切分层——
不重抽就不知道修到哪了、也不知道**剩下的主病灶换成谁了**。

三层（沿用 2026-08-24 口径）：
  rand   正文页所有字格均匀随机 —— 唯一能读作全书正确率的层
  tail   列首/列尾定向        —— 历史失败富集区
  flag   带缺陷旗定向          —— 自检队列的精确率抽查
定向层只用来找病灶形态，**不能**混进正确率。

用法：PYTHONPATH=. python scripts/sample_self_assess.py --n-rand 200 \
        --tag r2 --out output/self_assess_r2
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

BOOKS = ("vol01", "vol02")


def body_pages(dataset: Path) -> set[tuple[str, str]]:
    """正文页金标（只优化正文页——非正文各有各的排版规矩）。"""
    gold = json.loads((dataset / "page-type" / "expected.json")
                      .read_text(encoding="utf-8"))
    rows = gold if isinstance(gold, list) else gold.get("pages", [])
    return {(e["book"], str(e["page"])) for e in rows
            if e.get("page_type") == "body"}


def load_cells(body: set) -> list[dict]:
    """全书正文页的字格实例（夹注 a/b 半按各自实例计）。"""
    out = []
    for book in BOOKS:
        p = Path("output") / book / "phase4_chars" / "index.jsonl"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if (r["book"], r["page"]) not in body:
                continue
            if r.get("cell_type") != "char":
                continue
            out.append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="../open-guji-dataset")
    ap.add_argument("--n-rand", type=int, default=200)
    ap.add_argument("--n-tail", type=int, default=60)
    ap.add_argument("--n-flag", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    body = body_pages(Path(a.dataset))
    cells = load_cells(body)
    print(f"正文页 {len(body)}，字格 {len(cells)}")

    # 列尾/列首：按页内该列的格序两端各 2 格
    per_col: dict[tuple, list[dict]] = {}
    for r in cells:
        per_col.setdefault((r["book"], r["page"], r["col"]), []).append(r)
    end_ids = set()
    for k, rows in per_col.items():
        rows.sort(key=lambda r: r["idx"])
        for r in rows[:2] + rows[-2:]:
            end_ids.add(r["id"])

    rng = random.Random(a.seed)
    pool_rand = list(cells)
    rng.shuffle(pool_rand)
    picked = {r["id"]: "rand" for r in pool_rand[:a.n_rand]}

    pool_tail = [r for r in cells if r["id"] in end_ids
                 and r["id"] not in picked]
    rng.shuffle(pool_tail)
    for r in pool_tail[:a.n_tail]:
        picked[r["id"]] = "tail"

    INFO = {"jiazhu"}
    pool_flag = [r for r in cells
                 if set(r.get("flags") or []) - INFO and r["id"] not in picked]
    rng.shuffle(pool_flag)
    for r in pool_flag[:a.n_flag]:
        picked[r["id"]] = "flag"

    by_id = {r["id"]: r for r in cells}
    sample = []
    for cid, stratum in picked.items():
        r = by_id[cid]
        sample.append({"book": r["book"], "page": r["page"], "col": r["col"],
                       "idx": r["idx"], "sub": r.get("sub"),
                       "id": cid, "stratum": stratum,
                       "flags": r.get("flags") or [],
                       "bbox": r["bbox"],
                       "patch_path": r["patch_path"],
                       "seed": f"self_assess_{a.tag}",
                       "label_origin": "model", "schema_version": 1})
    outd = Path(a.out)
    outd.mkdir(parents=True, exist_ok=True)
    (outd / "sample.json").write_text(
        json.dumps(sample, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    print("分层:", dict(Counter(s["stratum"] for s in sample)),
          "→", outd / "sample.json")


if __name__ == "__main__":
    main()
