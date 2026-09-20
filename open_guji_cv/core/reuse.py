# -*- coding: utf-8 -*-
"""格级复用：本步没变、只是上游变了时，几何没动的格直接搬旧记录，不重算。

设计见 overview 仓 `项目进展/图片初步数字化/进度/总览/12-重跑粒度-格级复用设计.md`。
动机：bxgb 一轮全量 45 min 里 72% 花在 Step5-a/5-b 逐格的 CNN 匹配与 OCR 上，而
Step1 版框动 1px 就让 54 页 Step4–8 全过期——绝大多数格的图块其实没变。

## 只在 `run_page` 内部发生，指纹层不动

引擎眼里这一页就是重跑过了：产物文件是新写的（复用的记录 + 重算的记录），manifest 记
新指纹。不引入"容差指纹"这种模糊概念，指纹仍是精确的。

## 三道闸，缺一不复用（都过不了就返回空表，Step 照常全算）

1. **本步自己没变**：manifest 上一条 `self_hash`（版本+参数+代码+册配置，不含上游）
   等于现在算出来的。换 checkpoint / 改阈值 / 改代码 → 全量，与 cv-pipeline-ops §2.2 一致。
   老条目没有 `self_hash` → 不复用（第一轮跑完就有了）。
2. **拿得到"当时那份上游"**：manifest 上一条记的 `upstream[kind]` sha，要么等于
   `_prev/` 里那份（`ProductStore.write` 覆盖前留的），要么等于现在盘上这份（上游根本
   没重写）。都不等 → 不复用。
3. **逐格几何没变**：`bbox_page`（原图规范空间，与 Step2 列窗怎么漂无关）四角各 ≤ `tol` px，
   且 cell_type / step3_kind / flags / patch_key 相同。`bbox_page` 为 None（没有映射）→ 这格不复用。

复用的记录**逐字节等于旧记录**，产物里看不出它是搬来的（用户 2026-09-20 待定项之一，
先按"不带标记"做，要审计看引擎日志的「复用 n/m 格」）。
"""
from __future__ import annotations

from typing import Any

from .spec import page_key


def _geom(r) -> tuple | None:
    bb = getattr(r, "bbox_page", None)
    if not bb:
        return None
    return (r.cell_type, getattr(r, "step3_kind", None), tuple(sorted(r.flags or [])),
            r.patch_key, tuple(float(v) for v in bb))


def _same(g0: tuple, g1: tuple, tol: float) -> bool:
    if g0[:4] != g1[:4]:
        return False
    return all(abs(a - b) <= tol for a, b in zip(g0[4], g1[4]))


def cell_reuse(ctx, step, page: int, own_kind: str, upstream_kind: str = "char_index",
               tol: float = 1.0) -> dict[str, Any]:
    """→ `{id: 旧记录}`，可以原样放进本页产物的格。拿不到就是空表。

    `own_kind`：本步产物种类（记录带 `id`，按列装在 `.columns[i].chars`）。
    `upstream_kind`：逐格几何来自哪个上游（Step5 三步都是 `char_index`）。
    """
    if not getattr(ctx, "reuse_enabled", True):
        return {}
    from .engine import self_hash
    book, sid, key = ctx.book.id, step.spec.id, page_key(page)
    entry = ctx.store.manifest(book, sid).get(key)
    if (entry is None or entry.status != "ok" or entry.invalidated or not entry.self_hash
            or entry.self_hash != self_hash(step, ctx.book, ctx.params_for(step))):
        return {}
    # 盘上这份旧产物得是 manifest 说的那份（别人手改过就不认）
    if entry.sha256 and ctx.store.sha(book, sid, key) != entry.sha256:
        return {}
    up_sid = ctx.producer(upstream_kind).spec.id
    want = entry.upstream.get(upstream_kind)
    if not want:
        return {}
    if ctx.store.prev_sha(book, up_sid, key) == want:
        old_up = ctx.store.read_prev(book, up_sid, key, upstream_kind)
    elif ctx.store.sha(book, up_sid, key) == want:
        old_up = ctx.store.read(book, up_sid, key, upstream_kind)
    else:
        return {}
    old_own = ctx.store.read(book, sid, key, own_kind)
    if old_up is None or old_own is None:
        return {}
    new_up = ctx.product(upstream_kind, page)
    old_geom = {r.id: _geom(r) for cc in old_up.columns if cc.ok for r in cc.chars}
    own_recs = {r.id: r for cc in old_own.columns if cc.ok for r in (cc.chars or [])}
    out: dict[str, Any] = {}
    for cc in new_up.columns:
        if not cc.ok:
            continue
        for r in cc.chars:
            g0, g1 = old_geom.get(r.id), _geom(r)
            if g0 and g1 and r.id in own_recs and _same(g0, g1, tol):
                out[r.id] = own_recs[r.id]
    return out


def log_reuse(ctx, step, page: int, n_reused: int, n_total: int) -> None:
    if n_reused:
        ctx.log(f"{step.spec.id} p{page}: 复用 {n_reused}/{n_total} 格（几何未变，见 core/reuse.py）")
