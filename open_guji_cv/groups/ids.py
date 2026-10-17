"""字组的 IDS 展开（M7 块 A，GUJI-563）：把组内每个成员递归展开到「停止点」，再同向压平。

- 数据：`config/ids/ids_lv1.txt`（yi-bai/ids，MIT，已在仓里，`ids_guard` 也读它）；
  一个字可有多个写法（分号分隔，如 𢑱 的 ⿱𫜹𡙢 / ⿱彑𡙢），**全部保留**，各自展开。
- 展开到哪停：组配置 `config/groups/<组>/ids_override.tsv` 的 `stop` 行（该组各位置的可选部件）。
  不在停止点里的复合字继续展开（𪪷 → ⿱粉廾，粉 → ⿰米分）；碰到无 IDS 的原子字就停。
- 压平：同向嵌套 ⿱ 合并成 ⿳、⿰ 合并成 ⿲（彜 ⿱彑⿱粉廾 → ⿳彑⿰米分廾）。
- 本模块不被任何 Step 引用，不在 `code_deps` 里。分层 L2，只依赖标准库。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from pathlib import Path

_CFG = Path(__file__).resolve().parents[2] / "config"
IDS_TABLE = _CFG / "ids" / "ids_lv1.txt"
_REGION = re.compile(r"\([^)]*\)")
ARITY = {c: 2 for c in "⿰⿱⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿"}
ARITY.update({"⿲": 3, "⿳": 3})


@dataclass(frozen=True)
class Node:
    """IDS 树：叶子 `idc=None`、`ch` 是部件；内部结点 `idc` + `kids`。"""
    idc: str | None = None
    ch: str = ""
    kids: tuple = ()

    def __str__(self) -> str:
        return self.ch if self.idc is None else self.idc + "".join(str(k) for k in self.kids)


@lru_cache(maxsize=1)
def load_table(path: str = str(IDS_TABLE)) -> dict:
    """char → [写法, …]（去地区标记；跳过 `#(` 笔画组合和 `{x}` 自指项）。"""
    out: dict[str, list[str]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line or "\t" not in line:
            continue
        ch, rest = line.split("\t", 1)
        seqs = []
        for field in rest.split("\t"):
            for seq in field.split(";"):
                seq = _REGION.sub("", seq).strip()
                if seq and not seq.startswith("#") and not seq.startswith("{"):
                    seqs.append(seq)
        if seqs:
            out[ch] = seqs
    return out


def parse(seq: str) -> Node:
    """前缀式 IDS 串 → 树。"""
    chars = list(seq)
    pos = 0

    def rec() -> Node:
        nonlocal pos
        c = chars[pos]
        pos += 1
        n = ARITY.get(c)
        if n is None:
            return Node(ch=c)
        return Node(idc=c, kids=tuple(rec() for _ in range(n)))

    node = rec()
    if pos != len(chars):
        raise ValueError(f"IDS 串多余字符: {seq!r}")
    return node


def load_override(group_dir: Path) -> dict:
    """读 `ids_override.tsv`：`stop`（集合）和 `alias`（字典）。"""
    stop: set[str] = set(); alias: dict[str, str] = {}
    f = group_dir / "ids_override.tsv"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if parts[0] == "stop":
                stop.add(parts[1])
            elif parts[0] == "alias":
                alias[parts[1]] = parts[2]
    return {"stop": stop, "alias": alias}


def _flatten(idc: str, kids: list[Node]) -> Node:
    """同向嵌套压平：⿱ 里嵌 ⿱ → ⿳；⿰ 里嵌 ⿰ → ⿲（只压平两分结构，三分结构不再并）。"""
    three = {"⿱": "⿳", "⿰": "⿲"}
    if idc in three:
        flat: list[Node] = []
        for k in kids:
            if k.idc == idc:
                flat.extend(k.kids)
            else:
                flat.append(k)
        if len(flat) == 3:
            return Node(idc=three[idc], kids=tuple(flat))
        if len(flat) == 2:
            return Node(idc=idc, kids=tuple(flat))
    return Node(idc=idc, kids=tuple(kids))


def _expand_leaf(ch: str, stop: set, alias: dict, table: dict, depth: int) -> list[Node]:
    ch = alias.get(ch, ch)
    if ch in stop or depth > 6 or ch not in table:
        return [Node(ch=ch)]
    out: list[Node] = []
    for seq in table[ch]:
        try:
            tree = parse(seq)
        except (ValueError, IndexError):
            continue
        out.extend(_expand_tree(tree, stop, alias, table, depth + 1))
    return out or [Node(ch=ch)]


def _expand_tree(tree: Node, stop: set, alias: dict, table: dict, depth: int) -> list[Node]:
    if tree.idc is None:
        return _expand_leaf(tree.ch, stop, alias, table, depth)
    options = [_expand_tree(k, stop, alias, table, depth) for k in tree.kids]
    return [_flatten(tree.idc, list(combo)) for combo in product(*options)]


def expand(ch: str, stop: set, alias: dict | None = None, table: dict | None = None) -> list[Node]:
    """一个字的全部展开写法（去重，保持顺序）。无 IDS 的字返回单叶子。"""
    table = table if table is not None else load_table()
    alias = alias or {}
    seen: dict[str, Node] = {}
    for n in _expand_leaf(ch, set(stop) - {ch}, alias, table, 0):
        seen.setdefault(str(n), n)
    return list(seen.values())


def group_structures(members, group_dir: Path | str, table: dict | None = None) -> dict:
    """组内每个成员的展开写法。返回 `{字: [IDS 串, …]}`。"""
    ov = load_override(Path(group_dir))
    return {m: [str(n) for n in expand(m, ov["stop"], ov["alias"], table)] for m in members}


def slot_options(structs: dict, idc: str) -> list[set]:
    """在同一个顶层结构 `idc` 下按位对齐，求每个位置上出现过的部件集合（叶子才计；复合部件用其串）。"""
    cols: list[set] = []
    for seqs in structs.values():
        for s in seqs:
            n = parse(s)
            if n.idc != idc:
                continue
            for i, k in enumerate(n.kids):
                while len(cols) <= i:
                    cols.append(set())
                cols[i].add(str(k))
    return cols
