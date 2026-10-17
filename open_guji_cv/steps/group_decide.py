"""Step6b：形近字组分类器的统一出口（overview GUJI-49，PR1）。

本页每个**整理本对位字落在某字组成员内**的格，查该组的 `group_clf/1` 答案表
（`CV形近字分组/计划/分块-B1接口与放行闸-Ethan.md` §2.1），产出 `group_decision`。

**只出证据，不动放行**：没有任何现有 Step 读它（`seed_admit` 照旧读自己的 `ry_group` 等），
所以加这一步不让任何现有产物过期；PR2 才让 `seed_admit` 改读。`action` 恒为 `none`。

默认关：书级开关 `BookSpec.group_decide`（缺省 False），关时 `Engine._enabled` 把本步滤掉；
开了但 `group_tables` 为空也只产空产物。

弃权语义（B1 §2.1）：`char: null`＝不给字；缺格、`ctx` 不符、`ver` 不符一律弃权并写 `why`。

ctx 口径（GUJI-208bz 起）：序列范围与 `seed_admit._clf_ctx` 相同——**整页**列号升序展平、
窗口可跨列；取字仍不同：本步在 `seed_admit` 之前，拿不到「邻格已放行字」，邻格取
`glyph_match` 的 same 档字，否则整理本字，否则 `□`。（seed_admit 另剔 `excluded` 格，本步拿不到名单，不剔。）
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, Field

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.group import GroupDecRec, PageGroupDecision
from ..groups import GROUPS, JudgeInput, window_from_text
from ..groups.backends import GroupClfTableBackend
from ..products.kinds.recog import PageAlignRef, PageMatch

#: 字组 id → 成员字。S2a 起取自 `groups.registry.GROUPS`（单一真源），本步目前只服务 ry／jys 两组的答案表。
GROUP_MEMBERS: dict[str, frozenset[str]] = {g: GROUPS[g].members for g in ("ry", "jys")}

CTX_WIDTH = 30


class GroupDecideParams(BaseModel):
    group_tables: dict[str, str] = Field(default_factory=dict)
    """字组 id → `group_clf/1` 答案表路径。**缺省空＝本步不干活**。路径是机器属性，不进指纹
    （`path_params`），内容由 `group_tables_fingerprint` 把关。"""
    group_tables_fingerprint: str = ""
    """表内容哈希，留空自动填（有表时）——换了表内容，产物要判过期。"""

    def model_post_init(self, _ctx) -> None:
        if self.group_tables and not self.group_tables_fingerprint:
            object.__setattr__(self, "group_tables_fingerprint", tables_fingerprint(self.group_tables))


def tables_fingerprint(tables: dict[str, str]) -> str:
    h = hashlib.sha256()
    for g in sorted(tables):
        p = Path(tables[g])
        h.update(g.encode())
        h.update(hashlib.sha256(p.read_bytes()).digest() if p.exists() else b"missing")
    return h.hexdigest()[:16]


@lru_cache(maxsize=8)
def _load_table(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def lookup(table: dict, group: str, cell_id: str, left: str, right: str) -> dict:
    """查一张 `group_clf/1` 表 → `{char, conf, why}`；一切不确定都弃权并写明原因。

    S2a：读表实现已搬到 `groups.GroupClfTableBackend`（统一的后端），这里只是保留旧名与旧返回形状的薄包装。"""
    spec = SimpleNamespace(id=group, members=GROUP_MEMBERS.get(group, frozenset()))
    v = GroupClfTableBackend(table).judge(spec, JudgeInput(cell_id, None, window_from_text(left, right)))
    return {"char": v.char, "conf": v.conf, "why": v.why}


def _opt(ctx: RunContext, kind: str, page: int):
    try:
        return ctx.product(kind, page)
    except Exception:
        return None


def _neighbour_ctx(seq: list[tuple[str, str]], i: int, step: int) -> str:
    """第 i 格前（-1）／后（+1）至多 CTX_WIDTH 字，读序；邻格取 same 档字，否则整理本字，否则 □。"""
    out: list[str] = []
    j = i + step
    while 0 <= j < len(seq) and len(out) < CTX_WIDTH:
        out.append(seq[j][0] or seq[j][1] or "□")
        j += step
    return "".join(reversed(out)) if step < 0 else "".join(out)


@register_step
class GroupDecideStep(Step):
    spec = StepSpec(
        id="group_decide", title="Step6b 形近字组分类", version="1.0", unit="cell",
        consumes=("glyph_match",), optional_consumes=("align_ref",),
        produces=("group_decision",),
        params=GroupDecideParams,
        code_deps=("open_guji_cv.utils.ji_yi_si_clf", "open_guji_cv.utils.ry_group",
                   "open_guji_cv.groups.registry", "open_guji_cv.groups.protocol", "open_guji_cv.groups.backends"),
        path_params=("group_tables",),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: GroupDecideParams = ctx.params_for(self)  # type: ignore[assignment]
        out = PageGroupDecision(page=page, tables_fingerprint=p.group_tables_fingerprint)
        if not p.group_tables:
            return {"group_decision": out}
        match: PageMatch | None = _opt(ctx, "glyph_match", page)
        ref: PageAlignRef | None = _opt(ctx, "align_ref", page)
        if match is None or ref is None or not ref.anchored:
            return {"group_decision": out}
        amap = {c.id: c.align_char for c in ref.chars}
        same = {r.id: (r.char if r.verdict == "same" else None)
                for col in match.columns for r in col.chars}
        tables = {g: _load_table(path) for g, path in p.group_tables.items()}
        # 页宽口径（GUJI-208bz）：整页列号升序展平成**一条**序列，邻格窗口可跨列——与
        # `seed_admit._ry_group_pass` 的 `seq` 同一取法（口径差 2）。取字仍是 same→整理本→□。
        cols = sorted(match.columns, key=lambda c: c.col)
        flat = [r for col in cols for r in col.chars]
        seq = [(same.get(r.id) or "", amap.get(r.id) or "") for r in flat]
        for i, r in enumerate(flat):
            rc = amap.get(r.id)
            if not rc:
                continue
            for g, members in GROUP_MEMBERS.items():
                if g not in tables or rc not in members:
                    continue
                res = lookup(tables[g], g, r.id, _neighbour_ctx(seq, i, -1), _neighbour_ctx(seq, i, 1))
                out.cells.append(GroupDecRec(id=r.id, group=g, ref=rc, **res))
        return {"group_decision": out}
