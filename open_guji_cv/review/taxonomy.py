"""待审格分类规范（A31，2026-10-28）：每个待审格 → (大类, 小类, 键, 跟进方, 处理方式)。

在 `causes.py` 的主成因码（A1…I）上细分，并把 `eval/review_breakdown.py` 的 G/V/N/O 并进来（对照表见
ai-team `domain/CV/质检/待审分类规范.md`）。纯函数，只看线上待审单里一格自带的字段，不碰产物包：

    cause（成因码）、cause_detail、why（疑问码）、ref.c（整理本字）、ctx.c（文意字）、lib_top、occ、recheck，
    以及发布时补的 `grp`（字组 id）、`refc`（整理本字，单子里没 ref 时用）。

字段缺的格（vol51–99 的瘦单只有 cause／cause_detail）退化成按成因码＋细节判，小类粗一点，不报错。
统计入口 `scripts/zhengli/pending_stats.py`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: 大类 → (名, 一句话)
BIG: dict[str, tuple[str, str]] = {
    "S": ("切分／对位", "框或列格对不上整理本，字不是难认而是裁错了位"),
    "O": ("遮挡", "印章或污损盖住了字"),
    "Z": ("形近字组", "己已巳、日曰目等字组流程没定"),
    "M": ("码位异体", "整理本字与库字是异体，要看码位表或刻形"),
    "L": ("字形库／识别", "库里没有、库有把握不够、库首选已对但仍被拦"),
    "R": ("整理本／语料", "整理本与图冲突，或对齐改字层"),
    "P": ("只能人审", "没有自动解：整理本缺字〓、复审格"),
    "U": ("未归类", "没有成因码，或码不认识"),
}

#: 处理方式：auto＝改算法或补数据后可批量放行（预期，未实测）；confirm＝可快速确认（看一眼）；decide＝要 sheldon 定口径；human＝只能人逐格看
FIX = {"auto": "算法／数据可解", "confirm": "快速确认", "decide": "待定口径", "human": "只能人审"}

#: 小类 → (大类, 名, 跟进方, 处理方式, 怎么判)
SUBS: dict[str, tuple[str, str, str, str, str]] = {
    "S1": ("S", "乱码闸：字形像框线／墨点", "A22", "auto", "成因 A6：整理本这位没字且 ctx_garble_shape 等乱码护栏拦下"),
    "S2": ("S", "列格数与整理本字数对不上", "A22", "auto", "成因 A3：整列没对位"),
    "S3": ("S", "整页锚不上整理本", "A22", "auto", "成因 A5"),
    "S4": ("S", "与现役对位冲突，整列退回", "A22", "auto", "成因 A4"),
    "S5": ("S", "坐标对位说这一位是空格（多半假格）", "A22", "auto", "成因 A1"),
    "S6": ("S", "整理本这位没字（别的原因）", "A22", "auto", "成因 A9"),
    "O1": ("O", "遮挡·整页成片（首叶印章等）", "A31", "confirm", "成因 D，且同页遮挡格 ≥ 15；整理本有字"),
    "O2": ("O", "遮挡·零散，整理本有字", "A31", "confirm", "成因 D，整理本有字（occ.ref_blank=false 或 ref 有字）"),
    "O3": ("O", "遮挡·整理本这位没字", "A32", "human", "成因 D，ref 空／〓（occ.ref_blank=true）"),
    "O0": ("O", "遮挡·单子缺整理本信息", "A31", "confirm", "成因 D，单子没有 ref／occ（瘦单）"),
    "Z1": ("Z", "字组流程弃权", "A24", "auto", "成因 C，疑问码含 group_flow_abstain：文意表缺／字形判法弃权"),
    "Z2": ("Z", "字组流程分歧／与整理本异议", "A24", "decide", "成因 C，含 group_flow_disagree／ref_dissent／coord_dissent／ctx_contra／conflict"),
    "Z3": ("Z", "字组弱证据降审", "A24", "auto", "成因 C，含 group_flow_joint／weak"),
    "Z4": ("Z", "只有形近护栏（无字组流程结论）", "A24", "auto", "成因 C，只有 near_form／solo_confusable／ji_yi_si_review"),
    "M1": ("M", "码位已定，单子未跟上", "A30", "auto", "成因 B，字对已在 codepoints.yaml：重落即按码位放行"),
    "M2": ("M", "码位未定", "A24", "decide", "成因 B，字对不在 codepoints.yaml：sheldon 定码位或做刻形判法"),
    "L1": ("L", "库里没有这个字", "A23", "auto", "成因 F：补刻例"),
    "L2": ("L", "库首选＝整理本，仍被拦", "A23", "auto", "成因 H：看 why，ctx_guard_ref＝文意与整理本不一"),
    "L3": ("L", "证据不足（库 unsure、文意不够）", "A23", "human", "成因 I：兜底，目标 <10%"),
    "R1": ("R", "与整理本冲突", "A31", "human", "成因 E：context_vs_ref／iron_vs_ref 等"),
    "R2": ("R", "对齐改字层（replace 段）", "A31", "human", "成因 G：整理本这段是 replace"),
    "P1": ("P", "整理本写〓（没码位的生僻字）", "A32", "human", "成因 A2"),
    "P2": ("P", "复审格", "A32", "human", "单子里 recheck=true（上一单留下、请照书影核定）"),
    "U0": ("U", "未归类", "A31", "human", "没有成因码，或码不在表里"),
}

_DISSENT = {"group_flow_disagree", "group_flow_ref_dissent", "group_flow_coord_dissent", "group_flow_ctx_contra",
            "group_flow_conflict"}
_WEAK = {"group_flow_joint", "group_flow_weak"}
_MISSING_REF = {"", "〓", None}

#: 页内遮挡格 ≥ 这个数算「整页成片」
OCC_PAGE_MIN = 15
#: 同列待审 ≥ COL_MIN 算「整列出问题」；同页 ≥ PAGE_MIN 算「整页」
COL_MIN, PAGE_MIN = 5, 15


@dataclass(frozen=True)
class Verdict:
    big: str
    sub: str
    key: str
    owner: str
    fix: str


def _tok(cell: dict) -> set[str]:
    out = set()
    for x in list(cell.get("why") or []) + str(cell.get("cause_detail") or "").split(","):
        if isinstance(x, str) and x:
            out.add(re.split(r"[(（:：]", x, maxsplit=1)[0].strip())
    return out


def _c(v) -> str | None:
    """ref／ctx 可能是 {"c":…} 也可能是字符串。"""
    return v.get("c") if isinstance(v, dict) else v


def _ref(cell: dict):
    r = _c(cell.get("ref"))
    return r if r is not None else cell.get("refc")


def group_of_cell(cell: dict, group_of=None) -> str:
    """字组 id：发布时补的 `grp` 优先；没有就按整理本字／文意字／库首选查登记表。"""
    if cell.get("grp"):
        return cell["grp"]
    if group_of:
        tops = [x.get("c") for x in cell.get("lib_top") or []][:1]
        for ch in (_ref(cell), _c(cell.get("ctx")), *tops):
            if ch and (g := group_of(ch)):
                return g
    return "?"


def pair_key(cell: dict) -> tuple[str, str] | None:
    """B／E／G／I 的 cause_detail 是「库字/整理本字」。"""
    a, _, b = str(cell.get("cause_detail") or "").partition("/")
    return (a, b) if a and b else None


def classify(cell: dict, *, occ_page_n: int = 0, decided=None, group_of=None) -> Verdict:
    """`occ_page_n`＝本页遮挡格数；`decided(a, b)`＝码位表里这对是否已定；`group_of(ch)`＝字→字组 id。"""
    cause = cell.get("cause")
    tok = _tok(cell)

    def v(sub: str, key: str = "") -> Verdict:
        _, _, owner, fix, _ = SUBS[sub]
        return Verdict(SUBS[sub][0], sub, key, owner, fix)

    if cause is None:
        return v("P2") if cell.get("recheck") else v("U0")
    if cause == "D":
        occ = cell.get("occ")
        ref = _ref(cell)
        if isinstance(occ, dict) and occ.get("ref_blank"):
            return v("O3")
        if "ref" in cell and ref in _MISSING_REF:
            return v("O3")
        if isinstance(occ, dict) or "ref" in cell:
            return v("O1" if occ_page_n >= OCC_PAGE_MIN else "O2", ref or "")
        return v("O0")
    if cause == "C":
        g = group_of_cell(cell, group_of)
        sub = "Z2" if tok & _DISSENT else "Z1" if "group_flow_abstain" in tok else "Z3" if tok & _WEAK else "Z4"
        return v(sub, g)
    if cause == "B":
        p = pair_key(cell)
        k = "/".join(sorted(p)) if p else ""
        return v("M1" if p and decided and decided(*p) else "M2", k)
    if cause == "F":
        return v("L1", str(cell.get("cause_detail") or _ref(cell) or ""))
    if cause == "H":
        return v("L2", "ctx_guard_ref" if "ctx_guard_ref" in tok else "group_dissent" if tok & _DISSENT else "其他")
    if cause == "I":
        return v("L3", "ctx空" if not _c(cell.get("ctx")) else "ctx有字")
    if cause == "E":
        p = pair_key(cell)
        return v("R1", "/".join(sorted(p)) if p else "")
    if cause == "G":
        p = pair_key(cell)
        return v("R2", "/".join(sorted(p)) if p else "")
    if cause == "A2":
        return v("P1")
    sub = {"A6": "S1", "A3": "S2", "A5": "S3", "A4": "S4", "A1": "S5", "A9": "S6"}.get(cause)
    if sub:
        return v(sub, str(cell.get("cause_detail") or "")[:40] if sub in ("S1", "S2") else "")
    return v("U0", str(cause))


def cell_pos(cell_id: str) -> tuple[str, str] | None:
    """格号 `页:列:行` → (页, 页:列)。"""
    p = str(cell_id).split(":")
    return (p[0], f"{p[0]}:{p[1]}") if len(p) >= 2 else None


def conc_tag(page_n: int, col_n: int) -> str:
    return "整页" if page_n >= PAGE_MIN else "整列" if col_n >= COL_MIN else "零散"
