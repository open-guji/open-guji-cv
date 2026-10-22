"""IDS 通用计算 第一步：由组成员的 IDS 自动导出「怎么切、看哪一块」（切分计划），不再逐组手填 orient／which／frame。

思路（差分驱动）：组内各字的 IDS 在最浅一层上对齐——结构符（⿰⿱⿳…）和元数相同的，逐位置往下比；
位置上各字写法完全相同的是**公共部件**（不用看），不同的才是**判别位置**。判别位置上的写法就是该位置要认的候选部件。
结构符不同，或到了无法再对齐的叠合（⿻）／包围（⿴⿵…）里写法互异，就退成「整字」判法（与手写 SPECS 里 whole 的组一致）。

和手写 `ids_online.SPECS` 的对应：
  `orient`  ← 结构符（⿰⿲ 左右切＝v；⿱⿳ 上下切＝h）
  `which`   ← 判别位置的序号（0 左／上…）
  `frame`   ← 公共部件 ＋ 判别位置占位（`⿱厽{}`）
  别名／停止点仍来自 `ids_override.tsv`（`alias` 把不同拆法归成同形，如 㐱→彡）；本模块只做对齐，不展开数据。
一个字可有多个写法（ids_lv1 以分号分隔），取使判别位置**最少**、结构最一致的一组组合。
本模块只依赖 `ids`（标准库），不被任何 Step 引用，不在 `code_deps` 里：加它不让各书产物过期。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

from .ids import Node, _flatten, load_override, load_table, parse

#: 结构符 → 切向（v＝左右切，h＝上下切）。包围／叠合结构没有直线切法。
ORIENT = {"⿰": "v", "⿲": "v", "⿱": "h", "⿳": "h"}


@dataclass(frozen=True)
class Slot:
    """对齐后树上的一个位置。`same`＝各字写法相同；否则 `options` 是各字在此处的写法（字 → 串）。"""
    same: bool
    text: str = ""                              # same 时：公共写法
    options: tuple = ()                         # not same 时：((字, 写法), …)
    sub: tuple = ()                             # not same 且结构符一致时：往下一层的 Slot
    idc: str = ""                               # sub 非空时的结构符


@dataclass(frozen=True)
class Plan:
    """一组的切分计划。`mode`：
    - `split`：根结构符一致、有判别位置，可按 `orient` 切，`diff` 是判别位置的序号；
    - `whole`：结构符不同／无法直线切（⿻⿴⿵⿸…），整字判；
    - `same`：各字 IDS 完全一样（絕絶：差别在 IDS 之下的笔画），整字判。"""
    mode: str
    idc: str = ""
    orient: str = ""
    arity: int = 0
    diff: tuple = ()
    root: Slot | None = None
    picks: dict = field(default_factory=dict)   # 字 → 选用的写法
    frame: str = ""                             # 如 `⿱厽{}`；判别位置用 `{}` 占位（多个判别位置则逐个 `{}`）

    @property
    def cuts(self) -> int:
        """要切几刀（元数−1）。"""
        return max(self.arity - 1, 0) if self.mode == "split" else 0


def _norm(n: Node, alias: dict) -> Node:
    if n.idc is None:
        return Node(ch=alias.get(n.ch, n.ch))
    return Node(idc=n.idc, kids=tuple(_norm(k, alias) for k in n.kids))


def _opens(n: Node, table: dict, alias: dict) -> list[Node]:
    """把一个结点「打开一层」：叶子换成它在 ids_lv1 里的各种拆法；内部结点打开某个叶子孩子并压平同向嵌套。"""
    out: list[Node] = []
    if n.idc is None:
        for seq in table.get(n.ch, []):
            try:
                out.append(_norm(parse(seq), alias))
            except (ValueError, IndexError):
                pass
        return out
    for i, k in enumerate(n.kids):
        if k.idc is None:
            for alt in _opens(k, table, alias):
                kids = list(n.kids)
                kids[i] = alt
                out.append(_flatten(n.idc, kids))
    return out


def _align(nodes: list[Node], table: dict | None = None, alias: dict | None = None, budget: int = 0) -> Slot:
    texts = [str(n) for n in nodes]
    if len(set(texts)) == 1:
        return Slot(True, text=texts[0])
    opts = tuple(zip(range(len(nodes)), texts))
    idcs = {n.idc for n in nodes}
    if len(idcs) == 1 and None not in idcs and len({len(n.kids) for n in nodes}) == 1:
        idc = next(iter(idcs))
        sub = tuple(_align([n.kids[i] for n in nodes], table, alias, budget) for i in range(len(nodes[0].kids)))
        return Slot(False, options=opts, sub=sub, idc=idc)
    if budget > 0 and table is not None:
        # 结构对不上：以第一个字为基准，其余各字各自打开一层（含不打开），取与基准对齐判别位置最少的写法，再整体对齐
        base = nodes[0]
        chosen = [base]
        for n in nodes[1:]:
            best: tuple | None = None
            seen = set()
            for v in [n] + _opens(n, table, alias or {}):
                if str(v) in seen:
                    continue
                seen.add(str(v))
                for bv in [base] + _opens(base, table, alias or {}):
                    sl = _align([bv, v], table, alias, 0)
                    if sl.same or sl.sub:
                        key = (_cost(sl), 0 if str(v) == str(n) else 1)
                        if best is None or key < best[0]:
                            best = (key, v, bv)
            chosen.append(best[1] if best else n)
            if best and str(best[2]) != str(base):
                base = best[2]; chosen[0] = base
        if [str(c) for c in chosen] != texts:
            slot = _align(chosen, table, alias, budget - 1)
            if slot.same or slot.sub:
                return Slot(False, options=opts, sub=slot.sub, idc=slot.idc) if slot.sub else slot
    return Slot(False, options=opts)


def _cost(s: Slot) -> tuple:
    """越小越好：(判别叶子数, 不能再对齐的位置数)。"""
    if s.same:
        return (0, 0)
    if not s.sub:
        return (1, 1)
    c = [_cost(k) for k in s.sub]
    return (sum(a for a, _ in c), sum(b for _, b in c))


def _own_ids(group_dir: Path | str | None) -> dict:
    """组目录 `ids_override.tsv` 里的 `ids<TAB>字<TAB>IDS<TAB>理由` 行：ids_lv1 太粗分不出的字，给更细的组内 IDS（覆盖字表）。"""
    out: dict[str, list[str]] = {}
    f = Path(group_dir) / "ids_fine.tsv" if group_dir else None
    if f is not None and f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0] == "ids":
                out.setdefault(parts[1], []).append(parts[2])
    return out


def _tree_of(ch: str, table: dict, alias: dict) -> list[Node]:
    out = []
    for seq in table.get(ch, []):
        try:
            out.append(_norm(parse(seq), alias))
        except (ValueError, IndexError):
            continue
    return out or [Node(ch=alias.get(ch, ch))]


def derive_plan(members: str, group_dir: Path | str | None = None, table: dict | None = None, budget: int = 2) -> Plan:
    """成员串（如 `叙敘`）→ 切分计划。`group_dir` 给了就读它的 `ids_override.tsv` 的 `alias`。"""
    table = table if table is not None else load_table()
    alias = load_override(Path(group_dir))["alias"] if group_dir else {}
    members = [m for m in members]
    own = _own_ids(group_dir)
    cands = [_tree_of(m, {**table, **own}, alias) for m in members]
    best: tuple | None = None
    for combo in product(*cands):
        slot = _align(list(combo), table, alias, budget)
        # 根结构符一致优先，其次判别位置少
        key = (0 if (not slot.same and slot.sub) or slot.same else 1, _cost(slot))
        if best is None or key < best[0]:
            best = (key, slot, combo)
    _, root, combo = best
    picks = {m: str(n) for m, n in zip(members, combo)}
    if root.same:
        return Plan("same", root=root, picks=picks)
    if not root.sub:
        return Plan("whole", root=root, picks=picks)
    diff = tuple(i for i, k in enumerate(root.sub) if not k.same)
    orient = ORIENT.get(root.idc, "")
    if not orient:
        return Plan("whole", idc=root.idc, arity=len(root.sub), diff=diff, root=root, picks=picks)
    parts = [("{}" if not k.same else k.text) for k in root.sub]
    return Plan("split", idc=root.idc, orient=orient, arity=len(root.sub), diff=diff, root=root, picks=picks,
                frame=root.idc + "".join(parts))


def diff_leaves(plan: Plan) -> list[tuple]:
    """所有判别叶子：`[(路径, {字: 部件串}), …]`。路径是从根往下的位置序号，如彝的中段右半是 `(1, 1)`。
    只在 `split` 计划里有意义；每个叶子要认的是「这个位置上各字的部件」。"""
    if plan.mode != "split":
        return []
    names = list(plan.picks)
    out: list[tuple] = []

    def rec(slot: Slot, path: tuple) -> None:
        if slot.same:
            return
        if not slot.sub:
            out.append((path, {names[i]: t for i, t in slot.options}))
            return
        for i, k in enumerate(slot.sub):
            rec(k, path + (i,))

    rec(plan.root, ())
    return out
