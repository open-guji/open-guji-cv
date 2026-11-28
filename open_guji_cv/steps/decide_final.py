"""收尾步 `char_decide`（旧名 `seed_admit`）产物的兼容读口（CV4 P3a-1，2026-11-28）。

- `read_final(ctx, page)` → `PageAdmit | None`：先找 `char_decide/`，再找 `seed_admit/`；两个目录并存以新的为准；
- `read_final_store(store, book, key)`：同上，直接给 `ProductStore`、册名与页键（pNNNN）；
- `final_page_dict(doc)`：整份页 JSON（读盘得到的 dict）→ 收尾页的原始 dict，页顶层键新旧都认；
- `ADMIT_STEPS`、`LEGACY_ADMIT_STEP` 等常量见 `core/decide_names.py`，这里再导出一份。

页内版式不变：`columns[].chars[]`、`ask`、`doubts`、`evidence.vis_ctx` 的位置与含义同以前。
本模块**不在** `seed_admit` 的 `code_deps` 里（读口改动不让各书产物过期）；Step 本身仍写 `seed_admit`。
"""

from __future__ import annotations

from ..core.decide_names import (  # noqa: F401  再导出
    ADMIT_STEP_ACTIVE, ADMIT_STEPS, LEGACY_ADMIT_STEP, NEW_ADMIT_STEP, final_dir, final_dirs, final_page_dict,
)
from ..core.spec import page_key
from ..products.final_read import read_final_store  # noqa: F401  再导出
from ..products.kinds.recog import PageAdmit


def read_final(ctx, page: int) -> PageAdmit | None:
    """`ctx`（`RunContext`）这册第 `page` 页的收尾产物（新目录优先），没有 → None。"""
    return read_final_store(ctx.store, ctx.book.id, page_key(page))


def has_final(ctx, page: int) -> bool:
    return any(ctx.store.exists(ctx.book.id, s, page_key(page)) for s in ADMIT_STEPS)
