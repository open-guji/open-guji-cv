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


# ── 形近对表（overview#128，2026-09-28）──────────────────────────────
"""
从 IDS 拆分离线生成「形近对」候选表，供审卡标「存在形近字」与放行影子评测用
（**不接进放行判定**，见任务卡）。

⚠️ **别跟 `clustering/confusables.py` 混了**：那份（`config/ids/confusable_pairs_v1.tsv`，
2026-09-22 建，IDS 关系 + **字体模板 embedding 余弦** + 纯视觉近邻三路合成，19,732 条边，
已接进 `rare_panel` 的 `near` 字段与控制台「按形聚类分组」）已经在生产环境跑着，
本卡开工时才发现——写域检查时踩到文件名撞车，已确认没有覆盖到那份文件（改动前
`git checkout` 复核过）。本模块这套是**它的零训练版**：只用 IDS 结构，不需要
字体渲染或 embedding 模型，数据文件是另一个名字（`ids_confusable_pairs_v1.tsv`），
**没有接入 `rare_panel`/控制台**，两套并存，谁用哪套、要不要合并交协调者裁定
（见任务卡评论区的 ask）。三类对，判据都建在上面的结构/槽位之上：

1. **slot**（只差一个槽）：两字顶层结构、二层结构码、槽位路径集合全同，
   恰好一个槽的叶部件不同（K=20 口径，与 `structure_of` 默认一致）。
   score = (槽数-1)/槽数——槽数越多，共享的骨架占比越高。
   ⚠️ **实测发现**：⿰/⿱ 两槽结构占了绝大多数真实 confusable 对，score 恒为
   0.5——**score 本身在这个档位没有区分力**（申/中、宇/字、冶/治、馭/取、
   澤/擇、河/何、猶/獨……全部卡在 0.5，overview#128 任务卡评论区实测）。
   但**共享部件的一级频次**（`first_level_freq`）有区分力：2 槽真错例
   共享的都是冷僻声旁（治/冶 共享「台」频次 119、澤/擇 共享「睪」频次 61、
   河/何 共享「可」频次 134，全在全表后 10% 分位），而 氵/亻/木 这类高频
   形旁共享几乎不提供信息——这是**谐声偏旁混淆**的经典模式（同声旁、
   换形旁）。`slot1_pairs`/`build_confusable_pairs` 的 `max_shared_freq`
   参数按这条门槛筛：8,909 字宇宙上取 1000 能把全表从 448,659 压到
   61,376（**降 86.3%**），`scripts/eval_confusable_recall.py` 校准集
   18 对真错例的加权召回**一个百分点不掉**（53.3%，与不设门槛的全量相同）——
   随仓库提交的 `config/ids/ids_confusable_pairs_v1.tsv` **就是这个 1000 门槛档**
   （`build_confusable_pairs.py` 的默认值）；要全量不过滤，传
   `--max-shared-freq -1`。
   另一个筛选杠杆是**字表范围**（见 `scripts/build_confusable_pairs.py`
   只在「整理本 ∪ 各书库字种」8,909 字上生成，不是全量 10 万字表）。
2. **sameleaf**（部件相同，位置不同）：K=20 叶部件多重集完全相同、但顶层结构
   码不同。样本很少（8,909 字全表仅 96 对），score 定死 0.9。
3. **atom1**（差一个笔画级原子）：把两字都强制展开到**笔画级原子**
   （`k=ATOM_K`，停集规则失效、除非碰到 `_is_atomic` 或深度上限），
   多重集恰好相差一个原子（较大的那个 = 较小的 + 1 个原子）。
   score = n/(n+1)，n=较小侧的原子数。**这是唯一接住「加/减一笔」这类对的
   类型**——玉/王（+丶）、天/大（+一）都是 slot 接不住、atom1 才接得住的
   （K=20 口径下玉的主拆法与王完全对不上槽位，见任务卡评论区诊断）。

**已知接不住的**（实测记录，别重踩）：
- **纯原子字之间**（己/已/巳、人/入）：这几个字本身在 `ids_lv1.txt` 里就是
  独体（无 IDS 可拆），三类判据全部失效——这是 IDS 方法论本身的天花板，
  不是参数没调对。己已巳这族项目里已经在用文意判据（`utils/ji_yi_si.py`），
  不指望这张表。
- **纯字样/刻工差异**（以→取 135 次实测最大宗错例）：两字部件与结构毫无
  关联，这类错来自「同一本书里同一个字被借库模板系统性认成另一个字」
  （刻工写法差异，非几何形近），结构方法救不了，属于借库/自举那条线的问题
  （overview#86），不是本卡该覆盖的范围。
- **原子距离恰好为 2**（仕/士：仕 = 士 + 亻，亻 本身是 2 个原子 丿+丨）、
  **同原子数但多处替换**（平/乎：5 个原子里 2 处不同）：本卡判据严格卡在
  "恰好 1 个"，这两个不含糊地落在范围外，按 N2 文档定义（差一个笔画级原子）
  不该扩大。

数据文件：`config/ids/ids_confusable_pairs_v1.tsv`（`build_confusable_pairs.py` 生成，
指纹用文件内容哈希，跟 `components_v1.tsv` 一个模式）。
"""

