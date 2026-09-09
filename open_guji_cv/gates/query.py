"""查询一册书里被闸拦下的单位——不再是「没有任何东西在跟踪」。

`gate_manifest` 本身早就记着每一页/每一列的拒因（`GateManifest.reject` /
`GateColumn.reject`），只是散在 `products/<book>/column_gate/p*.json` 里，
没人把它们收成一份清单。这里只做收拢，不算新判据。

**局限**：keben_body_v2 管线的 `selector.page_type: [body]` 目前是外部选页
（跑批时人/脚本按页号挑，管线自己分不出 body/roster/toc——见仓库
`.claude/CLAUDE.md`「当前策略」一节），所以从来没跑过闸的页（比如 vol01
p90–132 那 41 页职名页）在 `gate_manifest` 里根本没有记录，`page_type` 本身
也不在这个仓库的产物里。这份清单只能把「有没有闸产物」这件事本身摆出来
（`missing`），做不到自动分辨「没产物是因为是职名页」还是「因为还没跑」——
那需要 `open-guji-dataset` 的 page-type 金标（只读），本轮没接，留给下一道。

用法：
    python -m open_guji_cv.gates.query vol01
    python -m open_guji_cv.gates.query vol01 --pages 90-132
"""

from __future__ import annotations

import argparse
import json

from ..core.book import load_book
from ..core.spec import page_key
from ..products.store import ProductStore


def blocked_units(book_id: str, pages: list[int] | None = None,
                   store: ProductStore | None = None) -> list[dict]:
    """逐页查 `gate_manifest`，收拢成一份清单：
    页级 admitted=False、列级 admitted=False、或者压根没有闸产物（missing）。"""
    store = store or ProductStore()
    book = load_book(book_id)
    pages = pages if pages is not None else book.all_pages()
    out: list[dict] = []
    for pg in pages:
        g = store.read(book_id, "column_gate", page_key(pg), "gate_manifest")
        if g is None:
            out.append({"page": pg, "status": "missing",
                        "reason": "没有闸产物——不在这轮跑过的页里（可能是非正文页，"
                                  "也可能是还没跑），需要 page-type 金标才能分清"})
            continue
        if not g.admitted:
            out.append({"page": pg, "status": "page_blocked", "reason": g.reject})
            continue
        for c in g.columns:
            if not c.admitted:
                out.append({"page": pg, "column": c.col, "status": "column_blocked",
                            "reason": c.reject})
    return out


def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("book")
    ap.add_argument("--pages", default=None, help="'all'（默认）| '90-132' | '3,4,5'")
    args = ap.parse_args()
    book = load_book(args.book)
    pages = book.resolve_pages(args.pages) if args.pages else None
    rows = blocked_units(args.book, pages)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"共 {len(rows)} 条：" + "；".join(f"{k} {v}" for k, v in counts.items()))


if __name__ == "__main__":
    _main()
