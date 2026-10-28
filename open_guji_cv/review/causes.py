"""待审格的主成因码（M9 D6，GUJI-668）：每个没放行的格打一个码，按码派给对口的人修。

码表沿用 `doc/research/人审率分析-vol04-09/分析报告.md` 的 A–I（A 再按坐标对位给的理由细分），
派单表见 `doc/design/M9-平台粗校-调研与总设计.md` D6。和控制台的 `review.cards.card_class` 不是一回事：
那个按「人怎么审」分标签页（己已巳、形近……），这个按「为什么机器没放、该谁去修」分；一格两套都有。

只读两步产物（seed_admit 的 doubts、align_ref 的对位与坐标对位），纯函数，不碰事件、不写任何东西。
"""
from __future__ import annotations

import re

#: 码 → (中文名, 交给谁)。判定优先级见 `cause_of`（D → C → A2 → 整理本这位没字的 A6/A1/A5/A3/A4/F/A9 → B → F → E → G → H → I）。
CAUSES: dict[str, tuple[str, str]] = {
    "D": ("印章／污损遮挡", "不修，交 M10"),
    "C": ("形近字组（己已巳、日曰等）", "M7"),
    "B": ("码位异体", "M7"),
    "A1": ("坐标对位说这一位是空格（多半假格）", "切分"),
    "A2": ("整理本写〓（没码位的生僻字）", "人认字"),
    "A3": ("列格数与整理本字数对不上，整列没对位", "切分"),
    "A4": ("与现役对位冲突，整列退回", "切分"),
    "A5": ("整页锚不上整理本", "切分"),
    "A6": ("字形像框线／墨点（乱码护栏拦下）", "切分"),
    "A9": ("整理本这一位没字（别的原因）", "切分"),
    "F": ("字形库里没有这个字", "字形库"),
    "E": ("与整理本冲突", "语料／整理本"),
    "G": ("对齐改字层（整理本是 replace 段）", "语料／整理本"),
    "H": ("库首选＝整理本，仍被拦", "字形库"),
    "I": ("证据不足（库 unsure、上下文 margin 不够）", "字形库"),
}

_GROUP_CODES = {"near_form", "solo_confusable", "ji_yi_si_review", "group_flow_disagree", "group_flow_abstain"}
_VARIANT_CODES = {"ref_lib_variant", "variant_indirect", "replace_form", "channel_off"}
_CONFLICT_CODES = {"context_vs_ref", "iron_vs_ref", "iron_vs_coord", "signal_conflict"}
_GARBLE_CODES = {"ctx_garble_shape", "context_single_stroke", "nonchar", "ctx_guard_flag"}


def doubt_codes(doubts) -> set[str]:
    """seed_admit 的 doubts 是「码」或「中文说明(数)」混写：取码，中文说明映射成短码。"""
    out = set()
    for d in doubts or []:
        if not isinstance(d, str):
            continue
        if d.startswith("库里没有"):
            out.add("lib_miss")
        elif d.startswith("库 unsure"):
            out.add("lib_unsure")
        elif d.startswith("库 same"):
            out.add("lib_same_blocked")
        else:
            out.add(re.split(r"[(（:：]", d, maxsplit=1)[0].strip())
    return out


def _fallback_code(reason: str) -> str:
    if reason.startswith("与现役对位冲突"):
        return "A4"
    if "锚" in reason:
        return "A5"
    return "A3"


def cause_of(char: dict, aligned: dict | None, coord: dict | None, col_fallback: str | None,
             anchored: bool = True) -> tuple[str, str]:
    """一格的 (主成因码, 细节)。

    `char` = seed_admit 的一格（doubts、char、evidence）；`aligned` = align_ref.chars 里这一格（没有＝整理本这位没字）；
    `coord` = align_ref.coord 里这一格（坐标对位给的字，`ref_char` 为空＝说这是空位）；
    `col_fallback` = 本列坐标对位放弃的理由（align_ref.coord_fallback）；`anchored` = 本页锚上了整理本没有。
    """
    from ..utils.ji_yi_si import FAMILY
    codes = doubt_codes(char.get("doubts"))
    ev = char.get("evidence") or {}
    mine = char.get("char") or ""
    ref = (aligned or {}).get("align_char") or (coord or {}).get("ref_char") or ""
    if "occluded" in codes or ev.get("occluded"):
        return "D", ""
    if codes & _GROUP_CODES or any(c and c in FAMILY for c in (mine, ref)):
        return "C", ",".join(sorted(codes & _GROUP_CODES)) or "己已巳"
    if ref == "〓":
        return "A2", ""
    if not ref:
        if codes & _GARBLE_CODES:
            return "A6", ",".join(sorted(codes & _GARBLE_CODES))
        if coord is not None:
            return "A1", ""
        if not anchored:
            return "A5", ""
        if col_fallback:
            return _fallback_code(col_fallback), col_fallback
        return ("F", "") if "lib_miss" in codes else ("A9", "")
    if codes & _VARIANT_CODES or (mine and mine != ref and _variants(mine, ref)):
        return "B", f"{mine}/{ref}"
    if "lib_miss" in codes:
        return "F", ref
    if codes & _CONFLICT_CODES:
        return "E", f"{mine}/{ref}"
    if (aligned or {}).get("align_op") == "replace" or "replace_align" in codes:
        return "G", f"{mine}/{ref}"
    if mine == ref:
        return "H", ref
    return "I", f"{mine}/{ref}"


