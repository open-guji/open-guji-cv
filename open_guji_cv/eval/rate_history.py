# -*- coding: utf-8 -*-
"""人审率台账：每册每次重跑记一行，用来 track「审得越多、后面越省」有多快。

`SEED` ＋ `body_pages` ＋ `measure` ＋ `_hist` 从 `scripts/track_review_rate.py`
搬来（控制台重构 C2）。脚本与控制台现在**共用这一份**——原先控制台是用
`importlib.spec_from_file_location` 反射进 `scripts/` 去调的，那是全仓唯一
一处「路由 import scripts/」，也是 46 条路由里唯一跑不通的那条（方案 §四·3）。

## 搬迁时改的**唯一一处行为**

`measure()` 查字形库的路径，从硬编码 `REPO/output/glyph.db` 改成
`core.workspace.glyph_db_path()`。这是后端任务书 §三·2 点名要消掉的那条：
硬编码那版绕过路径解析，在云端会现造一个 0 字节空库再报
`no such table: admissions`。**这一改会让 `POST /api/review/rate-history`
从「抛 OperationalError」变成「正常记一行」**——是本轮唯一一处有意的行为变化，
其余 45 条快照零差异。

## 一个坑：分「已审段」与「未审段」看

已审页的人审率会被**人裁通道**直接压到近 0（那是「你判过的位不再问你」，不是库变聪明），
拿它算全书会高估进步。真正衡量库长进的是**你还没审过的那些页**——所以每行都带
`unseen_rate`（全书里尚无人裁的页的人审率）。vol02 实测：全书 3.27% → 2.32% 的同期，
未审段 3.46% → 2.68%，后者才是干净的因果。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from ..core.spec import page_key
from ..core.workspace import glyph_db_path
from ..eval.round_check import DATASET, load_verdicts
from ..products.store import ProductStore

REPO = Path(__file__).resolve().parent.parent.parent

#: 台账文件。进版本控制——可再生的只有当前那一行。
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
        return sorted(p for p in body if st.exists(book, "admit_decide", page_key(p)))
    d = st.root / book / "admit_decide"
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
        a = st.read(book, "admit_decide", page_key(pg), "admit_decide")
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
    # 库路径走 `core/workspace`（`GUJI_GLYPH_DB` → `GUJI_WORKSPACE/output/glyph.db`
    # → 仓内默认），**不再硬编码 `REPO/output/glyph.db`**。原先那条写法绕过了
    # 路径解析：云端设了 `GUJI_WORKSPACE` 也没用，会在引擎仓下**当场造出一个
    # 0 字节空库**再去查 `admissions`，报 `no such table: admissions`
    # （控制台重构方案 §四·3 实测，是 46 条路由里唯一跑不通的那条）。
    with sqlite3.connect(str(glyph_db_path())) as c:
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


#: `_hist` 的公开名。脚本与控制台都用它，别再各写各的。
history = _hist