ATOM_K = 1_000_000     # 强制展开到笔画级原子：随便一个远超任何 first_level_freq 的数
CONFUSABLE_FILE = _CFG / "ids" / "ids_confusable_pairs_v1.tsv"


@dataclass(frozen=True)
class ConfusablePair:
    a: str
    b: str
    kind: str          # "slot" | "sameleaf" | "atom1"
    score: float
    detail: str         # 人读的差异说明


def leaf_multiset(ch: str, k: int = DEFAULT_K, path: str | None = None) -> Counter:
    """按槽位取叶部件的多重集（与 `Structure.leaves` 不同——那个去重，这里保留重复，
    例如同一部件在两个槽位各出现一次时要记两次）。"""
    return Counter(c for _, c in structure_of(ch, k, path).slots)


def atom_multiset(ch: str, path: str | None = None) -> Counter:
    """笔画级原子多重集（`k=ATOM_K` 的 `leaf_multiset`）。给 atom1 类用。"""
    return leaf_multiset(ch, ATOM_K, path)


def _skeleton(st: Structure) -> tuple:
    return (st.top, st.code, tuple(p for p, _ in st.slots))


def slot1_pairs(chars: Iterable[str], k: int = DEFAULT_K,
                path: str | None = None,
                max_shared_freq: int | None = None) -> dict[tuple[str, str], ConfusablePair]:
    """同结构、恰好一个槽的叶部件不同。用「遮住第 j 槽」当桶键的通配技巧，
    避免 O(n²) 两两比较——桶内候选数天然只有几个到几十个。

    `max_shared_freq`：**只对 2 槽结构生效**的门槛（⿰/⿱ 那 99.8%）。2 槽时
    「共享的那个部件」是唯一没变的东西，它作为一级部件出现得越频繁
    （`first_level_freq`，比如 氵/亻/木 这类高频形旁），这一对能提供的
    「共享部件长得像」信息量反而越低——真正的形近对多半是**共享冷僻的声旁、
    只在形旁上不同**（诸声字混淆：治/冶 共享「台」、澤/擇 共享「睪」、
    河/何 共享「可」——这三对共享部件的一级频次分别只有 119/61/134，全在
    全表后 10% 分位）。实测（overview#128 任务卡评论区）：8,909 字宇宙上
    7 个已确认的 2 槽真错例，共享部件频次全部 ≤984，取门槛 1000 能把
    443,078 条 2 槽候选压到 54,903 条（12.4%），**7 个真例一个不丢**
    （`scripts/eval_confusable_recall.py` 实测）。
    `None`＝不过滤（原始全量，`build_confusable_pairs` 缺省用这个）。
    ≥3 槽的结构（如 令/今）不受此参数影响——那部分只有几百条，且真例的
    共享部件本身也很常见，用同一把尺子会把它们筛掉。
    """
    chars = list(dict.fromkeys(chars))
    struct = {ch: structure_of(ch, k, path) for ch in chars}
    freq = first_level_freq(path) if max_shared_freq is not None else None
    buckets: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
    for ch, st in struct.items():
        n = len(st.slots)
        if n < 2:
            continue
        sk = _skeleton(st)
        leaves_seq = tuple(c for _, c in st.slots)
        for j in range(n):
            if n == 2 and freq is not None:
                shared = leaves_seq[1 - j]
                if freq.get(shared, 0) > max_shared_freq:
                    continue
            masked = sk + leaves_seq[:j] + ("*",) + leaves_seq[j + 1:]
            buckets[masked].append((ch, leaves_seq[j]))

    out: dict[tuple[str, str], ConfusablePair] = {}
    for key, items in buckets.items():
        if len(items) < 2:
            continue
        by_leaf: dict[str, list[str]] = defaultdict(list)
        for ch, leaf in items:
            by_leaf[leaf].append(ch)
        leaves = list(by_leaf)
        if len(leaves) < 2:
            continue
        n_slots = len(struct[items[0][0]].slots)
        score = (n_slots - 1) / n_slots
        for i in range(len(leaves)):
            for j in range(i + 1, len(leaves)):
                for a in by_leaf[leaves[i]]:
                    for b in by_leaf[leaves[j]]:
                        if a == b:
                            continue
                        pair = (a, b) if a < b else (b, a)
                        detail = f"槽位差: {leaves[i]}/{leaves[j]}"
                        prev = out.get(pair)
                        if prev is None or score > prev.score:
                            out[pair] = ConfusablePair(pair[0], pair[1], "slot", score, detail)
    return out


