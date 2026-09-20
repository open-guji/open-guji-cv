# -*- coding: utf-8 -*-
"""Step9-9.0 进度复查：一个页范围内，每页还挂着哪些待办。

用户 2026-09-20：「在第九步做一个总进度复查——检查页范围内还有哪些待办（即使还有待办，
也允许执行 9.1 或 9.2）」。所以这不是闸，是**看板**：只报数、给深链，不拦 9.1/9.2。

每页六个数，来源各不相同，别混：

| 列 | 意思 | 从哪来 |
|---|---|---|
| `stale` | 这一页有几步产物过期/缺失/失败（含人裁失效） | `Engine.status`（指纹 + `invalidated`） |
| `review` | 定字待人审的字位（未放行、且不在排除名单） | `seed_admit` 产物 |
| `cut` | 切线待裁的格位（多候选、没人裁过） | `review/cards.cut_pending` |
| `defect` | 排除名单上但是字的格（seg_defect/damaged，文本出阙文） | `report/slots` |
| `excluded` | 排除名单上的非字格 | 同上 |
| `cols_bad` | Step3 没解出来 / 没过闸的列（这些列文本整列缺） | `cells` 产物 |

`stale` 非零意味着下面几列的数是**旧产物**算的——先重跑再信数。
"""
from __future__ import annotations

from ..core.book import load_book
from ..core.engine import Engine
from ..core.pipeline import default_pipeline_id, load_pipeline
from ..core.spec import page_key
from ..products.store import ProductStore
from .slots import ADMIT_KIND, ADMIT_STEP, CELLS_KIND, cells_step, page_slots

COLS = ("stale", "review", "cut", "defect", "excluded", "cols_bad")


def page_progress(book: str, pages: list[int], store: ProductStore | None = None) -> dict:
    """→ `{"book", "pages": [{"page", 六个数, "stale_steps": [...]}], "totals": {...}}`。"""
    from ..review.cards import cut_pending

    st = store or ProductStore()
    bk = load_book(book)
    eng = Engine(bk, load_pipeline(default_pipeline_id(bk)), store=st, log=lambda s: None)
    status = eng.status(pages=pages)
    stale_steps: dict[int, list[str]] = {pg: [] for pg in pages}
    for sid, d in status["steps"].items():
        for pg, row in d["pages"].items():
            if row["status"] != "fresh":
                stale_steps[int(pg)].append(f"{sid}:{row['status']}")
    cut = cut_pending(book, pages, st)
    cut_by_page: dict[int, int] = {}
    for (pg, _col, _slot) in cut:
        cut_by_page[pg] = cut_by_page.get(pg, 0) + 1

    step3 = cells_step(book)
    rows = []
    totals = {k: 0 for k in COLS}
    for pg in pages:
        row = {"page": pg, "stale": len(stale_steps[pg]), "stale_steps": stale_steps[pg],
               "review": 0, "cut": cut_by_page.get(pg, 0), "defect": 0, "excluded": 0, "cols_bad": 0}
        cells = st.read(book, step3, page_key(pg), CELLS_KIND)
        if cells is not None:
            # 版心（筒子页第 10 列）被闸按 `non_body_column` 拒掉是版式如此，不是待办。
            row["cols_bad"] = sum(1 for c in cells.columns
                                  if not c.ok and "non_body_column" not in (c.error or ""))
        if st.exists(book, ADMIT_STEP, page_key(pg)) and cells is not None:
            try:
                for s in page_slots(st, book, pg, []):
                    if s.kind == "blank":
                        continue
                    if s.excluded:
                        row["excluded"] += 1
                    elif s.defect:
                        row["defect"] += 1
                    elif not s.admit:
                        row["review"] += 1
            except Exception as e:  # noqa: BLE001 —— 一页读坏不拖垮整张看板
                row["stale_steps"].append(f"slots:{type(e).__name__}")
                row["stale"] += 1
        else:
            row["stale_steps"].append(f"{ADMIT_STEP}:missing" if cells is not None else f"{step3}:missing")
            row["stale"] = len(row["stale_steps"])
        for k in COLS:
            totals[k] += row[k]
        rows.append(row)
    # 「无待办」不看 excluded：非字格是已了结的账，不是要人做的事。
    todo = tuple(k for k in COLS if k != "excluded")
    return {"book": book, "pages": rows, "totals": totals,
            "n_pages": len(pages), "n_clean": sum(1 for r in rows if not any(r[k] for k in todo))}


def format_table(doc: dict) -> str:
    head = f"{'页':>4} {'过期':>4} {'待审':>4} {'切线':>4} {'阙文':>4} {'非字':>4} {'坏列':>4}  说明"
    lines = [head]
    for r in doc["pages"]:
        if not any(r[k] for k in COLS if k != "excluded"):
            continue
        note = " ".join(r["stale_steps"][:3]) + ("…" if len(r["stale_steps"]) > 3 else "")
        lines.append(f"{r['page']:>4} {r['stale']:>4} {r['review']:>4} {r['cut']:>4} {r['defect']:>4} "
                     f"{r['excluded']:>4} {r['cols_bad']:>4}  {note}")
    t = doc["totals"]
    lines.append(f"合计 {doc['n_pages']} 页，{doc['n_clean']} 页无待办；过期 {t['stale']} · 待审 {t['review']} · "
                 f"切线 {t['cut']} · 阙文 {t['defect']} · 非字 {t['excluded']} · 坏列 {t['cols_bad']}")
    return "\n".join(lines)
