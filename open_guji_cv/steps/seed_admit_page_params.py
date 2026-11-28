"""C1 进库准入（`seed_admit`）按页换参数：无参照页、参校本准确度分档（`trust_from_accuracy`）。

CV4 整理 P1a（2026-11-28）从 seed_admit.py **原样搬来，不改行为**。
"""

from __future__ import annotations

from .seed_admit_params import SeedAdmitParams



def _no_ref_page(book, p: "SeedAdmitParams", page: int) -> bool:
    """本页是不是无参照页：册配置 `reference_profile` 声明 `kind: none`，或在 `no_ref_pages`（`page_kinds.no_ref`）里。
    `solo_5b_scope: no_ref` 用。"""
    prof = getattr(book, "reference_profile", None)
    if prof is not None and prof.declared and prof.kind_of(page) == "none":
        return True
    from ..core.book import _expand_pages
    return bool(p.no_ref_pages) and page in set(_expand_pages(list(p.no_ref_pages)))


def no_ref_page_params(p: "SeedAdmitParams", page: int, book=None) -> "SeedAdmitParams":
    """无参照页（册配置 `reference_profile` 声明 `kind: none`，或 `no_ref_pages`／`page_kinds.no_ref`）上把 `no_ref_params`
    叠到本步参数上；别的页、或没配，原样返回同一个对象。两种写法同一口径（同 `_no_ref_page`，参校本 bug 修 CV0 11-27）。"""
    if not p.no_ref_params:
        return p
    if not _no_ref_page(book, p, page):
        return p
    bad = [k for k in p.no_ref_params if k not in type(p).model_fields or k.startswith("no_ref_")]
    if bad:
        raise ValueError(f"seed_admit.no_ref_params: 不认的参数 {bad}（须是 seed_admit 的参数名，且不能是 no_ref_*）")
    return type(p).model_validate({**{k: getattr(p, k) for k in type(p).model_fields}, **p.no_ref_params})


#: 准确度档 → 信任档（`trust_from_accuracy`）
_ACC_TRUST = {"very_high": "very_high", "high": "high"}


_TRUST_RANK = {"none": 0, "high": 1, "very_high": 2}


def ref_accuracy_summary(book) -> str:
    """本册参校本 accuracy/script 与段上压低的摘要（`ref_accuracy` 指纹用）。没标的项写空，全没标也给一串（开关开着就要进指纹）。"""
    refs = list(getattr(book, "references", None) or [])
    parts = [f"{r.get('accuracy') or ''}/{r.get('script') or ''}" for r in refs]
    prof = getattr(book, "reference_profile", None)
    segs = [f"{','.join(map(str, s.expr))}:{s.accuracy}" for s in (getattr(prof, "segments", ()) or ()) if s.accuracy]
    return "refs=" + ";".join(parts) + ("|segs=" + ";".join(segs) if segs else "")


def accuracy_page_params(p: "SeedAdmitParams", page: int, book=None) -> "SeedAdmitParams":
    """`trust_from_accuracy` 开时按本页参照的准确度档推信任档（只往上推）、按 `script` 关照录异体；关或无变化时原样返回同一个对象。"""
    if not p.trust_from_accuracy or book is None:
        return p
    from ..core.ref_profile import UNDECLARED
    refs = list(getattr(book, "references", None) or [])
    prof = getattr(book, "reference_profile", None) or UNDECLARED
    if prof.kind_of(page) == "none" or _no_ref_page(book, p, page):
        return p
    acc = prof.accuracy_of(page, refs)
    upd: dict = {}
    trust = _ACC_TRUST.get(acc)
    if trust and _TRUST_RANK[trust] > _TRUST_RANK[p.reference_trust]:
        upd["reference_trust"] = trust
    if acc == "mid" and not p.ref_lib_coord and p.reference_trust == "none":
        upd["ref_lib_coord"] = True
    if prof.script_of(page, refs) in ("trad", "simp"):
        upd["ref_variants_off"] = True
        if p.edge_pair_to == "ref":
            upd["edge_pair_to"] = "freq"
    if not upd:
        return p
    return type(p).model_validate({**{k: getattr(p, k) for k in type(p).model_fields}, **upd})
