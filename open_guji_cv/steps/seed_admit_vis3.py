"""收尾影子读口：第三步 3e `glyph_vis`（vis3，只看图）与第四步现行 `vis_llm` 看图结论逐格对比（CV4 2026-11-28，P1）。

**只记录、不改放行**：只往格 `evidence.vis3_shadow` 写一条对比，不动 char／admit／channel／doubts。
开关 `vis3_shadow`（缺省 False，关时本模块不被调用、不读 `glyph_analyzer`，产物逐字节同）。

现行 vis_llm 的结论取自（先到先用）：
- `evidence.group.solvers` 里 `solver=="vis"` 的项：`why` 为 `<conf>:<字>`（字＝组员或「其他」）或 `ref_dissent:<字>`（高把握但被整理本拦下）；带 `ask` ＝没缓存、待问；
- `evidence.vis_ruling`（通道 vis_ruling 放行的格，无组入口的看图判裁定）：`char`／`conf`。

vis3 取同页 `glyph_analyzer` 的 `FinalRec.vis`：`status` 是 hit／asked 才算有答案，`other=True` ＝答「其他」。

`cmp`：same（同字，或都答其他）｜diff（都有答案但不同）｜cur_only（vis3 没答：没触发／pending／error／skipped）｜vis3_only（现行没问）。
"""
from __future__ import annotations

_CONFS = ("high", "mid", "low")


def cur_vis(ev: dict | None) -> dict | None:
    """格 evidence → 现行 vis_llm 结论 {src, char, conf, ask}｜None（没走看图）。char 为 None 且 ask 假＝答其他或没答字。"""
    ev = ev or {}
    for t in ((ev.get("group") or {}).get("solvers") or []):
        if t.get("solver") != "vis":
            continue
        if t.get("ask"):
            return {"src": "L4", "char": None, "conf": None, "ask": True}
        why = str(t.get("why") or "")
        head, _, ch = why.partition(":")
        if head in _CONFS:
            conf = head
        elif head == "ref_dissent":
            conf = t.get("vis_conf") or "high"
        else:
            continue
        return {"src": "L4", "char": ch or None, "conf": conf, "ask": False}
    vr = ev.get("vis_ruling")
    if isinstance(vr, dict) and vr.get("char"):
        return {"src": "ruling", "char": vr["char"], "conf": vr.get("conf"), "ask": False}
    return None


def vis3_of(vrec: dict | None) -> dict | None:
    """FinalRec.vis → {status, char, other, conf, legacy}｜None（该格没触发）。"""
    if not vrec:
        return None
    return {"status": vrec.get("status") or "", "char": vrec.get("char"), "other": bool(vrec.get("other")),
            "conf": vrec.get("conf"), "legacy": bool(vrec.get("legacy")), "trigger": vrec.get("trigger")}


def compare(cur: dict | None, v3: dict | None) -> str | None:
    """→ same／diff／cur_only／vis3_only｜None（两边都没有）。"""
    v3_ans = bool(v3) and v3["status"] in ("hit", "asked") and (v3["char"] or v3["other"])
    cur_ans = bool(cur) and not cur["ask"]
    if cur is None and not v3_ans:
        return None
    if cur is None:
        return "vis3_only"
    if not v3_ans:
        return "cur_only"
    if not cur_ans:
        return "vis3_only"
    a, b = cur["char"], (None if v3["other"] else v3["char"])
    return "same" if a == b else "diff"


def vis3_shadow_pass(ctx_final, out: list) -> dict[str, int]:
    """逐格写 `evidence.vis3_shadow`，→ 各 cmp 计数。`ctx_final`＝同页 glyph_analyzer 的 PageFinal（None＝读不到，全按 vis3 缺记）。"""
    fin = ctx_final.by_id() if ctx_final is not None else {}
    cnt: dict[str, int] = {}
    for col in out:
        for r in col.chars or []:
            cur = cur_vis(r.evidence)
            fr = fin.get(r.id)
            v3 = vis3_of(getattr(fr, "vis", None) if fr is not None else None)
            c = compare(cur, v3)
            if c is None:
                continue
            cnt[c] = cnt.get(c, 0) + 1
            r.evidence = {**(r.evidence or {}), "vis3_shadow": {"cmp": c, "cur": cur, "vis3": v3}}
    return cnt
