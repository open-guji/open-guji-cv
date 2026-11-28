"""收尾步（`char_decide`，旧名 `seed_admit`）产物的读口实现（CV4 P3a-1，2026-11-28）。

放在 products（L1）是为了 report、feedback、steps 都能用。对外入口见 `steps/decide_final.py`
（`read_final(ctx, page)`、`final_page_dict`），这里只有按 `ProductStore` 读的一个函数。不在任何 Step 的 `code_deps` 里。
"""

from __future__ import annotations

from ..core.decide_names import ADMIT_STEPS, final_page_dict
from .kinds.recog import PageAdmit


def read_final_store(store, book: str, key: str) -> PageAdmit | None:
    """`store`（`ProductStore`）里这册这页（`key`＝pNNNN）的收尾产物。目录 `char_decide/`、`seed_admit/` 和页顶层键
    新旧名都认，新的优先（两个目录并存以 `char_decide/` 为准）；都没有 → None。"""
    for step in ADMIT_STEPS:                      # 新名在前
        raw = store.read_raw(book, step, key)
        if raw is None:
            continue
        try:
            body = final_page_dict(raw)
        except KeyError:
            continue
        return PageAdmit.model_validate(body)
    return None
