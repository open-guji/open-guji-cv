# -*- coding: utf-8 -*-
"""组视图：按异体组把字位摊成「列 = 形、格 = 图块」（variant_strategy.md §5.1）。

从 `console/app.py::api_variants_groups` 搬来（控制台重构 C2）。逻辑一行未改，
只动了函数名、`ProductStore` 改成可注入、延迟 import 提到模块级，以及
`HTTPException(404, …)` 换成 `NotFound`（本模块不 import fastapi，状态码映射
在 `console/errors.py`，仍然是 404）。

**判据 E 的分母就在这里算**（`audit` 那一列：自动放行、还没人核过的异体位），
所以它属于领域层，不属于 HTTP 层。
"""
from __future__ import annotations

from ..core.book import load_book
from ..core.spec import cell_key, page_key
from ..errors import NotFound
from ..eval.round_check import load_verdicts
from ..products.store import ProductStore
from ..variant_ledger import DEFAULT_EDITION, BookLedger


def group_view(book: str, pages: str = "dev_set", edition: str = "",
               limit_tiles: int = 400, store: ProductStore | None = None) -> dict:
    """组视图（variant_strategy.md §5.1）：按异体组把字位摊成「列 = 形、格 = 图块」。

    每组两类格：**已自动放行**的（char 在组内；抽审字形保真率用）与**义定形未定**的
    （落人审、`evidence.form.state == open`；首例确认用）。人裁过的格带 `human`。
    组按待审数、再按格数排。裁决走既有的 confirm 事件协议，这里只出数据。
    """
    led = BookLedger.load_or_empty(edition or DEFAULT_EDITION)
    if not len(led):
        raise NotFound("没有用字账——先跑 python scripts/build_book_variants.py")
    st = store or ProductStore()
    bk = load_book(book)
    truth = load_verdicts(book)
    tiles: dict[str, list[dict]] = {}
    for pg in bk.resolve_pages(pages):
        a = st.read(book, "admit_decide", page_key(pg), "admit_decide")
        if a is None:
            continue
        for cc in a.columns:
            if not cc.ok:
                continue
            for r in cc.chars:
                f = (r.evidence or {}).get("form") or {}
                # **裁过的就不再算待审**（用户 2026-09-05 实锤：「我之前标注过，点了提交
                # 待审与改动，为什么这次刷新还在」）。产物是上次跑管线时算的，裁决进了
                # 库、产物没重跑，`form.state` 还停在 open——但人确实已经答过了。
                # 事件是比产物更新的事实，以它为准；产物等下次重跑自然跟上。
                pending = (not r.admit) and f.get("state") == "open" \
                    and r.id not in truth
                human = truth.get(r.id)
                if r.admit and r.char and r.char in led.form_index:
                    canon = led.form_index[r.char]
                elif pending:
                    canon = led.canonical(f.get("semantic", ""))
                elif human and f.get("state") == "open":
                    # 裁过、产物还没重跑：按**人裁的字形**归组显示（否则这一格会
                    # 整个从视图里消失——比「还在待审」更让人摸不着头脑）
                    canon = led.form_index.get(human) or led.canonical(f.get("semantic", "") or human)
                else:
                    continue
                key = cell_key(pg, cc.col, r.slot) + (r.sub or "")
                tiles.setdefault(canon, []).append({
                    "id": r.id, "page": pg, "col": cc.col, "slot": r.slot, "sub": r.sub,
                    "patch": f"/api/cache/{book}/char_patch/{key}.png",
                    # 产物落后时用人裁的字形当 char，格子才落在对的那一列
                    "char": r.char or human, "reading": r.reading, "channel": r.channel,
                    "state": f.get("state") or ("lib_same" if r.admit else None),
                    # 裁过但产物没跟上 → 标 stale，前端提示「重跑管线后生效」
                    "stale": bool(human and not r.admit and f.get("state") == "open"),
                    # 判据 E 的分母：自动放行的**异体位**（reading≠char，或走了 variant_form
                    # 定形）。`audit` 标出「还没人核过的异体位」——那才是抽审该点的格；
                    # 「有/洧」「正/政」这种账本噪声组即便 100 格也一条都不贡献。
                    "variant": bool(r.admit and r.char
                                    and ((r.reading and r.reading != r.char)
                                         or f.get("state") in ("fixed_lib", "fixed_form"))),
                    "audit": bool(r.admit and r.char and r.id not in truth
                                  and ((r.reading and r.reading != r.char)
                                       or f.get("state") in ("fixed_lib", "fixed_form"))),
                    "pending": pending, "human": human,
                    "lib": f.get("lib"), "human_n": f.get("human"),
                })
    out = []
    for canon, ts in tiles.items():
        g = led.groups.get(canon)
        if not g:
            continue
        n_pending = sum(1 for t in ts if t["pending"])
        n_stale = sum(1 for t in ts if t.get("stale"))
        n_audit = sum(1 for t in ts if t.get("audit"))
        # 待审在前，其次「待抽审的异体位」——判据 E 只认这些格，人该先点它们
        ts.sort(key=lambda t: (not t["pending"], not t.get("audit"),
                               t["page"], t["col"], t["slot"]))
        refd = [m for m, fm in g["forms"].items() if fm["ref"] > 0 and m not in g.get("ref_minor", [])]
        out.append({
            "canonical": canon, "members": g["members"], "forms": g["forms"],
            "ref_policy": g["ref_policy"], "preferred": g.get("preferred"),
            "reading_default": refd[0] if len(refd) == 1 else canon,
            "n_tiles": len(ts), "n_pending": n_pending, "n_stale": n_stale,
            "n_audit": n_audit,
            "tiles": ts[:limit_tiles], "truncated": len(ts) > limit_tiles,
        })
    # 排序：待审 > 待抽审（判据 E 的分母）> 格数。此前只按格数排，结果排最前的是
    # 「有/洧」125 格、「正/政」60 格这类账本噪声组——它们一条都不贡献 E，而真正
    # 要抽的 卽/彚/㫖 被挤到后面。
    out.sort(key=lambda x: (-x["n_pending"], -x["n_audit"], -x["n_tiles"], x["canonical"]))
    return {"book": book, "pages": pages, "groups": out}
