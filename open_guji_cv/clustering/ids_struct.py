# -*- coding: utf-8 -*-
"""IDS 结构层：拆字表 → 结构码 + 槽位部件 + 倒排索引 + 部件一致性打分。

`structure_aware_recognition_design.md` 第二部分 M0 的第一块（2026-09-21）。
`ids_guard.py` 只把 IDS 当**护栏**（比两个候选差几个部件）；这里把它当**表示**：
每个字 → (顶层结构、二层结构码、槽位 → 叶部件)，并反过来建索引，让
「⿰ 言 ?」这种查询能取回字集，让候选能按「它的部件被预测存在了吗」重排。

## 三个口径，先记死

1. **主拆法**：yi-bai 表一行可有多种写法 `;` 分隔，每种后带地区码 `(.,T,J…)`。
   取**含 `T`（台湾正体）的第一种**，其次含 `.` 的，再其次第一种——刻本是传承字形。
   其余写法保留在 `alts`，训练时当正例集合，不当负例。
2. **停集展开**（K=20）：一级部件 11,527 个太碎、全递归到底只剩 163 个笔画级原子
   太细。规则：部件若「作为一级部件出现在 ≥K 个字里」就是叶，否则用它自己的主拆法
   继续拆，拆到叶或原子（无 IDS / `#(...)` 笔画式 / `{…}` 无码）为止。
   K=20 → 1,700 个叶部件（停集 1,598 / 笔画式 81 / 原子 21），每字 2 个 61% / 3 个 28%。
   词表落盘 `config/ids/components_v1.tsv`，`vocab_fingerprint()` 供指纹用。
3. **槽位**：顶层算符定槽名（⿰ L/R、⿱ T/B、⿲ L/M/R、⿳ T/M/B、包围类 O/I、⿻ A/B、
   ⿾⿿ 单槽 X）；子树再套一层用 `.` 连成路径（`R.T`）。停集展开会把子树拼进来，
   所以路径可能到三层；索引同时按**完整路径**与**顶层槽**建，查询一般只用顶层槽。

## 不做什么

- 不碰 `ids_guard`：护栏那套「一级部件 + 结构串」口径与 `NEVER_MATCH` 表绑在一起，
  重排/检索用新口径，两边各自成立。
- 不接进 `rare_panel` 的 RRF：`component_consistency` 只是函数，**接线要等靶子**
  （oov_bench / 北行 383）量过 top-1/top-10 不掉才动，见设计稿 §11 #3。
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable

_CFG = Path(__file__).resolve().parent.parent.parent / "config"
IDS_TABLE = _CFG / "ids" / "ids_lv1.txt"
VOCAB_FILE = _CFG / "ids" / "components_v1.tsv"

#: 表意文字描述字符 → 元数（几个子节点）。⿾⿿ 是镜像/旋转，单目；㇯ 是「减笔」，双目。
IDC_ARITY: dict[str, int] = {
    "⿰": 2, "⿱": 2, "⿲": 3, "⿳": 3, "⿴": 2, "⿵": 2, "⿶": 2, "⿷": 2,
    "⿸": 2, "⿹": 2, "⿺": 2, "⿻": 2, "⿼": 2, "⿽": 2, "⿾": 1, "⿿": 1, "㇯": 2,
}
IDC = set(IDC_ARITY)

#: 顶层算符 → 槽名。包围类一律 O（外）/ I（内），查询时不必分清是哪一种包围。
SLOT_NAMES: dict[str, tuple[str, ...]] = {
    "⿰": ("L", "R"), "⿱": ("T", "B"), "⿲": ("L", "M", "R"), "⿳": ("T", "M", "B"),
    "⿴": ("O", "I"), "⿵": ("O", "I"), "⿶": ("O", "I"), "⿷": ("O", "I"),
    "⿸": ("O", "I"), "⿹": ("O", "I"), "⿺": ("O", "I"), "⿼": ("O", "I"), "⿽": ("O", "I"),
    "⿻": ("A", "B"), "⿾": ("X",), "⿿": ("X",), "㇯": ("A", "B"),
}

#: 二层结构码只对这四个算符展开（⿰⿱ 4,032 字、⿱⿰ 1,527…），包围类的内部再拆
#: 视觉上没有稳定的方位，截断。
SECOND_LEVEL_OPS = ("⿰", "⿱", "⿲", "⿳")

DEFAULT_K = 20
STROKE_ONLY = "#"          # `#(H)(.)` 笔画式 = 独体，没有部件可拆
SINGLE = "独体"             # 结构码：独体 / 无 IDS


# ── 解析 ────────────────────────────────────────────────────────────────

@dataclass
class Node:
    """IDS 树节点：`op` 为 None 时是叶（`comp` 是部件字或 `{无码}`）。"""
    op: str | None = None
    comp: str = ""
    kids: list["Node"] = field(default_factory=list)

    @property
    def leaf(self) -> bool:
        return self.op is None

    def leaves(self) -> list[str]:
        return [self.comp] if self.leaf else [x for k in self.kids for x in k.leaves()]


def tokenize(seq: str) -> list[str]:
    """按 yi-bai 表的语法切 token：

    - `{…}` 无码部件 / 形体标注 → 一个 token；
    - `#(…)` 笔画式部件（如 `#(H)`、`#(-丿乀)`）→ 一个 token；裸 `#` 也算一个；
    - `[…]` 是 ⿻ 的重叠细节修饰（`⿻[1:]亅…`、`⿻[l,l,.]勹巳`），**跳过**；
    - 其余按字符。
    """
    out, i = [], 0
    while i < len(seq):
        c = seq[i]
        if c == "{":
            j = seq.find("}", i)
            if j < 0:
                out.append(seq[i:]); break
            out.append(seq[i:j + 1]); i = j + 1
        elif c == "#" and i + 1 < len(seq) and seq[i + 1] == "(":
            j = seq.find(")", i)
            if j < 0:
                out.append(seq[i:]); break
            out.append(seq[i:j + 1]); i = j + 1
        elif c == "[":
            j = seq.find("]", i)
            i = len(seq) if j < 0 else j + 1
        else:
            out.append(c); i += 1
    return out


def parse_ids(seq: str) -> Node | None:
    """前缀式 IDS → 树；多余/不足 token 一律返回 None（不猜）。"""
    toks = tokenize(seq.strip())
    if not toks:
        return None
    # 行首 `{丗}⿱卅一`：花括号是「这个形体」的标注，不是部件——后面能解析成完整树就丢掉它
    if len(toks) > 1 and toks[0].startswith("{") and toks[1] in IDC:
        inner = parse_ids("".join(toks[1:]))
        if inner is not None:
            return inner
    pos = 0

    def rec() -> Node | None:
        nonlocal pos
        if pos >= len(toks):
            return None
        t = toks[pos]; pos += 1
        if t in IDC:
            kids = []
            for _ in range(IDC_ARITY[t]):
                k = rec()
                if k is None:
                    return None
                kids.append(k)
            return Node(op=t, kids=kids)
        return Node(comp=t)

    root = rec()
    return root if (root is not None and pos == len(toks)) else None


def _split_alternatives(raw: str) -> list[tuple[str, set[str]]]:
    """`⿰言俞(.,T,J);⿰言兪(K)` → [(seq, {regions})…]。没括号的地区集为空。"""
    out = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        regions: set[str] = set()
        # 只剥**末尾**那一组括号当地区码：`#(H)(.)` 里 `(H)` 是笔画码，属于序列本身。
        # 末尾一组的内容若含 IDC/汉字（如整行没标地区、以 `#(-丿乀)` 收尾），则不是地区码，不剥。
        if part.endswith(")") and "(" in part:
            i = part.rindex("(")
            body = part[i + 1:-1]
            if body and all(ch.isascii() or ch == "." for ch in body):
                regions = {r.strip() for r in body.split(",") if r.strip()}
                part = part[:i]
        out.append((part, regions))
    return out


def pick_primary(alts: list[tuple[str, set[str]]]) -> str:
    """主拆法：含 T 的第一种 > 含 `.` 的第一种 > 第一种。"""
    for want in ("T", "."):
        for seq, regs in alts:
            if want in regs:
                return seq
    return alts[0][0] if alts else ""


@dataclass
class Entry:
    char: str
    primary: str                 # 主拆法（原始序列，可能是 `#...` 或自身）
    alts: tuple[str, ...]        # 全部写法（含主拆法），去重保序


@lru_cache(maxsize=2)
def load_table(path: str | None = None) -> dict[str, Entry]:
    p = Path(path) if path else IDS_TABLE
    out: dict[str, Entry] = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split("\t")
        if len(parts) < 2:
            continue
        ch = parts[0]
        alts = _split_alternatives(parts[1])
        # 第三列起偶有额外写法（无地区码）
        for extra in parts[2:]:
            alts += _split_alternatives(extra)
        seqs: list[str] = []
        for s, _ in alts:
            if s and s not in seqs:
                seqs.append(s)
        if not seqs:
            continue
        out[ch] = Entry(char=ch, primary=pick_primary(alts), alts=tuple(seqs))
    return out


def _is_atomic(seq: str, ch: str) -> bool:
    """笔画式、自指、无码：不能再拆。行首的 `{形体标注}` 先剥掉再看（`{卩}#(-丨𠃌)`）。"""
    if seq.startswith("{") and "}" in seq:
        seq = seq[seq.index("}") + 1:]
    return (not seq) or seq.startswith(STROKE_ONLY) or seq == ch or ch.startswith("{")


# ── 停集词表 ──────────────────────────────────────────────────────────

@lru_cache(maxsize=2)
def first_level_freq(path: str | None = None) -> Counter:
    """每个部件作为**一级部件**出现在多少个字里（主拆法口径）。停集判据用它。"""
    cnt: Counter = Counter()
    for e in load_table(path).values():
        if _is_atomic(e.primary, e.char):
            continue
        cnt.update({t for t in tokenize(e.primary) if t not in IDC})
    return cnt


def expand(ch: str, k: int = DEFAULT_K, path: str | None = None,
           _depth: int = 0) -> Node | None:
    """主拆法的树，子部件按停集规则继续拆到叶。独体/无 IDS 返回单叶节点。"""
    tab = load_table(path)
    e = tab.get(ch)
    if e is None or _is_atomic(e.primary, ch):
        return Node(comp=ch)
    root = parse_ids(e.primary)
    if root is None:
        return Node(comp=ch)
    freq = first_level_freq(path)

    def grow(n: Node, depth: int) -> Node:
        if not n.leaf:
            return Node(op=n.op, kids=[grow(x, depth) for x in n.kids])
        t = n.comp
        if freq.get(t, 0) >= k or depth >= 6 or t == ch:
            return n
        sub = tab.get(t)
        if sub is None or _is_atomic(sub.primary, t):
            return n
        subtree = parse_ids(sub.primary)
        if subtree is None:
            return n
        return grow(subtree, depth + 1)

    return grow(root, _depth)


def build_vocab(k: int = DEFAULT_K, path: str | None = None) -> list[tuple[str, int, str]]:
    """[(部件, 被多少字用到, 类别)]，类别 ∈ {stop, atom, unencoded}。"""
    tab = load_table(path)
    freq = first_level_freq(path)
    used: Counter = Counter()
    for ch, e in tab.items():
        if _is_atomic(e.primary, ch):
            continue
        t = expand(ch, k, path)
        if t is not None:
            used.update(set(t.leaves()))
    rows = []
    for comp, n in sorted(used.items(), key=lambda kv: (-kv[1], kv[0])):
        if comp.startswith("{"):
            kind = "unencoded"
        elif comp.startswith("#"):
            kind = "stroke"          # `#(H)` 笔画式部件：没有字形可渲染，训练时只当占位
        elif freq.get(comp, 0) >= k:
            kind = "stop"
        else:
            kind = "atom"
        rows.append((comp, n, kind))
    return rows


def write_vocab(rows: Iterable[tuple[str, int, str]], out: Path = VOCAB_FILE,
                k: int = DEFAULT_K) -> Path:
    src = hashlib.sha1(IDS_TABLE.read_bytes()).hexdigest()[:12]
    lines = [f"# components_v1  K={k}  source=ids_lv1.txt@{src}  columns: component\tn_chars\tkind"]
    lines += [f"{c}\t{n}\t{kind}" for c, n, kind in rows]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


@lru_cache(maxsize=1)
def load_vocab(path: str | None = None) -> dict[str, tuple[int, str]]:
    p = Path(path) if path else VOCAB_FILE
    out: dict[str, tuple[int, str]] = {}
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln or ln.startswith("#"):
            continue
        c, n, kind = ln.split("\t")
        out[c] = (int(n), kind)
    return out


def vocab_fingerprint(path: str | None = None) -> str:
    """词表文件指纹；缺文件 → "novocab"。Step A 的参数要带上它。"""
    p = Path(path) if path else VOCAB_FILE
    if not p.exists():
        return "novocab"
    return hashlib.sha1(p.read_bytes()).hexdigest()[:12]


# ── 结构码与槽位 ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Structure:
    char: str
    top: str                        # 顶层算符，或 SINGLE
    code: str                       # 二层结构码，如 "⿰" / "⿰⿱"；独体为 SINGLE
    slots: tuple[tuple[str, str], ...]   # ((槽位路径, 叶部件), …)，按前缀序
    leaves: tuple[str, ...]         # 叶部件（去重保序）

    def top_slots(self) -> dict[str, tuple[str, ...]]:
        """顶层槽 → 该槽下全部叶部件。"""
        d: dict[str, list[str]] = defaultdict(list)
        for p, c in self.slots:
            d[p.split(".")[0]].append(c)
        return {s: tuple(v) for s, v in d.items()}


def _walk(n: Node, prefix: str, out: list[tuple[str, str]]) -> None:
    if n.leaf:
        out.append((prefix, n.comp)); return
    names = SLOT_NAMES[n.op]
    for name, kid in zip(names, n.kids):
        _walk(kid, f"{prefix}.{name}" if prefix else name, out)


@lru_cache(maxsize=1 << 17)
def structure_of(ch: str, k: int = DEFAULT_K, path: str | None = None) -> Structure:
    t = expand(ch, k, path)
    if t is None or t.leaf:
        return Structure(ch, SINGLE, SINGLE, ((SINGLE, ch),), (ch,))
    code = t.op
    if t.op in SECOND_LEVEL_OPS:
        for kid in t.kids:
            if not kid.leaf and kid.op in SECOND_LEVEL_OPS:
                code += kid.op
                break          # 只记第一个带二层结构的子槽，与统计口径一致
    slots: list[tuple[str, str]] = []
    _walk(t, "", slots)
    leaves: list[str] = []
    for _, c in slots:
        if c not in leaves:
            leaves.append(c)
    return Structure(ch, t.op, code, tuple(slots), tuple(leaves))


# ── 倒排索引 ──────────────────────────────────────────────────────────

class IdsIndex:
    """结构码 / 部件 / 部件@顶层槽 → 字集。全表约 10 万字，建一次 2–3 s，进程内常驻。"""

    def __init__(self, chars: Iterable[str] | None = None, k: int = DEFAULT_K,
                 path: str | None = None):
        tab = load_table(path)
        self.k = k
        self.by_top: dict[str, set[str]] = defaultdict(set)
        self.by_code: dict[str, set[str]] = defaultdict(set)
        self.by_comp: dict[str, set[str]] = defaultdict(set)
        self.by_comp_slot: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.struct: dict[str, Structure] = {}
        for ch in (chars if chars is not None else tab.keys()):
            s = structure_of(ch, k, path)
            self.struct[ch] = s
            self.by_top[s.top].add(ch)
            self.by_code[s.code].add(ch)
            for c in s.leaves:
                self.by_comp[c].add(ch)
            for slot, comps in s.top_slots().items():
                for c in comps:
                    self.by_comp_slot[(c, slot)].add(ch)

    def search(self, top: str | None = None, slots: dict[str, str] | None = None,
               components: Iterable[str] = (), within: Iterable[str] | None = None,
               limit: int = 50) -> list[tuple[str, int]]:
        """按约束打分取字：每满足一条 +1；`top` 给了就当硬过滤。
        `slots={'L': '言'}` 是「左边是言」；`components=['俞']` 是「某处有俞」。
        返回 [(字, 命中数)]，命中数降序、同分按字表序。"""
        pool: set[str] | None = set(within) if within is not None else None
        if top:
            cand = set(self.by_top.get(top, ()))
            pool = cand if pool is None else pool & cand
        score: Counter = Counter()
        for slot, comp in (slots or {}).items():
            for ch in self.by_comp_slot.get((comp, slot), ()):
                score[ch] += 1
        for comp in components:
            for ch in self.by_comp.get(comp, ()):
                score[ch] += 1
        if not score and pool is not None:
            return [(ch, 0) for ch in sorted(pool)][:limit]
        items = [(ch, n) for ch, n in score.items() if pool is None or ch in pool]
        items.sort(key=lambda t: (-t[1], t[0]))
        return items[:limit]


@lru_cache(maxsize=1)
def shared_index() -> IdsIndex:
    return IdsIndex()


# ── 部件一致性打分（M0 零训练重排的核） ──────────────────────────────

def component_consistency(cands: Iterable[str], comp_probs: dict[str, float],
                          components_of: Callable[[str], Iterable[str]] | None = None,
                          ) -> dict[str, float | None]:
    """每个候选字：它的部件里「被预测存在」的平均概率；一个部件都不在
    `comp_probs` 里的候选给 None（**不是 0**——那是「没意见」，不是「不像」）。

    `comp_probs` 来自哪个头，`components_of` 就必须用同一套口径：现役 r5 的
    部件袋头是 `ids_guard.components`（一级部件）；Step A 的槽位头是本模块的
    `structure_of(ch).leaves`。混用会把分数打到不相干的词表上。
    """
    comps_of = components_of or (lambda ch: structure_of(ch).leaves)
    out: dict[str, float | None] = {}
    for ch in cands:
        ps = [comp_probs[c] for c in comps_of(ch) if c in comp_probs]
        out[ch] = (sum(ps) / len(ps)) if ps else None
    return out


# ── Step A 的标签空间（结构头 + 槽位部件头）──────────────────────────

#: 结构头的类：17 个算符 + 独体，顺序固定（进 checkpoint 的 `struct_classes`）。
STRUCT_CLASSES: tuple[str, ...] = tuple(sorted(IDC_ARITY)) + (SINGLE,)
SINGLE_SLOT = "S"


def struct_index(ch: str, k: int = DEFAULT_K) -> int:
    """结构头的目标类下标。"""
    return STRUCT_CLASSES.index(structure_of(ch, k).top)


def slot_keys_of(ch: str, k: int = DEFAULT_K) -> tuple[str, ...]:
    """槽位部件头的目标：`部件@顶层槽`（言@L、俞@R）；独体字是 `字@S`。去重保序。

    与 `component_consistency` / `struct_rerank` 的 `components_of` 参数配套：
    槽位头的概率字典键就是这些串。
    """
    st = structure_of(ch, k)
    if st.top == SINGLE:
        return (f"{ch}@{SINGLE_SLOT}",)
    out: list[str] = []
    for slot, comps in st.top_slots().items():
        for c in comps:
            key = f"{c}@{slot}"
            if key not in out:
                out.append(key)
    return tuple(out)


def build_slot_labels(classes: Iterable[str], min_count: int = 3,
                      k: int = DEFAULT_K) -> list[str]:
    """训练类表 → 槽位标签词表：只留在 ≥min_count 个类里出现的 `部件@槽`（与现役
    部件袋头「≥3 字」同一条纪律，罕见标签学不动只添噪）。排序稳定。"""
    cnt: Counter = Counter()
    for ch in classes:
        cnt.update(set(slot_keys_of(ch, k)))
    return sorted(key for key, n in cnt.items() if n >= min_count)


#: 一致性名次表在 RRF 里的权重。**未标定**——等 `scripts/eval_struct_rerank.py`
#: 在 oov_bench / 北行 383 上扫过再定；扫之前它只在 `struct_rerank=True` 时生效。
STRUCT_RERANK_WEIGHT = 1.0
STRUCT_RERANK_TOP_M = 30      # 只在融合结果前 M 名里重排（GL-HPN：K ≥ 30 不丢召回）


def struct_rerank(order: list[str], comp_probs: dict[str, float],
                  components_of: Callable[[str], Iterable[str]] | None = None,
                  k: int = 10, weight: float = STRUCT_RERANK_WEIGHT,
                  top_m: int = STRUCT_RERANK_TOP_M) -> list[str]:
    """把融合名次表的前 `top_m` 名按部件一致性重排，返回前 `k`。

    做法：一致性分（`component_consistency`）降序排成第二份名次表（None 的不进），
    与原名次表做 RRF（原表权 1、一致性表权 `weight`）。只重排、不拦截、不改
    top_m 之外的字——它是**候选排序**信号，不是放行判据（设计稿 §4.3）。
    `comp_probs` 为空时原样返回，等于关掉。
    """
    head = list(order[:top_m])
    if not head or not comp_probs:
        return list(order[:k])
    from .cnn_candidates import rrf
    cons = component_consistency(head, comp_probs, components_of)
    ranked = sorted((ch for ch in head if cons[ch] is not None),
                    key=lambda ch: -cons[ch])
    if not ranked:
        return list(order[:k])
    fused = rrf(head, ranked, k=len(head), weights=(1.0, weight))
    # rrf 只返回有分的字；head 里每个字在原表都有分，长度不会缩。top_m 之外原样接回。
    return (fused + list(order[top_m:]))[:k]


def _main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="建停集部件词表 / 查结构")
    ap.add_argument("--build", action="store_true", help="生成 config/ids/components_v1.tsv")
    ap.add_argument("-k", type=int, default=DEFAULT_K)
    ap.add_argument("chars", nargs="*", help="打印这些字的结构码与槽位")
    a = ap.parse_args(argv)
    if a.build:
        rows = build_vocab(a.k)
        out = write_vocab(rows, k=a.k)
        kinds = Counter(kind for _, _, kind in rows)
        print(f"写入 {out}: {len(rows)} 个部件 {dict(kinds)}，指纹 {vocab_fingerprint()}")
    for ch in a.chars:
        s = structure_of(ch, a.k)
        print(ch, s.top, s.code, s.slots)
    return 0


if __name__ == "__main__":     # python -m open_guji_cv.clustering.ids_struct --build 諭 論
    import sys
    raise SystemExit(_main(sys.argv[1:]))
