# -*- coding: utf-8 -*-
"""5a.2：形近字组里**只看字形**的判法，前移到第 5 步跑（2026-11-16，Sheldon 定；OCR 研究 Project）。

## 分段

    5a.1  CNN 匹配＋分流（`clustering/near_route.py`）：首位字落形近字组表、或属于注册字组 → near_group；近邻一致度不满 → weak
    5a.2  本模块：near_group 的格，按字组注册表里**只吃字块图**的方法（量横、数横、宽高比、整字 HOG、IDS 部件……）判一遍
    5a.3… 以后加的字形方法（没有注册组的对的通用判别区域、weak 格的第二路）照这个接口往后排
    5b    生僻字候选
    第 7 步 要文意、整理本、书级字频与码位的判法，以及补放／复核／改字这些策略，照旧在 `seed_admit.group_flow`

## 只做什么

- **方法不另写**：直接取 `registry` 里各组 `FlowSpec.methods`（及两段判的 `form_methods`）中 `needs_patch` 的那些，原样调用。
  字组的单一真源还是注册表；一个方法该不该跑、门槛多少，都在方法自己那里。
- **不给整理本、不给文意**：`MethodInput.ref／left／right／coord／cur` 一律空。靠整理本当护栏的方法（`Only`、`zy_strokes`）会自己弃权，
  这些组留给第 7 步。
- **只出「字形判定」**：给字的方法全一致 → `char`；互相冲突、全弃权、或这一组没有字形方法 → `char=None`。
  拿它怎么用（直接定字，还是只当证据交第 7 步和文意、整理本互证）由调用方按 `final()` 决定：组的方法数组里只有字形方法、
  又没有声明任何要整理本互证的策略，才算字形能单独定字。

## 现状（注册表 185 个流程组，`inventory()`）

| | 组数 | 例 |
|---|---|---|
| 字形能单独定字（`final`） | 9 | 由出山、宋朱未、名各、必心、衛衞、刪删、扺抵 |
| 有字形方法，但要和文意／字频／整理本互证（只当证据） | 71 | 日曰、入人八、未末、土士、大太、玉王、一二、十士、彝、點㸃 |
| 没有字形方法（只有文意／字频／码位归一） | 105 | 己已巳、戊戌戍、目自、木本；码位归一 79 组 |

能单独定字的只有 9 组，是因为现有字形方法当初多数是配着整理本互证上线的（`lift_ref_agree`、`lift_ref_veto`、`Only` 等）。
要把一组从「只当证据」提到「单独定字」，得先在人裁格上量它**不看整理本**时的准确率，过了再把互证策略摘掉。

本模块不在任何 Step 的 `code_deps` 里（还没接进 `glyph_match`），合进来不动各书指纹。分层同 `groups` 包：只 import 包内模块。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .methods import Chain, MethodInput
from .registry import FLOW_GROUPS

# 声明了这些策略的组，字形判定要和整理本互证才能放：5a.2 只留证据，不单独定字
_REF_POLICIES = ("lift_ref_agree", "lift_ref_veto", "tolerate_ref_agree", "lift_img_ref_veto", "review_ref_agree", "ref_enter", "ref_top_enter")


def _flat(methods) -> list:
    out = []
    for m in methods:
        out += _flat(m.steps) if isinstance(m, Chain) else [m]
    return out


def shape_methods(gid: str) -> tuple:
    """这一组里只吃字块图的方法（按注册顺序；两段判的形选择方法排在后面，去重）。没有这个组或没有字形方法 → ()。"""
    g = FLOW_GROUPS.get(gid)
    if g is None or g.flow is None:
        return ()
    ms = [m for m in _flat(g.flow.methods) if m.needs_patch]
    if g.flow.families:
        ms += [m for m in _flat(g.flow.form_methods) if m.needs_patch and m not in ms]
    return tuple(ms)


def final(gid: str) -> bool:
    """字形能不能在第 5 步单独定字：方法数组里全是字形方法，且组没有声明要整理本互证的策略、不是两段判。"""
    g = FLOW_GROUPS.get(gid)
    if g is None or g.flow is None or g.flow.families:
        return False
    ms = _flat(g.flow.methods)
    return bool(ms) and all(m.needs_patch for m in ms) and not any(getattr(g.flow, k) for k in _REF_POLICIES)


@dataclass(frozen=True)
class ShapeVerdict:
    group: str
    char: str | None
    """给字的字形方法全一致时的那个字；否则 None。"""
    why: str
    """`agree`／`conflict`／`abstain`／`no_method`／`no_patch`。"""
    final: bool = False
    """这一组字形能单独定字（见 `final()`）且 `char` 非空。"""
    solvers: tuple = field(default_factory=tuple)
    """每个方法的留痕：(方法名, 给的字或 None, 置信度, why)。"""


def judge(gid: str, cell_id: str, cands: list, patch_fn: Callable[[str], Any], cfg: Any = None) -> ShapeVerdict:
    """一格按组的字形方法判一遍。`cands`：库候选 [(字, 分)]；`patch_fn`：格 id → 灰度字块；`cfg`：`flow.FlowConfig`（IDS 模板库等书级路径）。"""
    ms = shape_methods(gid)
    if not ms:
        return ShapeVerdict(gid, None, "no_method")
    if patch_fn is None or patch_fn(cell_id) is None:
        return ShapeVerdict(gid, None, "no_patch")
    inp = MethodInput(group=gid, members=frozenset(FLOW_GROUPS[gid].members), cell_id=cell_id, cands=list(cands), ref=None, cfg=cfg,
                      patch_fn=patch_fn)
    rows = []
    for m in ms:
        v = m.run(inp)
        rows.append((m.name, v.char, v.conf, v.why))
    picked = {c for _, c, _, _ in rows if c is not None}
    if len(picked) == 1:
        c = next(iter(picked))
        return ShapeVerdict(gid, c, "agree", final(gid), tuple(rows))
    return ShapeVerdict(gid, None, "conflict" if picked else "abstain", False, tuple(rows))


def inventory() -> dict[str, list[str]]:
    """注册表按「字形方法有没有、能不能单独定字」分三类（给文档与排期用）。"""
    out: dict[str, list[str]] = {"final": [], "evidence": [], "none": []}
    for gid in FLOW_GROUPS:
        out["final" if final(gid) else ("evidence" if shape_methods(gid) else "none")].append(gid)
    return out
