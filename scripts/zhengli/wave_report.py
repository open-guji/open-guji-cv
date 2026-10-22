#!/usr/bin/env python3
"""每波归因报告（M9 D6-6，GUJI-670）：一波各册待审格按主成因汇总，派给对口的人；和上一波比，看各家改动的实际收益。

    python scripts/zhengli/wave_report.py --products <产物根> [--books vol04,…,vol10] --wave 1 \\
        [--prev <上一波 wave.json>] [--bench <eval_rough_bench --out 的 json> …] --out-dir <目录>

- 产物根＝这一波各册出口时的产物（如各册 main 包取回的根；`guji products pack fetch <册> --to <根>`）。
  每格的码由 `open_guji_cv/review/causes.py` 判（同 `guji audit reasons`），只读 seed_admit／align_ref。
- `--prev`：上一波本脚本出的 `wave.json`。按码、按册报增减，另列「上一波待审、这一波不用审了」的格数（收益）
  和新冒出来的格数。格号随切分会漂，增减按码计数比，不逐格对。
- `--bench`：这一波各家改动在粗校基准上的结果（`scripts/eval_rough_bench.py --var … --out`），列进「上一波改动的收益」。
- 出 `wave.json`（下一波的 `--prev`）和 `wave.md`（贴 Jira 的正文：成因分布、派单、收益、下一波目标）。

只读产物，只写 `--out-dir`。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from open_guji_cv.review.causes import CAUSES, book_causes  # noqa: E402

DEFAULT_BOOKS = tuple(f"vol{i:02d}" for i in range(4, 11))
TOP = 10
NOT_FIXED = {"不修，交 M10", "人认字"}      # 下一波目标不列：不是机器能修的


def wave_stats(products: Path, books) -> dict:
    """各册 → {n, by_cause, cells: {格号: [码, 细节]}}。"""
    out = {}
    for b in books:
        res = book_causes(products, b)
        out[b] = {"n": len(res), "by_cause": dict(sorted(Counter(v["cause"] for v in res.values()).items())),
                  "cells": {k: [v["cause"], v["detail"]] for k, v in sorted(res.items())}}
    return out


def totals(stats: dict) -> Counter:
    c: Counter = Counter()
    for s in stats.values():
        c.update(s["by_cause"])
    return c


def _kind(code: str, detail: str) -> str:
    """切分类的细节带格号和字数，归成一类再数（「格数少于整理本字数（6 < 11）」→「格数少于整理本字数」）。"""
    if code.startswith("A"):
        return re.sub(r"\d+", "N", re.split(r"[（(]", detail, maxsplit=1)[0]).strip()
    return detail


def owners(stats: dict) -> dict[str, dict]:
    """交给谁 → {n, codes: {码: 格数}, top: 最常见的细节（字对、字组码）}。"""
    out: dict[str, dict] = defaultdict(lambda: {"n": 0, "codes": Counter(), "top": Counter()})
    for s in stats.values():
        for code, detail in s["cells"].values():
            who = CAUSES.get(code, ("", "其他"))[1]
            o = out[who]
            o["n"] += 1
            o["codes"][code] += 1
            if detail:
                o["top"][f"{code} {_kind(code, detail)}"] += 1
    return {k: {"n": v["n"], "codes": dict(v["codes"]), "top": v["top"].most_common(TOP)}
            for k, v in sorted(out.items(), key=lambda kv: -kv[1]["n"])}


def delta(prev: dict, cur: dict) -> dict:
    """按码、按册的增减；逐格只看「同格号同码」还在不在（格号会漂，只作参考）。"""
    books = sorted(set(prev) | set(cur))
    by_code: dict[str, dict] = {}
    for code in CAUSES:
        row = {b: (cur.get(b, {}).get("by_cause", {}).get(code, 0) - prev.get(b, {}).get("by_cause", {}).get(code, 0))
               for b in books}
        if any(row.values()):
            by_code[code] = row
    gone = new = 0
    for b in books:
        p, c = (prev.get(b) or {}).get("cells", {}), (cur.get(b) or {}).get("cells", {})
        gone += sum(1 for k in p if k not in c)
        new += sum(1 for k in c if k not in p)
    return {"by_code": by_code, "gone_cells": gone, "new_cells": new,
            "n_prev": sum(s["n"] for s in prev.values()), "n_cur": sum(s["n"] for s in cur.values())}


def render_md(wave: str, stats: dict, prev: dict | None, benches: list[dict], products: str) -> str:
    books = list(stats)
    tot = totals(stats)
    n = sum(tot.values())
    L = [f"# 第 {wave} 波归因报告（{dt.date.today().isoformat()}）", "",
         f"- 册：{', '.join(books)}；待审格共 **{n}**。产物根 `{products}`。",
         "- 每格一个主成因码（`review/causes.py`，同 `guji audit reasons`）。「I 证据不足」是兜底，设计要它 < 10%。", ""]
    L += ["## 一、成因分布", "", "| 码 | 成因 | 交给 | " + " | ".join(books) + " | 合计 | 占比 |",
          "|---|---|---|" + "---|" * len(books) + "---|---|"]
    for code, (name, who) in CAUSES.items():
        if tot.get(code):
            L.append(f"| {code} | {name} | {who} | " + " | ".join(str(stats[b]["by_cause"].get(code, 0)) for b in books)
                     + f" | {tot[code]} | {tot[code] / n:.0%} |")
    L.append("| | 合计 | | " + " | ".join(str(stats[b]["n"]) for b in books) + f" | {n} | |")
    L += ["", "## 二、派单（谁收什么）", ""]
    for who, o in owners(stats).items():
        codes = "、".join(f"{c} {k}" for c, k in sorted(o["codes"].items(), key=lambda kv: -kv[1]))
        L.append(f"- **{who}**：{o['n']} 格（{codes}）")
        if o["top"]:
            L.append("  - 最常见：" + "；".join(f"{d} ×{k}" for d, k in o["top"]))
    L += ["", "格清单在 `wave.json` 的 `stats.<册>.cells`（格号 → [码, 细节]），按码筛出来交给对口的人。", ""]
    L += ["## 三、上一波改动的实际收益", ""]
    if prev:
        d = delta(prev, stats)
        L.append(f"- 待审 {d['n_prev']} → {d['n_cur']}（{d['n_cur'] - d['n_prev']:+d}）；上一波的格号这一波不在待审里的 "
                 f"{d['gone_cells']} 格，新出现的 {d['new_cells']} 格（格号随切分会漂，只作参考）。")
        if d["by_code"]:
            pb = sorted(set(prev) | set(stats))
            L += ["", "| 码 | " + " | ".join(pb) + " | 合计 |", "|---|" + "---|" * len(pb) + "---|"]
            for code, row in d["by_code"].items():
                L.append(f"| {code} | " + " | ".join(f"{row[b]:+d}" if row[b] else "0" for b in pb)
                         + f" | {sum(row.values()):+d} |")
    else:
        L.append("- 没有上一波的 `wave.json`，这是第一份，下一波起比。")
    if benches:
        L += ["", "粗校基准上的结果（`scripts/eval_rough_bench.py`）：", "",
              "| 改动 | 正文送审率（基线 → 变体） | 差 | 新增错放 | 改对 |", "|---|---|---|---|---|"]
        for r in benches:
            vs = r.get("variants") or {}
            names = list(vs)
            for v in names[1:]:
                a, b = vs[names[0]], vs[v]
                L.append(f"| {v} | {a['review_rate_body']:.3%} → {b['review_rate_body']:.3%} | {b['review_rate_diff']:+.3%} | "
                         f"{len(b['new_wrong'])} | {len(b['fixed_wrong'])} |")
    L += ["", "## 四、下一波目标", ""]
    fixable = [(c, k) for c, k in tot.most_common() if CAUSES[c][1] not in NOT_FIXED]
    for code, k in fixable[:5]:
        name, who = CAUSES[code]
        L.append(f"- {code}（{name}）{k} 格 → 交 {who}；目标先降一半（{k} → {k // 2}），在粗校基准上验证、新增错放为 0 才进 rc。")
    share_i = tot.get("I", 0) / n if n else 0
    L.append(f"- 兜底「I 证据不足」现占 {share_i:.0%}（线 < 10%）。")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--products", required=True)
    ap.add_argument("--books", default=",".join(DEFAULT_BOOKS))
    ap.add_argument("--wave", required=True)
    ap.add_argument("--prev", default=None)
    ap.add_argument("--bench", action="append", default=[])
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    books = [b.strip() for b in a.books.split(",") if b.strip()]
    stats = wave_stats(Path(a.products), books)
    prev = json.loads(Path(a.prev).read_text(encoding="utf-8"))["stats"] if a.prev else None
    benches = [json.loads(Path(f).read_text(encoding="utf-8")) for f in a.bench]
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "wave.json").write_text(json.dumps({"wave": a.wave, "products": a.products, "stats": stats},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    md = render_md(a.wave, stats, prev, benches, a.products)
    (out / "wave.md").write_text(md, encoding="utf-8")
    tot = totals(stats)
    print(f"第 {a.wave} 波：待审 {sum(tot.values())} 格 {dict(tot.most_common())} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
