# -*- coding: utf-8 -*-
"""`guji rerun --stale <册>`：只重跑被显式标失效的页及其下游（GUJI-578，设计 §5.2 第 4 条）。

人裁落定后，`product_invalidate` 消费者只把对应页的 manifest 条目标 `invalidated`（只标不跑）。
以前要么整册 `pipeline`（把因 cv 升版、字形库变化而过期的页也一起重算），要么人工挑页。
这里只收集「哪些步的哪些页被显式标了失效」，从最早的那一步起逐步往下跑：每一步只跑
本步失效的页，加上上游这一轮真的重算了的页；上游跳过的页不往下传。

注意：页集之外因别的原因过期的页（cv 升版、字形库变）**不跑**——那是冻结基线规矩里
「只记不报」的一类，要跑请显式 `guji pipeline`。闸跟着宿主步自动跑（`Engine.run`）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StalePlan:
    by_step: dict[str, list[int]] = field(default_factory=dict)   # 步 → 显式失效的页
    reasons: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def pages(self) -> list[int]:
        return sorted({p for ps in self.by_step.values() for p in ps})

    def first_step(self, order: list[str]) -> str | None:
        for sid in order:
            if self.by_step.get(sid):
                return sid
        return None


def plan(eng, pages: list[int] | None = None) -> StalePlan:
    """扫管线里每一步的 manifest，收集 `invalidated` 非空的页（含挂在步上的闸）。"""
    from ..core.spec import parse_key
    from ..core.step import STEPS
    want = set(pages) if pages is not None else None
    out = StalePlan()
    sids: list[str] = []
    for sid in eng.pipeline.steps:
        sids.append(sid)
        g = STEPS[sid].spec.gate
        if g:
            sids.append(g.id)
    host = {STEPS[s].spec.gate.id: s for s in eng.pipeline.steps if STEPS[s].spec.gate}
    for sid in sids:
        man = eng.store.manifest(eng.book.id, sid)
        for key, e in man.all().items():
            if not e.invalidated:
                continue
            try:
                pg = parse_key(key)[0]
            except ValueError:
                continue
            if want is not None and pg not in want:
                continue
            run_as = host.get(sid, sid)          # 闸失效 = 从宿主步起跑
            out.by_step.setdefault(run_as, [])
            if pg not in out.by_step[run_as]:
                out.by_step[run_as].append(pg)
            r = out.reasons.setdefault(run_as, {})
            why = e.invalidated.split(";")[0].strip()[:60]
            r[why] = r.get(why, 0) + 1
    for v in out.by_step.values():
        v.sort()
    return out


def run(eng, steps_after, pages: list[int] | None = None, to_step: str | None = None,
        dry_run: bool = False, jobs: int = 1, log=print):
    """`steps_after(from_step, to_step)` → 实际要跑的步列表（CLI 传 `cli_steps`，套书级开关）。
    返回 (plan, report 或 None)。"""
    p = plan(eng, pages)
    first = p.first_step(eng.pipeline.steps)
    if first is None:
        log("没有显式失效的页，什么也不跑")
        return p, None
    steps = steps_after(first, to_step)
    log(f"显式失效：{sum(len(v) for v in p.by_step.values())} 处，涉及 {len(p.pages)} 页："
        + "；".join(f"{s} {len(v)} 页" for s, v in p.by_step.items()))
    log(f"从 {first} 起跑 {len(steps)} 步，只跑这些页：{_fmt_pages(p.pages)}")
    if dry_run:
        return p, None
    # 一步一步跑：本步要跑的页 = 本步显式失效的页 ∪ 上游这一轮真重算了（ok）的页。
    # 上游跳过（新鲜）的页不往下传，免得把只因 cv 升版而过期的下游也一并重算。
    carried: set[int] = set()
    outcomes = []
    rep = None
    for sid in steps:
        run_pages = sorted(set(p.by_step.get(sid, [])) | carried)
        if not run_pages:
            continue
        rep = eng.run(steps=[sid], pages=run_pages, jobs=jobs)
        outcomes.extend(rep.outcomes)
        carried |= {o.page for o in rep.outcomes if o.status == "ok"}
    if rep is not None:
        rep.outcomes = outcomes
    return p, rep


def _fmt_pages(pages: list[int]) -> str:
    if not pages:
        return "—"
    out, start, prev = [], pages[0], pages[0]
    for x in pages[1:] + [None]:
        if x is not None and x == prev + 1:
            prev = x
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        if x is not None:
            start = prev = x
    return ",".join(out)
