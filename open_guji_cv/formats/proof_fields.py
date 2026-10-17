"""审阅卡 → guji-proof 0.2 新增字段（GUJI-557）。

只**加**字段，不改 0.1 已有的 `id`／`a`／`method`／`review`／`channel`／`cand`；cv 引擎不动。
字段口径见 ai-team `team/CV/guji-proof-0.2-字段表-GUJI-557.md`。输入是 `review.cards.cards()` 出的卡
（建议传 `cls="*"`，卡上才有 `cls`／`cls_sub`），输出是纯 dict，由整理侧导出脚本并进册级
`NNN.pending.json` 的 `cells[]` 或章 `proof.json` 的 `cells[]`。

- `pending_fields(card)`：册级 pending 用的全部字段（`img`／`ex` 由雪碧图脚本另加，这里不出）。
- `slim_fields(card)`：章 `proof.json` 瘦身形态，只带 `cls`／`why`／`conf`。
"""
from __future__ import annotations

from ..review.cards import doubt_codes

PROOF_FIELDS_SCHEMA = "guji-proof/0.2"
LIB_TOP_N = 5
NO_DOUBT = ["none"]          # 无疑问码但仍待审时的占位


def why_codes(card: dict) -> list[str]:
    """待审原因机器码；`doubts` 里的中文说明不要，没有码写 `["none"]`。"""
    return doubt_codes(card.get("doubts")) or list(NO_DOUBT)


def _num(x, nd: int) -> float | None:
    return None if x is None else round(float(x), nd)


def _lib_top(db: dict) -> list[dict]:
    out = []
    for cand in (db.get("candidates") or [])[:LIB_TOP_N]:
        c, s = cand[0], cand[1]
        out.append({"c": c, "s": _num(s, 4)})
    return out


def _stale(sv: dict) -> dict | None:
    c = ((sv.get("verdict") or {}).get("shape")) or ""
    if not c:                      # 旧裁决是「非字／没有」时没有预勾字
        return None
    return {"c": c, "ts": sv.get("ts"), "state": "withdrawn" if sv.get("withdrawn") else (sv.get("status") or "stale")}


def pending_fields(card: dict) -> dict:
    """卡 → 0.2 新增字段（键序固定；值为空的键不出）。不含 `img`／`ex`。"""
    out: dict = {"why": why_codes(card)}
    if card.get("cls") is not None:
        out["cls"] = card["cls"]
        if card.get("cls_sub") is not None:
            out["cls_sub"] = card["cls_sub"]
    db = card.get("db")
    if db:
        out["lib_top"] = _lib_top(db)
        out["lib"] = {"verdict": db.get("verdict"), "cov": _num(db.get("cov"), 4), "wmax": _num(db.get("wmax"), 1)}
        out["conf"] = _num(db.get("cov"), 4)
    ctx = card.get("ctx")
    if ctx and ctx.get("margin") is not None:
        # 字表 ctx.c 是字符串：上下文没给出字（先验、领先幅度不足）时写 ""，不写 null
        out["ctx"] = {"c": ctx.get("char") or "", "margin": _num(ctx["margin"], 4), "src": ctx.get("source") or ""}
        out["margin"] = _num(ctx["margin"], 4)
    ref = card.get("ref")
    if ref and ref.get("char"):
        out["ref"] = {"c": ref["char"], "op": ref.get("op")}
    ocr = [{"c": t[0], "src": "ocr"} for t in (card.get("ocr") or []) if t and t[0]]
    if ocr:
        out["ocr"] = ocr
    sv = card.get("stale_verdict")
    if sv:
        st = _stale(sv)
        if st:
            out["stale"] = st
    occ = card.get("occluded")
    if occ:
        out["occ"] = {"c": occ.get("char") or "", "ref_blank": bool(occ.get("ref_blank"))}
    return out


def slim_fields(card: dict) -> dict:
    """章 `proof.json` 瘦身形态：只加 `cls`／`why`／`conf`。"""
    full = pending_fields(card)
    return {k: full[k] for k in ("cls", "why", "conf") if k in full}
