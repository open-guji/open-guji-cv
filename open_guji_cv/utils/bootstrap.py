# -*- coding: utf-8 -*-
"""缺产物时从原图现跑 Step1-3 补齐（公共件，供 `seg_harness.py` 与 `eval run --from-raw` 共用）。

云端会话 clone 之后没有 products/ 与 cache/，但原图（data_full/）、金标、册配置都在
git 里，所以现跑一遍就能开工——dev_set 12 页约 30 秒，比想办法把产物传过去省事得多。

从 `scripts/seg_harness.py` 原样搬来，**行为逐字不变**：只补缺的页，已有产物一律不动，
也不传 force——那会让本地已有的产物白重跑一遍，还会因为 code_rev 变化把下游全冲掉。
"""
from __future__ import annotations

from open_guji_cv.core.step import page_key
from open_guji_cv.products import kinds as _k  # noqa: F401  (side effect: 注册产物种类)
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore

# Step1 边框 → Step2 列图 → Step3 现役 cells——本项目所有「需要产物」的台子与评测器
# 都以这三步的产物齐不齐为准。
BOOTSTRAP_STEPS = ("border_detect", "column_warp", "column_gate", "row_segment")


def has_products(bk_id: str, page: int, *, store: ProductStore) -> bool:
    """这一页的 Step3 产物在不在——bootstrap 与 eval 的「缺不缺」判据统一走这一个函数。"""
    return store.read(bk_id, "row_segment", page_key(page), "cells") is not None


def ensure_products(bk, pages: list[int], *, store: ProductStore,
                     cache: ImageCache, quiet: bool = False) -> None:
    """缺产物时从原图现跑 Step1-3 补齐。

    只补缺的页，已有产物一律不动，也不传 force——那会让本地已有的产物白重跑一遍，
    还会因为 code_rev 变化把下游全冲掉。
    """
    from open_guji_cv.core.engine import Engine
    from open_guji_cv.core.pipeline import load_pipeline

    missing = [pg for pg in pages if not has_products(bk.id, pg, store=store)]
    if not missing:
        return
    if not quiet:
        print(f"[from-raw] {len(missing)} 页缺产物，从原图补跑 "
              f"{' → '.join(BOOTSTRAP_STEPS)}：{missing}", flush=True)
    log = (lambda s: None) if quiet else (lambda s: print(f"  {s}", flush=True))
    eng = Engine(bk, load_pipeline("keben_body_v2"), store=store, cache=cache, log=log)
    eng.run(steps=list(BOOTSTRAP_STEPS), pages=missing)
    still = [pg for pg in missing if not has_products(bk.id, pg, store=store)]
    if still and not quiet:
        print(f"[from-raw] ⚠️ {len(still)} 页仍无产物（多半是整页 DP 无解，"
              f"例如职名页）：{still}", flush=True)