def sameleaf_pairs(chars: Iterable[str], k: int = DEFAULT_K,
                   path: str | None = None) -> dict[tuple[str, str], ConfusablePair]:
    """叶部件多重集完全相同、顶层结构不同（部件相同、位置或组合方式不同）。"""
    chars = list(dict.fromkeys(chars))
    struct = {ch: structure_of(ch, k, path) for ch in chars}
    groups: dict[tuple, list[str]] = defaultdict(list)
    for ch, st in struct.items():
        if len(st.slots) < 2:
            continue
        key = tuple(sorted(Counter(c for _, c in st.slots).items()))
        groups[key].append(ch)

    out: dict[tuple[str, str], ConfusablePair] = {}
    for key, items in groups.items():
        if len(items) < 2:
            continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if struct[a].top == struct[b].top and struct[a].code == struct[b].code:
                    continue    # 结构也相同：不是这一类要抓的对象
                pair = (a, b) if a < b else (b, a)
                detail = f"同部件不同结构: {struct[a].code}/{struct[b].code}"
                out[pair] = ConfusablePair(pair[0], pair[1], "sameleaf", 0.9, detail)
    return out


def atom1_pairs(chars: Iterable[str],
                path: str | None = None) -> dict[tuple[str, str], ConfusablePair]:
    """笔画级原子多重集恰好相差一个原子（较大的 = 较小的 + 1 个原子）。

    做法：每个字生成「去掉其中一个原子实例」的全部归约签名（同值原子只留一份，
    去重避免重复配对）；归约签名若恰好等于另一个字的**完整**签名，两者即一对，
    「去掉的那个原子」就是差异。比两两比较快得多——大字表也能几秒内跑完。
    """
    chars = list(dict.fromkeys(chars))
    atoms = {ch: atom_multiset(ch, path) for ch in chars}

    def sig(cnt: Counter) -> tuple:
        return tuple(sorted(cnt.items()))

    full_map: dict[tuple, list[str]] = defaultdict(list)
    for ch, cnt in atoms.items():
        full_map[sig(cnt)].append(ch)

    reduced_map: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
    for ch, cnt in atoms.items():
        for atom in set(cnt):
            rc = Counter(cnt)
            rc[atom] -= 1
            if rc[atom] <= 0:
                del rc[atom]
            reduced_map[sig(rc)].append((ch, atom))

    out: dict[tuple[str, str], ConfusablePair] = {}
    for key, reduced_items in reduced_map.items():
        smaller = full_map.get(key, [])
        if not smaller:
            continue
        n = sum(c for _, c in key)
        score = n / (n + 1) if n > 0 else 0.5
        for big_ch, removed_atom in reduced_items:
            for small_ch in smaller:
                if big_ch == small_ch:
                    continue
                pair = (big_ch, small_ch) if big_ch < small_ch else (small_ch, big_ch)
                detail = f"多一个原子: {removed_atom}"
                prev = out.get(pair)
                if prev is None or score > prev.score:
                    out[pair] = ConfusablePair(pair[0], pair[1], "atom1", score, detail)
    return out


