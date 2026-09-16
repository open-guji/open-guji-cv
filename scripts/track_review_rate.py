# -*- coding: utf-8 -*-
"""人审率台账：每册每次重跑记一行，用来 track「审得越多、后面越省」到底有多快。

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/track_review_rate.py            # 记一行（两册）
    … --books vol02 --note "撤 15 条错刻例后"                                                # 只记一册、带说明
    … --show                                                                                # 只看历史，不写

台账 `output/review_rate_history.jsonl`（进版本控制，可再生的只有当前那一行）。

**口径与实现都在 `open_guji_cv/eval/rate_history.py`**（控制台重构 C2 搬过去的）——
本脚本只是它的命令行外壳。此前控制台是用 `importlib.spec_from_file_location`
反射进本文件来调 `measure()` / `_hist()` 的，那是全仓唯一一处「路由 import scripts/」，
也是 46 条路由里唯一跑不通的那条（脚本里那时写死 `REPO/output/glyph.db`，
绕过 `core/workspace`，云端当场造出空库）。现在两边共用一份。
每行一册一次快照：

    date  book  字位  人审  人审率  已裁决字位  库内该书人裁刻例  判据A  note

## 为什么要有它

产物只保留最新一版，人审率是「当下这一跑」的数字——**上一版是多少，跑完就没了**。
而这条线最该回答的问题恰恰是纵向的：一册书从零开始审，人审率掉得有多快、
拐点在哪、第三册能不能少审几轮。所以每次重跑顺手记一行，别再事后从聊天记录里翻。

## 一个坑：分「已审段」与「未审段」看

已审页的人审率会被**人裁通道**直接压到近 0（那是「你判过的位不再问你」，不是库变聪明），
拿它算全书会高估进步。真正衡量库长进的是**你还没审过的那些页**——所以每行都带
`unseen_rate`（全书里尚无人裁的页的人审率）。vol02 实测：全书 3.27% → 2.32% 的同期，
未审段 3.46% → 2.68%，后者才是干净的因果。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import open_guji_cv.steps  # noqa: E402,F401
from open_guji_cv.eval.rate_history import (HIST, SEED, _hist, body_pages,  # noqa: E402,F401
                                            measure)
from open_guji_cv.products.store import ProductStore  # noqa: E402


def show() -> None:
    rows = _hist()
    for book in sorted({r["book"] for r in rows}):
        rs = [r for r in rows if r["book"] == book]
        rs.sort(key=lambda r: (r.get("ts") or r["date"]))
        first = rs[0]
        print(f"\n== {book} ==  起点 {first['rate']:.2%}（{first['date']}）"
              f" → 现在 {rs[-1]['rate']:.2%}"
              f"，降 {(first['rate'] - rs[-1]['rate']) * 100:.2f} 个点"
              f"（相对 {(1 - rs[-1]['rate'] / max(first['rate'], 1e-9)):.0%}）")
        print(f"  {'日期':10s} {'人审率':>7s} {'未审段':>7s} {'人审/字位':>16s} {'人裁刻例':>8s}  说明")
        for r in rs:
            un = f"{r['unseen_rate']:.2%}" if r.get("unseen_rate") is not None else "—"
            print(f"  {r['date']:10s} {r['rate']:7.2%} {un:>7s}"
                  f" {r['review']:>7,}/{r['slots']:<8,} {r.get('db_human', '—'):>8}"
                  f"  {r.get('note', '')}")


def main() -> int:
    ap = argparse.ArgumentParser(description="人审率台账")
    ap.add_argument("--books", default="vol01,vol02")
    ap.add_argument("--note", default="")
    ap.add_argument("--show", action="store_true", help="只看历史，不记新行")
    a = ap.parse_args()
    if not a.show:
        st = ProductStore()
        HIST.parent.mkdir(parents=True, exist_ok=True)
        with open(HIST, "a", encoding="utf-8") as f:
            for book in [b.strip() for b in a.books.split(",") if b.strip()]:
                rec = measure(book, st)
                if rec is None:
                    print(f"  {book}: 没有 seed_admit 产物，跳过")
                    continue
                if a.note:
                    rec["note"] = a.note
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(f"  记下 {book}: 人审率 {rec['rate']:.2%}"
                      f"（未审段 {rec['unseen_rate']:.2%}）" if rec.get("unseen_rate") is not None
                      else f"  记下 {book}: 人审率 {rec['rate']:.2%}")
    show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
