"""4 定字·出口 gate `decide_gate`：**只检测，不判断**（2026-11-28，Sheldon 定；CV4）。

照 `cut_gate` 的样子：挂在第四步最后一步（今天是 `seed_admit`，以后改名 `char_decide` 时跟着换）出口，永远在最后跑，
读第四步全部产物（`seed_admit`、`align_ref`、`context_decision`、`glyph_match`、`char_index`），出一份检测清单
（`PageDecideGate`）。三条纪律：

1. **不改任何格**：不改字、不改放行、不挡别的步骤；本步产物也不被任何步骤读。
2. **不影响别的步骤的指纹**：只新增本步自己的模块与产物种类，没有任何现有 Step 把它列进 `consumes`／`code_deps`。
3. **只出证据**：检测出的问题由人和下游决定怎么办（修算法、重跑、送审）；某类检测稳定后要拦，就改收尾步的规则，
   不在这里拦。

检测项分两级：`fail`＝大概率有错，要人或书 Project 处理；`flag`＝可疑，留证据攒阈值。首批检测项（设计第三节表）：

| 级别 | 单位 | 名字 | 看什么 |
|---|---|---|---|
| fail | 列 | `step_error` | 第四步某列报错（整列没出结果；切字阶段本来就没过的「未过交接闸」「弹性 DP 无解」降为 flag `col_not_cut`） |
| fail | 列 | `ref_shift` | 连续 ≥k 个放行字恰好等于参校本错开一位（±1）的字、而不是本位的字（脉经 01 第 11、12 页类） |
| fail | 格 | `char_not_in_evidence` | 放行字不在候选、参校本字、上下文、证据、人裁任何一处出现过 |
| fail | 格 | `admit_blank_cell` | 放行格切分判成空白／空格（4c 状态不是 char 的代理，等 `cell_state` 独立后换成它） |
| flag | 页 | `no_align_ref` | 参校本对位产物缺席（降级运行） |
| flag | 页 | `unanchored_ref_admit` | 参校本没锚上、也没坐标对位，却有 ≥m 格靠参校本／上下文通道放行 |
| flag | 列 | `col_coord_fallback` | 整列坐标对位退回（附原因） |
| flag | 列 | `col_alt_cut` | 这列改用备选切法（挑路结果留复核） |
| flag | 格 | `rare_codepoint` | 放行字≠参校本字，且放行字是罕用码位（已放行字频低）、参校本字是它的常用异体形 |
| flag | 格 | `human_unbound` / `human_conflict` | 人裁绑丢；绑丢的人裁字与放行字不同 |
| flag | 格 | `group_without_4d` | 放行字在本书启用的字组里，却没经字组流程（缺省关，见 `check_group`） |
| flag | 页 | `upstream_error` | 识字或上下文的某列报错、带着缺证据放行 |

所有阈值在 `DecideGateParams`，量法与误报率见 ai-team `domain/CV/A24/decide-bench/`。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

from ..core.spec import GateLevel, GateSpec, StepSpec
from ..core.step import STEPS, RunContext, Step, attach_gate, register_step
from ..products.kinds.decide_gate import GateCheck, PageDecideGate

#: 靠参校本／上下文放行的通道（通道名里带 ref、或下面几个）；`unanchored_ref_admit` 用
REF_LANES = frozenset({"context", "coord_fallback", "witness3", "edge_pair", "follow_ref"})


#: 第四步列报错里属于「切字阶段本来就没过」的：交给 `cut_gate`，本闸只记 flag `col_not_cut`
UPSTREAM_CUT_ERRORS = ("未过交接闸", "弹性 DP 无解")


class DecideGateParams(BaseModel):
    shift_run_min: int = 3
    """`ref_shift`：连续这么多个放行字等于参校本错开一位的字，才报 fail。"""
    unanchored_min: int = 3
    """`unanchored_ref_admit`：参校本没锚上又没坐标对位的页，靠参校本／上下文通道放行 ≥ 这么多格才标。"""
    rare_freq_max: int = 5
    """`rare_codepoint`：放行字在 `form_freq.tsv`（已放行字频）里的次数 < 这个值才算罕用。"""
    partner_freq_min: int = 20
    """……且参校本字（它的异体）的字频 ≥ 这个值（有常用形）。"""
    check_group: bool = False
    """是否做 `group_without_4d`。**缺省关**：殿本 vol04 实测 50 页 8,006 个非人裁放行格里 855 格（10.7%）命中，
    绝大多数是字组没触发条件（库 same、整理本一致）的正常放行，不是漏判；等 4d `group_decision` 独立成产物、
    能分清「触发了没经流程」时再开。"""


# ── 工具 ─────────────────────────────────────────────────────────────

def _same(x: str | None, y: str | None) -> bool:
    if not x or not y:
        return False
    if x == y:
        return True
    from ..variants import are_variants
    return are_variants(x, y)


def _chars_in(v, out: set[str]) -> None:
    """证据里出现过的所有单字（递归取字符串值与列表元素）。"""
    if isinstance(v, str):
        if len(v) == 1:
            out.add(v)
    elif isinstance(v, dict):
        for x in v.values():
            _chars_in(x, out)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _chars_in(x, out)


def _sub_key(rec) -> tuple[int, str]:
    return rec.slot, (rec.sub or "")


def _col_of(rid: str) -> int | None:
    try:
        return int(rid.split(":")[2])
    except (IndexError, ValueError):
        return None


def _ref_maps(align, alt_cols) -> tuple[dict[str, str], dict[str, str]]:
    """参校本字：({格 id: 8-gram 对位字}, {格 id: 坐标对位字（空格不收）})。改用备选切法的列按备选那份读。"""
    if align is None:
        return {}, {}
    if alt_cols and align.alt_draft is not None and not align.alt_cols:
        from ..products.alt_view import merge_alt
        align = align.model_copy(deep=True)
        merge_alt(align, align.alt_draft, alt_cols)
    text = {c.id: c.align_char for c in align.chars if c.align_char}
    coord = {c.id: c.ref_char for c in align.coord if c.ref_char}
    return text, coord


def _match_by_id(match, alt_cols) -> dict:
    if match is None:
        return {}
    if alt_cols:
        match = match.with_alt(alt_cols)
    return {r.id: r for c in match.columns for r in c.chars}


def _known_chars(rid: str, rec, match_rec, ctx_rec, text_ref: dict, coord_ref: dict) -> set[str]:
    """这一格「有出处」的字：候选、参校本、上下文、证据里出现过的任何字。"""
    out: set[str] = set()
    if match_rec is not None:
        if match_rec.char:
            out.add(match_rec.char)
        out.update(c for c, _ in match_rec.candidates)
        for cv in match_rec.cand_variants:
            if cv.char:
                out.add(cv.char)
            out.update(c for c, _ in cv.candidates)
    if ctx_rec is not None:
        if ctx_rec.char:
            out.add(ctx_rec.char)
        out.update(c for c, _ in ctx_rec.ranked)
        if ctx_rec.llm_suggestion:
            out.add(ctx_rec.llm_suggestion)
    for m in (text_ref, coord_ref):
        if rid in m:
            out.add(m[rid])
    _chars_in(rec.evidence, out)
    return out


@lru_cache(maxsize=1)
def _edge_variants() -> frozenset:
    """`config/hanzi/core/edges.tsv` 里 relation=variant 的字对（无向）；文件不在（装成包时）返回空。
    變／𬽠、策／䇿 这类不在 `variants` 图里，只在边表里（decide-bench 打分口径同）。"""
    f = Path(__file__).resolve().parents[2] / "config" / "hanzi" / "core" / "edges.tsv"
    out: set = set()
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            t = line.split("\t")
            if len(t) > 2 and t[2] == "variant" and len(t[0]) == 1 and len(t[1]) == 1:
                out.add((t[0], t[1]))
                out.add((t[1], t[0]))
    return frozenset(out)


def _is_variant(a: str, b: str) -> bool:
    from ..variants import are_variants
    return (a, b) in _edge_variants() or are_variants(a, b)


def _is_human(rec) -> bool:
    return rec.channel == "human" or rec.provenance == "human" or bool((rec.evidence or {}).get("human") is True)


# ── 检测 ─────────────────────────────────────────────────────────────

def _shift_runs(cells: list, refs: dict[tuple[int, str, int], str], k: int) -> list[dict]:
    """一列（同 col、同 sub 的格按 slot 排好）里，放行字等于参校本错开一位的字的最长连续段 ≥k。"""
    out: list[dict] = []
    for s in (1, -1):
        run: list = []

        def flush():
            if len(run) >= k:
                out.append({"shift": s, "run": len(run), "ids": [r.id for r in run[:8]],
                            "slots": [run[0].slot, run[-1].slot], "sub": run[0].sub or ""})
            run.clear()
        for rec in cells:
            r_here = refs.get((_col_of(rec.id), rec.sub or "", rec.slot))
            r_next = refs.get((_col_of(rec.id), rec.sub or "", rec.slot + s))
            ok = (not _is_human(rec) and r_here and r_next and not _same(r_here, r_next)
                  and _same(rec.char, r_next) and not _same(rec.char, r_here))
            if ok and run and rec.slot - run[-1].slot != 1:
                flush()
            if ok:
                run.append(rec)
            else:
                flush()
        flush()
    return out


def detect_page(page: int, admit, *, align=None, match=None, ctxdec=None, chars=None,
                group_chars: Iterable[str] = (), params: DecideGateParams | None = None) -> PageDecideGate:
    """纯函数：一页的第四步产物 → 检测清单。不碰磁盘、不改入参。"""
    p = params or DecideGateParams()
    checks: list[GateCheck] = []
    alt_cols = list(admit.alt_cols or [])
    text_ref, coord_ref = _ref_maps(align, alt_cols)
    mrec = _match_by_id(match, alt_cols)
    crec = {} if ctxdec is None else {r.id: r for c in ctxdec.columns for r in c.chars if _col_of(r.id) not in alt_cols}
    blank = {}
    if chars is not None:
        cc = chars.with_alt(alt_cols) if alt_cols else chars
        blank = {r.id: r for c in cc.columns for r in c.chars if r.cell_type == "empty" or r.step3_kind == "blank"}
    gset = frozenset(group_chars)

    def add(name, level, unit, key, reason, **m):
        checks.append(GateCheck(name=name, level=level, unit=unit, key=str(key), reason=reason, metrics=m))

    n_cells = n_admit = 0
    n_ref_lane = 0
    freq = None
    for col in admit.columns:
        if col.error:
            if any(k in col.error for k in UPSTREAM_CUT_ERRORS):
                # 切字出口闸已拒收这列（`cut_gate` 管，这里不重复报 fail），只记一笔
                add("col_not_cut", "flag", "col", col.col, f"本列切字阶段就没过，第四步没出结果：{col.error}", error=col.error)
            else:
                add("step_error", "fail", "col", col.col, f"第四步本列报错，整列没出结果：{col.error}", error=col.error)
        by_sub: dict[str, list] = {}
        for rec in col.chars:
            n_cells += 1
            if not rec.admit:
                continue
            n_admit += 1
            if rec.channel and ("ref" in rec.channel or rec.channel in REF_LANES):
                n_ref_lane += 1
            by_sub.setdefault(rec.sub or "", []).append(rec)
            human = _is_human(rec)
            ev = rec.evidence or {}
            # ── 格：放行字没有任何出处
            if not human and rec.char:
                known = _known_chars(rec.id, rec, mrec.get(rec.id), crec.get(rec.id), text_ref, coord_ref)
                if known and rec.char not in known and not any(_same(rec.char, c) for c in known):
                    add("char_not_in_evidence", "fail", "cell", rec.id,
                        f"放行字「{rec.char}」不在候选、参校本、上下文、证据里的任何字之中（通道 {rec.channel}）",
                        char=rec.char, channel=rec.channel)
                elif not known:
                    add("char_not_in_evidence", "fail", "cell", rec.id,
                        f"放行字「{rec.char}」没有任何证据出处（通道 {rec.channel}）", char=rec.char, channel=rec.channel)
            if not human and rec.id in blank:
                b = blank[rec.id]
                add("admit_blank_cell", "fail", "cell", rec.id,
                    f"放行格在切分里是空白（cell_type={b.cell_type}，step3={b.step3_kind}），放行字「{rec.char}」",
                    char=rec.char, channel=rec.channel)
            # ── 格：人裁
            hu = ev.get("human_unbound")
            if hu:
                hc = hu.get("char") if isinstance(hu, dict) else None
                if hc and rec.char and not _same(hc, rec.char):
                    add("human_conflict", "flag", "cell", rec.id, f"人裁「{hc}」绑丢，且与放行字「{rec.char}」不同",
                        char=rec.char, human=hc, event=(hu or {}).get("event"))
                else:
                    add("human_unbound", "flag", "cell", rec.id, "有一条人裁没绑到这一格（位置过期？）",
                        char=rec.char, human=hc, event=(hu or {}).get("event") if isinstance(hu, dict) else None)
            # ── 格：罕用码位（放行字 ≠ 参校本字，而参校本字是它的常用异体形）
            if not human and rec.char:
                ref = coord_ref.get(rec.id) or text_ref.get(rec.id)
                if ref and ref != rec.char:
                    if freq is None:
                        from ..groups import edge_pairs
                        freq = edge_pairs._freq()
                    if (freq.get(rec.char, 0) < p.rare_freq_max and freq.get(ref, 0) >= p.partner_freq_min
                            and _is_variant(rec.char, ref)):
                        add("rare_codepoint", "flag", "cell", rec.id,
                            f"放行字「{rec.char}」是罕用码位（已放行字频 {freq.get(rec.char, 0)}），参校本作其常用异体「{ref}」（{freq.get(ref, 0)}）",
                            char=rec.char, ref=ref, channel=rec.channel)
            # ── 格：字组漏判
            if (p.check_group and not human and rec.char in gset and "group" not in ev
                    and rec.channel != "group_flow"):
                add("group_without_4d", "flag", "cell", rec.id,
                    f"放行字「{rec.char}」在本书启用的字组里，证据里却没有字组判定（通道 {rec.channel}）",
                    char=rec.char, channel=rec.channel)
        # ── 列：错开一位
        if p.shift_run_min > 0 and (text_ref or coord_ref):
            refs: dict[tuple[int, str, int], str] = {}
            for src in (text_ref, coord_ref):                   # 坐标对位每个字位都有，后写覆盖；缺的位用 8-gram 的
                for rid, ch in src.items():
                    if _col_of(rid) == col.col:
                        parts = rid.rsplit(":", 1)[1]
                        sub = parts[-1] if parts and parts[-1] in "ab" else ""
                        num = parts[:-1] if sub else parts
                        if num.lstrip("-").isdigit():
                            refs[(col.col, sub, int(num))] = ch
            for sub, cells in by_sub.items():
                cells.sort(key=lambda r: r.slot)
                for run in _shift_runs(cells, refs, p.shift_run_min):
                    add("ref_shift", "fail", "col", col.col,
                        f"第 {run['slots'][0]}–{run['slots'][1]} 格连续 {run['run']} 个放行字等于参校本"
                        f"{'后' if run['shift'] > 0 else '前'}一位的字（对位疑似错开一位）",
                        **run)
    # ── 列：坐标退回、备选切法
    if align is not None:
        for c, why in sorted((align.coord_fallback or {}).items()):
            add("col_coord_fallback", "flag", "col", c, f"整列坐标对位退回：{why}", why=why)
    for c in alt_cols:
        add("col_alt_cut", "flag", "col", c, "这列准入后定为改用备选切法", )
    # ── 页
    missing = [n for n, v in (("align_ref", align), ("glyph_match", match), ("context_decision", ctxdec),
                              ("char_index", chars)) if v is None]
    if align is None:
        add("no_align_ref", "flag", "page", page, "参校本对位产物缺席，本页按降级读")
    elif (not align.anchored and not align.coord_cols and n_ref_lane >= p.unanchored_min):
        add("unanchored_ref_admit", "flag", "page", page,
            f"参校本没锚上也没坐标对位，却有 {n_ref_lane} 格靠参校本／上下文通道放行", n=n_ref_lane)
    bad = [f"{n}:{c.col}" for n, pr in (("glyph_match", match), ("context_decision", ctxdec)) if pr is not None
           for c in pr.columns if getattr(c, "error", None) or getattr(c, "ok", True) is False]
    if bad:
        add("upstream_error", "flag", "page", page, "识字或上下文有列报错：" + "、".join(bad[:8]), cols=bad)
    return PageDecideGate(
        page=page, passed=not any(c.level == "fail" for c in checks), checks=checks,
        metrics={"n_cells": n_cells, "n_admit": n_admit, "admit_rate": round(n_admit / n_cells, 4) if n_cells else None,
                 "missing": missing})


# ── Step ─────────────────────────────────────────────────────────────

@register_step
class DecideGateStep(Step):
    spec = StepSpec(
        id="decide_gate", title="4 定字出口 gate（只检测，不判断）", version="1.0", unit="page",
        consumes=("seed_admit",),
        optional_consumes=("align_ref", "glyph_match", "context_decision", "char_index"),
        produces=("decide_gate",),
        params=DecideGateParams,
        code_deps=("open_guji_cv.products.kinds.decide_gate", "open_guji_cv.variants", "open_guji_cv.groups.edge_pairs",
                   "open_guji_cv.groups.registry"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: DecideGateParams = ctx.params_for(self)  # type: ignore[assignment]
        opt = {k: (ctx.product(k, page) if ctx.has_product(k, page) else None)
               for k in ("align_ref", "glyph_match", "context_decision", "char_index")}
        gset: frozenset[str] = frozenset()
        if p.check_group:
            from ..groups.registry import FLOW_GROUPS, flow_names
            names = flow_names(getattr(ctx.params_for(STEPS["seed_admit"]), "group_flow", ()) or ())
            gset = frozenset(c for g in names if g in FLOW_GROUPS for c in FLOW_GROUPS[g].members)
        res = detect_page(page, ctx.product("seed_admit", page), align=opt["align_ref"], match=opt["glyph_match"],
                          ctxdec=opt["context_decision"], chars=opt["char_index"], group_chars=gset, params=p)
        return {"decide_gate": res}


DECIDE_GATE_SPEC = GateSpec(
    id="decide_gate", unit="page", on_fail="flag",       # 只检测：fail 不挡任何步骤，由 manager 体检／各书 Project 读
    levels=(
        GateLevel(id="G1", unit="column", name="step_error", desc="第四步某列报错（整列没出结果）——fail"),
        GateLevel(id="G2", unit="column", name="ref_shift", desc="连续放行字等于参校本错开一位的字——fail"),
        GateLevel(id="G3", unit="cell", name="char_not_in_evidence", desc="放行字没有任何出处——fail"),
        GateLevel(id="G4", unit="cell", name="admit_blank_cell", desc="放行格在切分里是空白——fail"),
        GateLevel(id="G5", unit="page", name="no_align_ref", desc="参校本对位缺席、参校本没锚上却靠参校本通道放行——flag"),
        GateLevel(id="G6", unit="column", name="col_coord_fallback", desc="整列坐标退回／改用备选切法——flag"),
        GateLevel(id="G7", unit="cell", name="rare_codepoint", desc="放行字≠参校本字，且是参校本常用字的罕用异体码位——flag"),
        GateLevel(id="G8", unit="cell", name="human_unbound", desc="人裁绑丢或与放行字冲突——flag"),
        GateLevel(id="G9", unit="cell", name="group_without_4d", desc="放行字在启用的字组里却没经字组流程——flag"),
    ),
)
attach_gate("seed_admit", DECIDE_GATE_SPEC)
