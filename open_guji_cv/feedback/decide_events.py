"""收尾步事件的读口：`target.step` 的 `seed_admit`／`char_decide` 当同一步（CV4 P3a-1，2026-11-28）。

承诺（`ai-team domain/CV/A24/P3-接口变更通知-2026-11-28.md` 第四、六节）：

- D1 里历史事件的 `target.step=seed_admit` **永不改写**；读端永久并认两个名字；
- 「后到覆盖」按 `replay_key`（写入时间）先后重放，旧名事件与新名事件落在同一个格上互相覆盖，读时归一；
- 失效（`product_invalidate`）同时作用于两个产物目录；
- 写端本版仍写旧名（`core.decide_names.ADMIT_STEP_ACTIVE`），读端都认新名之后再切。

本模块只做读与失效，不写事件。不在任何 Step 的 `code_deps` 里。
"""

from __future__ import annotations

from typing import Iterable

from ..core.decide_names import ADMIT_STEPS, canonical_step, is_admit_step, same_admit_step  # noqa: F401  再导出
from .events import Event, replay_key


def admit_events(events: Iterable[Event], book: str | None = None, kinds: Iterable[str] | None = None,
                 unit: str | None = "cell") -> list[Event]:
    """只留收尾步名下的事件（新旧名都算），按 `replay_key` 升序。`book`／`kinds`／`unit` 给了就再筛（`unit=None` 不筛）。"""
    want = set(kinds) if kinds is not None else None
    out = []
    for e in events:
        t = e.target
        if not is_admit_step(t.step):
            continue
        if unit is not None and t.unit != unit:
            continue
        if book is not None and t.book != book:
            continue
        if want is not None and e.kind not in want:
            continue
        out.append(e)
    out.sort(key=replay_key)
    return out


def decided_view(events: Iterable[Event], book: str | None = None, kinds: Iterable[str] | None = None) -> dict[str, Event]:
    """每个格 `target.key` 的**最终**收尾事件（后到覆盖；旧名与新名当同一步，谁晚谁赢）。"""
    return {e.target.key: e for e in admit_events(events, book=book, kinds=kinds)}


def ruling_by_u(events: Iterable[Event], book: str | None = None, kinds: Iterable[str] | None = None) -> dict[tuple[str, int], Event]:
    """按字格永久编号 `payload.u` 查的最终裁定：`{(册, u): 事件}`，后到覆盖，新旧名同一步。
    没有整数 `u` 的事件不进表。"""
    out: dict[tuple[str, int], Event] = {}
    for e in admit_events(events, book=book, kinds=kinds):
        u = (e.payload or {}).get("u")
        if isinstance(u, int) and not isinstance(u, bool) and u > 0 and e.target.book:
            out[(e.target.book, u)] = e
    return out


def invalidate_final(store, book: str, key: str, reason: str, cells: list[str] | None = None) -> list[str]:
    """把某页收尾产物显式失效：**两个名字的目录都标**（只标存在条目的）。返回被标的步名。
    `cells` 给了只失效这些格（同 `Manifest.invalidate`）。"""
    done = []
    for step in ADMIT_STEPS:
        if store.manifest(book, step).invalidate(key, reason, cells):
            done.append(step)
    return done
