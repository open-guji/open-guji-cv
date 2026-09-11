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
    python -m open_guji_cv.gates.query vol01 --gate row_segment_gate

2026-09-11 补闸3：新增 `--gate` 选项，同一条命令按闸 id 切换查哪道闸的
`*_manifest` 产物——闸2（`column_gate`）与闸3（`row_segment_gate`）的产物
kind id 与 store step id 不同名（`gate_manifest` vs `row_segment_gate_manifest`），
用 `GATES` 表登记对应关系，不新开一条命令。
"""

from __future__ import annotations

import argparse
import json

from ..core.book import load_book
from ..core.spec import page_key
from ..products.store import ProductStore

# 闸 id → (store 读取用的 step id, 产物 kind id)。两道闸各自的 Step id 与
# 产物 kind id 恰好同名（`column_gate`/`gate_manifest` 是历史命名，新闸
# `row_segment_gate` 干脆让 step id 与产物名共用前缀，不再引入新的映射坑）。
GATES: dict[str, tuple[str, str]] = {
    "column_gate": ("column_gate", "gate_manifest"),
    "row_segment_gate": ("row_segment_gate", "row_segment_gate_manifest"),
}


def blocked_units(book_id: str, pages: list[int] | None = None,
                   store: ProductStore | None = None,
                   gate: str = "column_gate") -> list[dict]:
    """逐页查某道闸的 manifest，收拢成一份清单：
    页级 admitted=False、列级 admitted=False、或者压根没有闸产物（missing）。
    `gate` 是闸 id（见 `GATES`），默认闸2（`column_gate`），向后兼容旧调用方。"""
    store = store or ProductStore()
    book = load_book(book_id)
    pages = pages if pages is not None else book.all_pages()
    step_id, kind_id = GATES[gate]
    out: list[dict] = []
    for pg in pages:
        g = store.read(book_id, step_id, page_key(pg), kind_id)
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
    ap.add_argument("--gate", default="column_gate", choices=sorted(GATES),
                    help="查哪道闸，默认 column_gate（闸2）")
    args = ap.parse_args()
    book = load_book(args.book)
    pages = book.resolve_pages(args.pages) if args.pages else None
    rows = blocked_units(args.book, pages, gate=args.gate)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"共 {len(rows)} 条：" + "；".join(f"{k} {v}" for k, v in counts.items()))


if __name__ == "__main__":
    _main()
