# -*- coding: utf-8 -*-
"""质量看板：**当前准确率**与**缺陷聚集在哪**。

从 `console/app.py::api_quality` 整体搬来（控制台重构 C2）。这 120 行是
**判准的事实源之一**——比 `reading` 不比 `shape`、conversion 放行、账本
preferred 放行，三条判准连同实测数字与用户裁决日期都写在下面的注释里
（后端任务书 §三·5：「搬它时连注释一起搬，一个字不改」）。

搬迁**只改了两处**，都不碰判准：

1. 函数名 `api_quality` → `quality`；
2. `store = ProductStore()` → `store = store or ProductStore()`（多一个注入口，
   不传时与原来逐字等价）。

判准本身现在与 `eval/rulers.py`、`eval/round_check.py` 同级——三份判准的家一致了。
"""
from __future__ import annotations

from ..products.store import ProductStore


def quality(book: str = "vol01", pages: str = "dev_set",
            store: ProductStore | None = None) -> dict:
    """**质量看板**：当前准确率 + 缺陷聚集在哪。

    人裁完之后最该回答两个问题——「准了没有」和「下一刀该切哪」。此前两个都
    要手写脚本查，这个接口把它们做成一次调用。

    - **准确率**：拿整理本自动金标（`gold/v2_align`）对当前定字，按通道分层。
      金标只覆盖锚得上的页，所以同时报覆盖率，别拿它当全量准确率。
    - **缺陷聚集**：人裁标的切分缺陷按 页 / 列 / slot 聚。**孤例是个案，
      扎堆才是系统性问题**——v1 时代 `report_intrusions.py` 就是靠列级聚集
      找出「13 列整列偏移」的（手册「版面线侵入」一节）。
    """
    from ..core.book import load_book
    from ..gold.v2_align import align_book
    import collections

    store = store or ProductStore()
    bk = load_book(book)
    pgs = bk.resolve_pages(pages)

    # ── 准确率（对整理本金标）─────────────────────────────
    from ..variant_ledger import BookLedger
    ledger = BookLedger.load_or_empty("wuyingdian_zongmu")
    golds = align_book(book, pgs, store)
    gold = {c.id: c for g in golds if g.anchored for c in g.chars}
    by_ch: dict[str, list[int]] = {}
    by_op: dict[str, list[int]] = {}
    errors: list[dict] = []
    n_total = 0
    for pg in pgs:
        a = store.read(book, "seed_admit", page_key(pg), "seed_admit")
        d = store.read(book, "context_decide", page_key(pg), "context_decision")
        if a is None:
            continue
        dd = {r.id: r for cc in (d.columns if d else []) for r in cc.chars}
        for cc in a.columns:
            for r in cc.chars:
                n_total += 1
                g = gold.get(r.id)
                if g is None:
                    continue
                pred = r.char if r.admit else (dd[r.id].char if r.id in dd else None)
                if pred is None:
                    continue
                k = r.channel if r.admit else "人审"
                slot = by_ch.setdefault(k, [0, 0])
                # ⚠️ 比 `reading` 不比 `shape`（2026-09-06 修，variant_strategy.md）。
                # `v2_align` 里 shape = lab.hyp = **当次转写自己**，reading = lab.char
                # 才是整理本给的金标。比 shape 的后果：equal 段恒真（自证，该模块头
                # 「纪律 1」写过），replace 段比的是「这次跟上次一不一样」，与对错无关。
                # 实测 vol02 p1–10：比 shape 报 5 错，比 reading 只有 1 条真错。
                #
                # 第二项是「忠于刻本字形」方针（用户 2026-09-05 定）的要求：金标记过
                # 转换（conversion）的位上，输出**刻本形**同样算对——葢/蓋、卽/即 这类
                # 按刻本形放行是对的，不该记成错误。
                # 第三项（2026-09-06 用户裁决 禀/稟 后补）：整理本与刻本用**同一组里
                # 不同的形**时，`conversion` 不一定为真——整理本印 稟、刻本刻 禀，两边
                # 都在 稟 组里，v2_align 只按字面比，记的是 equal / conversion=False。
                # 这类位上管线按账本 preferred 出刻本形是**对的**（用户 2026-09-05 定的
                # 「忠于刻本字形」），判据不该记成错。所以：pred 与金标同组、且 pred 就是
                # 账本给这组定的 preferred → 算对。
                # 只认 preferred，不认「同组任一形」——否则组内选错形也会被放过。
                ok = ((pred == g.reading) or (g.conversion and pred == g.shape)
                      or ledger.preferred_form(g.reading) == pred)
                slot[0] += ok
                slot[1] += 1
                # 分层：equal 段是自证层，replace 段才是真正的错误样本，别合成一个数看
                lay = by_op.setdefault(g.align_op or "?", [0, 0])
                lay[0] += ok
                lay[1] += 1
                if not ok:
                    errors.append({"id": r.id, "pred": pred, "gold": g.reading,
                                   "shape": g.shape, "align_op": g.align_op,
                                   "channel": k, "cov": (r.evidence or {}).get("cov")})
    acc = [{"channel": k, "ok": v[0], "n": v[1], "acc": round(v[0] / v[1], 4)}
           for k, v in sorted(by_ch.items(), key=lambda x: -x[1][1])]
    by_align = [{"align_op": k, "ok": v[0], "n": v[1], "acc": round(v[0] / v[1], 4)}
                for k, v in sorted(by_op.items(), key=lambda x: -x[1][1])]
    n_gold = sum(v[1] for v in by_ch.values())
    n_ok = sum(v[0] for v in by_ch.values())

    # ── 缺陷聚集（人裁标的切分问题）───────────────────────
    from ..gold.store import GoldStore
    gs = GoldStore()
    page_c: collections.Counter = collections.Counter()
    col_c: collections.Counter = collections.Counter()
    slot_c: collections.Counter = collections.Counter()
    qual_c: collections.Counter = collections.Counter()
    n_def = 0
    try:
        for it in gs.list("char-segmentation/instances"):
            q = (it.expected or {}).get("quality")
            if q not in ("truncated", "contaminated"):
                continue
            an = it.anchor
            if getattr(an, "book", None) != book or getattr(an, "page", None) not in pgs:
                continue
            n_def += 1
            qual_c[q] += 1
            page_c[an.page] += 1
            if an.col is not None:
                col_c[an.col] += 1
            if an.slot is not None:
                slot_c[an.slot] += 1
    except Exception:
        pass

    def top(c, k=6):
        return [{"key": str(a), "n": b} for a, b in c.most_common(k)]

    return {
        "book": book, "pages": len(pgs),
        "accuracy": {"overall": round(n_ok / n_gold, 4) if n_gold else None,
                      "n_gold": n_gold, "n_total": n_total,
                      "gold_coverage": round(n_gold / n_total, 4) if n_total else None,
                      "by_channel": acc, "by_align_op": by_align,
                      "errors": errors[:20]},
        "defects": {"n": n_def, "by_quality": top(qual_c),
                     "by_page": top(page_c), "by_col": top(col_c),
                     "by_slot": top(slot_c)},
    }