def _variants(a: str, b: str) -> bool:
    try:
        from ..variants import are_variants
        return are_variants(a, b)
    except Exception:  # noqa: BLE001 —— 异体表读不到就不判 B，落到后面的码
        return False


def page_causes(seed: dict, align: dict | None) -> dict[str, tuple[str, str]]:
    """一页：没放行、不在排除名单的格 → (码, 细节)。`seed`/`align` 是产物里 `seed_admit`／`align_ref` 那一层。"""
    align = align or {}
    by_id = {c["id"]: c for c in align.get("chars", [])}
    by_coord = {c["id"]: c for c in align.get("coord", [])}
    fb = {int(k): v for k, v in (align.get("coord_fallback") or {}).items()}
    anchored = bool(align.get("anchored", True))
    out: dict[str, tuple[str, str]] = {}
    for col in seed.get("columns", []):
        for ch in col.get("chars", []):
            if ch.get("admit") or "excluded" in (ch.get("doubts") or []):
                continue
            cid = ch["id"]
            colno = int(cid.split(":")[2])
            out[cid] = cause_of(ch, by_id.get(cid), by_coord.get(cid), fb.get(colno), anchored)
    return out


def page_facts(seed: dict, align: dict | None) -> dict[str, dict]:
    """一页没放行的格 → 分类要用、待审单里没有的事实：字组 id（`grp`）、整理本字（`refc`）。给 guji-manager 的 `taxonomy` 用。"""
    align = align or {}
    by_id = {c["id"]: c for c in align.get("chars", [])}
    by_coord = {c["id"]: c for c in align.get("coord", [])}
    out: dict[str, dict] = {}
    for col in seed.get("columns", []):
        for ch in col.get("chars", []):
            if ch.get("admit") or "excluded" in (ch.get("doubts") or []):
                continue
            cid = ch["id"]
            f = {}
            if (g := ((ch.get("evidence") or {}).get("group") or {}).get("id")):
                f["grp"] = g
            if (r := (by_id.get(cid) or {}).get("align_char") or (by_coord.get(cid) or {}).get("ref_char")):
                f["refc"] = r
            out[cid] = f
    return out


def book_causes(products_dir, book: str) -> dict[str, dict]:
    """全册：`{格号（不带册前缀）: {cause, detail}}`。读 `<产物根>/<册>/seed_admit|align_ref/p*.json`。"""
    import json
    from pathlib import Path
    root = Path(products_dir) / book
    out: dict[str, dict] = {}
    for f in sorted((root / "seed_admit").glob("p*.json")):
        seed = json.loads(f.read_text(encoding="utf-8"))["seed_admit"]
        af = root / "align_ref" / f.name
        align = json.loads(af.read_text(encoding="utf-8"))["align_ref"] if af.exists() else None
        facts = page_facts(seed, align)
        for cid, (code, detail) in page_causes(seed, align).items():
            out[cid.split(":", 1)[1]] = {"cause": code, "detail": detail, **facts.get(cid, {})}
    return out


def causes_md(book: str, res: dict[str, dict], sample: int = 8) -> str:
    """按码汇总成派单表：每码格数、占比、交给谁、几个例子。"""
    from collections import Counter, defaultdict
    n = len(res)
    cnt = Counter(v["cause"] for v in res.values())
    ex: dict[str, list[str]] = defaultdict(list)
    for cell, v in res.items():
        if len(ex[v["cause"]]) < sample:
            ex[v["cause"]].append(f"`{cell}`" + (f" {v['detail']}" if v["detail"] else ""))
    lines = [f"# {book} 待审格成因（{n} 格）", "", "| 码 | 成因 | 格数 | 占比 | 交给 | 例 |", "|---|---|---|---|---|---|"]
    for code in CAUSES:
        if cnt.get(code):
            name, who = CAUSES[code]
            lines.append(f"| {code} | {name} | {cnt[code]} | {cnt[code] / n:.0%} | {who} | {'；'.join(ex[code])} |")
    return "\n".join(lines) + "\n"
