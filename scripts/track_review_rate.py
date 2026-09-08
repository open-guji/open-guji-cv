# -*- coding: utf-8 -*-
"""人审率台账：每册每次重跑记一行，用来 track「审得越多、后面越省」到底有多快。

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/track_review_rate.py            # 记一行（两册）
    … --books vol02 --note "撤 15 条错刻例后"                                                # 只记一册、带说明
    … --show                                                                                # 只看历史，不写

台账 `output/review_rate_history.jsonl`（进版本控制，可再生的只有当前那一行）。
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
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import open_guji_cv.steps  # noqa: E402,F401
from open_guji_cv.core.spec import page_key  # noqa: E402
from open_guji_cv.eval.round_check import DATASET, load_verdicts  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402

HIST = REPO / "output" / "review_rate_history.jsonl"

#: 台账建立（2026-09-08）之前的历史点，从当时的文档/提交里抄回来。
#: 口径与本脚本一致的才收；早期只有「dev_set 12 页」那种局部数字不收，会误导曲线。
SEED = [
    {"date": "2026-09-06", "book": "vol01", "slots": 16823, "review": 327, "rate": 0.0194,
     "note": "第一册正文 108 页跑通，用户审完前 3 轮（判据 A 16,285/16,285）"},
    {"date": "2026-09-06", "book": "vol01", "slots": 16805, "review": 274, "rate": 0.0163,
     "note": "第一册正文审完（71/79 批落地）"},
    {"date": "2026-09-06", "book": "vol02", "slots": 29362, "review": 2579, "rate": 0.0878,
     "note": "★第二册全书首跑基线（尚未人审，字形库沿用第一册）"},
    {"date": "2026-09-06", "book": "vol02", "slots": 29496, "review": 1596, "rate": 0.0541,
     "note": "九步全新鲜重跑（夹注格首次进金标）"},
    {"date": "2026-09-06", "book": "vol01", "slots": 16805, "review": 108, "rate": 0.0064,
     "note": "拆掉账本误合并的 10 组（注/註 等）"},
    {"date": "2026-09-06", "book": "vol02", "slots": 29476, "review": 1027, "rate": 0.0348,
     "note": "减审三刀：人裁定案 + 拆组 49 对 + 整理本一致放行"},
    {"date": "2026-09-07", "book": "vol01", "slots": 16805, "review": 18, "rate": 0.0011,
     "note": "库清账 15 条错刻例后全量重跑 + 人裁改判对齐"},
    {"date": "2026-09-07", "book": "vol02", "slots": 29476, "review": 965, "rate": 0.0327,
     "note": "同上；用户审到 p50"},
    {"date": "2026-09-07", "book": "vol02", "slots": 29467, "review": 684, "rate": 0.0232,
     "note": "用户审到 p70（+1,515 条裁决）后全量重跑",
     "unseen_pages": "71-188", "unseen_slots": 18748, "unseen_review": 635, "unseen_rate": 0.0339},
]


def body_pages(book: str, st: ProductStore) -> list[int]:
    """**只取正文页**，与判据 B / 对勘报告同口径（`build_collation_report.body_pages`）。

    vol01 的产物有 116 页，其中 p89–95 是职名页、p184 是目录页——版式不同、人审天然高，
    混进来会让 0.11% 看着涨回 0.53%，误判成回退（2026-09-08 建台账时踩到）。
    页型来自金标分片 `page-type`；分片缺失时退回全部有产物的页并在记录里标注。
    """
    f = DATASET / "page-type" / "items.jsonl"
    body = set()
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            anc = r.get("anchor") or {}
            if str(anc.get("book")) == book and (r.get("expected") or {}).get("page_type") == "body":
                body.add(int(anc["page"]))
    if body:
        return sorted(p for p in body if st.exists(book, "seed_admit", page_key(p)))
    d = st.root / book / "seed_admit"
    return sorted(int(p.stem[1:]) for p in d.glob("p*.json")) if d.exists() else []


def measure(book: str, st: ProductStore) -> dict | None:
    pages = body_pages(book, st)
    if not pages:
        return None
    truth = load_verdicts(book)
    tot = auto = exc = 0
    seen_pages, un_tot, un_auto = set(), 0, 0
    per_page: dict[int, tuple[int, int]] = {}
    for pg in pages:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        t0 = r0 = 0
        judged = False
        for cc in a.columns:
            if not cc.ok:
                continue
            for r in cc.chars:
                if "excluded" in (r.doubts or []):
                    exc += 1
                    continue
                t0 += 1
                r0 += (not r.admit)
                if r.id in truth:
                    judged = True
        tot += t0
        auto += t0 - r0
        per_page[pg] = (t0, r0)
        if judged:
            seen_pages.add(pg)
        else:
            un_tot += t0
            un_review = r0
            un_auto += t0 - un_review
    review = tot - auto
    un_review = un_tot - un_auto
    with sqlite3.connect(str(REPO / "output" / "glyph.db")) as c:
        n_human = c.execute(
            "SELECT COUNT(*) FROM admissions WHERE provenance='human' AND instance_id LIKE ?",
            (f"v2:{book}:%",)).fetchone()[0]
    unseen = sorted(set(per_page) - seen_pages)
    return {
        "date": time.strftime("%Y-%m-%d"), "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "book": book, "pages": len(per_page), "slots": tot, "review": review,
        "rate": round(review / max(tot, 1), 6), "excluded": exc,
        "judged_slots": sum(1 for k in truth if k.startswith(f"{book}:")),
        "db_human": n_human,
        "seen_pages": len(seen_pages),
        "unseen_pages": f"{unseen[0]}-{unseen[-1]}" if unseen else "",
        "unseen_slots": un_tot, "unseen_review": un_review,
        "unseen_rate": round(un_review / max(un_tot, 1), 6) if un_tot else None,
    }


def _hist() -> list[dict]:
    rows = list(SEED)
    if HIST.exists():
        rows += [json.loads(x) for x in HIST.read_text(encoding="utf-8").splitlines() if x.strip()]
    return rows


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