def build_confusable_pairs(chars: Iterable[str], k: int = DEFAULT_K,
                           path: str | None = None,
                           max_shared_freq: int | None = None) -> list[ConfusablePair]:
    """三类合并；同一对多类命中时只留分最高的一条。按分数降序、字典序返回。

    `max_shared_freq` 透传给 `slot1_pairs`（见其文档串）——2 槽结构的共享
    部件门槛，不影响 sameleaf/atom1。"""
    chars = list(dict.fromkeys(chars))
    merged: dict[tuple[str, str], ConfusablePair] = {}
    for pair, cp in slot1_pairs(chars, k, path, max_shared_freq).items():
        merged[pair] = cp
    for pair, cp in sameleaf_pairs(chars, k, path).items():
        prev = merged.get(pair)
        if prev is None or cp.score > prev.score:
            merged[pair] = cp
    for pair, cp in atom1_pairs(chars, path).items():
        prev = merged.get(pair)
        if prev is None or cp.score > prev.score:
            merged[pair] = cp
    return sorted(merged.values(), key=lambda p: (-p.score, p.a, p.b))


def write_confusable_pairs(pairs: Iterable[ConfusablePair],
                           out: Path = CONFUSABLE_FILE) -> Path:
    lines = ["# ids_confusable_pairs_v1  source=ids_lv1.txt  "
             "columns: a\\tb\\tkind\\tscore\\tdetail"]
    for p in pairs:
        lines.append(f"{p.a}\t{p.b}\t{p.kind}\t{p.score:.4f}\t{p.detail}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


@lru_cache(maxsize=1)
def load_confusable_pairs(path: str | None = None) -> dict[frozenset, ConfusablePair]:
    """→ {frozenset({a,b}): ConfusablePair}。文件不存在时返回空表（`is_confusable`
    因此缺省关闭，不报错——与 `load_vocab` 对空文件的处理一致）。"""
    p = Path(path) if path else CONFUSABLE_FILE
    out: dict[frozenset, ConfusablePair] = {}
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split("\t")
        if len(parts) < 5:
            continue
        a, b, kind, score, detail = parts[0], parts[1], parts[2], parts[3], parts[4]
        out[frozenset((a, b))] = ConfusablePair(a, b, kind, float(score), detail)
    return out


def is_confusable(a: str, b: str, path: str | None = None) -> bool:
    """`a`、`b` 是否在形近对表里。**只供审卡标记与影子评测**，不接进放行判定
    （见任务卡边界）。"""
    if a == b:
        return False
    return frozenset((a, b)) in load_confusable_pairs(path)


def confusable_detail(a: str, b: str, path: str | None = None) -> ConfusablePair | None:
    """同 `is_confusable`，命中时把 `ConfusablePair`（含 kind/score/detail）一并给出，
    供审卡界面拼「差在右槽 X/Y」这类提示语。"""
    if a == b:
        return None
    return load_confusable_pairs(path).get(frozenset((a, b)))


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
