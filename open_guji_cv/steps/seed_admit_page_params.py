"""C1 进库准入（`seed_admit`）按册／按页换参数：无参照页、参校本准确度分档（四维推信任字段，2026-11-28 起恒开）。

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


#: 由参校本四维推出的 seed_admit 字段（册配置里写这几个不采用，2026-11-28 Sheldon 定）
DERIVED_FIELDS = ("reference_trust", "ref_lib_coord", "follow_ref_variants", "ref_topk_follow")


def derive_trust(accuracy: str, script: str = "", form: str = "", by_carving: bool = False) -> dict:
    """参校本准确度档（＋用字、形态）→ seed_admit 信任字段。门槛见 `doc/design/参校本四维与准确度分档.md`。

    - very_high：`reference_trust: very_high`＋`ref_topk_follow`（库前 5 名有参校字也按参校本放）；
    - high：`reference_trust: high`（含 ref_lib_coord 那一路）；
    - mid：逐列参校本（form column）开 `ref_lib_coord`；不分行的用不上坐标对位，不开；
    - low／未标：都不开；
    - 照录参校本异体（`follow_ref_variants`）：very_high/high、`script: faithful`、且本书不按刻形录字（`edge_pair_to` 不是 lib）。"""
    out = {"reference_trust": "none", "ref_lib_coord": False, "follow_ref_variants": False, "ref_topk_follow": False}
    if accuracy == "very_high":
        out.update(reference_trust="very_high", ref_topk_follow=True)
    elif accuracy == "high":
        out["reference_trust"] = "high"
    elif accuracy == "mid" and form == "column":
        out["ref_lib_coord"] = True
    if accuracy in ("very_high", "high") and script == "faithful" and not by_carving:
        out["follow_ref_variants"] = True
    return out


def _page_ref(book, page: int | None):
    """（这页／整册缺省）用哪份参校本、准确度档。page=None＝整册缺省（profile default，未声明＝references[0]）。"""
    from ..core.ref_profile import UNDECLARED, ref_accuracy
    refs = list(getattr(book, "references", None) or [])
    prof = getattr(book, "reference_profile", None) or UNDECLARED
    if page is None:
        i = prof.default_ref if prof.declared else (0 if refs else None)
        r = refs[i] if i is not None and i < len(refs) else None
        return r, (ref_accuracy(r) if r is not None else "")
    r = prof.ref_of(page, refs)
    return r, (prof.accuracy_of(page, refs) if r is not None else "")


def derived_for(p: "SeedAdmitParams", book, page: int | None = None) -> dict | None:
    """本册（或本页）由参校本推出的字段值；没有参照（整页 none、没配 references）→ None（不动）。"""
    r, acc = _page_ref(book, page)
    if r is None:
        return None
    upd = derive_trust(acc, str(r.get("script") or ""), str(r.get("form") or ""), by_carving=p.edge_pair_to == "lib")
    if r.get("script") in ("trad", "simp") and p.edge_pair_to == "ref":
        upd["edge_pair_to"] = "freq"
    return upd


def ref_accuracy_summary(book) -> str:
    """段上压低准确度的摘要（`ref_accuracy` 指纹用）：没有压低段＝空。"""
    prof = getattr(book, "reference_profile", None)
    segs = [f"{','.join(map(str, s.expr))}:{s.accuracy}" for s in (getattr(prof, "segments", ()) or ()) if s.accuracy]
    return ";".join(segs)


def book_trust_params(p: "SeedAdmitParams", book) -> "SeedAdmitParams":
    """整册：按缺省参照推信任字段，覆盖册里写的旧开关（写了不同的值提示一次），段上压低进 `ref_accuracy`。"""
    upd = derived_for(p, book) or {k: type(p).model_fields[k].default for k in DERIVED_FIELDS}
    dflt = {k: type(p).model_fields[k].default for k in DERIVED_FIELDS}
    stale = [f"{k}={getattr(p, k)!r}" for k in DERIVED_FIELDS if getattr(p, k) not in (dflt[k], upd[k])]
    if stale:
        import warnings
        warnings.warn(f"册 {getattr(book, 'id', '?')}：seed_admit {', '.join(stale)} 不再采用，改由 references[].accuracy 推出"
                      f"（{', '.join(f'{k}={upd[k]!r}' for k in DERIVED_FIELDS)}）；请删掉旧键", FutureWarning, stacklevel=2)
    summ = ref_accuracy_summary(book)
    if summ:
        upd["ref_accuracy"] = summ
    if all(getattr(p, k) == v for k, v in upd.items()):
        return p
    return type(p).model_validate({**{k: getattr(p, k) for k in type(p).model_fields}, **upd})


def accuracy_page_params(p: "SeedAdmitParams", page: int, book=None) -> "SeedAdmitParams":
    """本页参照与整册缺省不同（段指了别的参校本、段上压低准确度）时按本页重推信任字段；一样或无参照页原样返回同一个对象。"""
    if book is None or _no_ref_page(book, p, page):
        return p
    upd = derived_for(p, book, page)
    if upd is None or all(getattr(p, k) == v for k, v in upd.items()):
        return p
    return type(p).model_validate({**{k: getattr(p, k) for k in type(p).model_fields}, **upd})
