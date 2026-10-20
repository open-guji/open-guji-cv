# -*- coding: utf-8 -*-
"""hanzi 库的查询（总设计 §6.3）。只读打开 sqlite，进程内常驻。

    from open_guji_cv.hanzi import HanziDB
    db = HanziDB.open()            # 按 git 里的清单 config/hanzi/manifest.json 灌本机库（同版本只灌一次）
    db.family("互")                # {字: [Edge…]}，星形一跳，剔掉人审定的 distinct
    db.pool(["歷", "注"])          # 与 variant_sources.family_pool 同形

部件检索要用的部件包第一次用到时才从 R2 按 sha 拉（约 2.6 MB），查族、形近只要核心包（已在 git）。

**异体关系不传递**：这里只给以查询字为中心的星形；`depth=2` 也只是「一跳成员再走一跳」，
从不做连通分量（需求 §7 坑 1）。
"""
from __future__ import annotations

import heapq
import sqlite3
import threading
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from . import schema as S


class Edge(NamedTuple):
    a: str
    b: str
    rel: str
    directed: int
    src: str
    sense: str
    ref: str
    note: str

    def other(self, c: str) -> str:
        return self.b if self.a == c else self.a


#: `pool()` 的来源简写，与 `variant_sources.family_pool` 的 `src` 对齐。
def _pool_tag(src: str) -> str | None:
    if src in S.LEGACY_TAGS or src.startswith("local:keben"):
        return None if src in S.LEGACY_NEVER_TAGS else "v"
    if src.startswith("charcomp:"):
        return "rt"
    if src == "zi" or src.startswith("zi:"):
        return "zi"
    if src.startswith("web:"):
        return "web"
    return None


def _ro_uri(p: Path) -> str:
    return p.resolve().as_uri() + "?mode=ro"          # Windows 下是 file:///C:/…


class HanziDB:
    """核心库常开；部件库 ATTACH 成 `parts`，没有就在第一次部件查询时经 `pack` 拉。"""

    def __init__(self, core: str | Path, parts: str | Path | None = None, pack=None):
        self.path = Path(core)
        if not self.path.exists():
            raise FileNotFoundError(f"没有 hanzi 库：{self.path}")
        self.con = sqlite3.connect(_ro_uri(self.path), uri=True, check_same_thread=False)
        self.meta = dict(self.con.execute("SELECT k, v FROM meta"))
        self.version = self.meta.get("version", "")
        self._pack = pack
        self._has_parts = False
        self._up_cache: dict[tuple[str, int], dict[str, int]] = {}
        self._lock = threading.Lock()                   # 控制台多线程：部件库只 ATTACH 一次
        if parts is not None:
            self._attach(Path(parts))

    @classmethod
    def open(cls, version: str | None = None, parts: bool | None = None, **pack_kw) -> HanziDB:
        """按清单打开某版（缺省当前版）。`parts=True` 立刻备好部件库，`False` 不要，
        `None`（缺省）本机有就挂上、没有就等第一次部件查询再拉。`pack_kw` 传给 `pack.Pack`。"""
        from .pack import Pack
        pk = Pack(version, **pack_kw)
        core = pk.ensure("core")
        p = pk.ensure("parts") if parts else (pk.db_path("parts") if parts is None and pk.has("parts")
                                              else None)
        return cls(core, p, pack=pk if parts is not False else None)

    @classmethod
    def from_tables(cls, root: str | Path, core: dict[str, list[tuple]],
                    parts: dict[str, list[tuple]] | None = None) -> HanziDB:
        """直接拿行建一个小库（测试与临时实验用，不走清单）：`{表: 行}`，列序同 `schema.TABLES`。"""
        from .pack import write_db
        root = Path(root)
        c = write_db(root / "core.sqlite", core, {"version": "adhoc", "pack": "core"})
        p = write_db(root / "parts.sqlite", parts, {"version": "adhoc", "pack": "parts"}) if parts else None
        return cls(c, p)

    def _attach(self, p: Path) -> None:
        self.con.execute("ATTACH DATABASE ? AS parts", (_ro_uri(p),))
        self._has_parts = True

    def _parts(self) -> None:
        if self._has_parts:
            return
        if self._pack is None:
            raise RuntimeError("没有部件库：用 HanziDB.open(parts=True) 打开")
        with self._lock:
            if not self._has_parts:
                self._attach(self._pack.ensure("parts"))

    def manifest(self) -> dict:
        return self._pack.manifest if self._pack is not None else {}

    # ── 边 ───────────────────────────────────────────

    def edges_of(self, c: str) -> list[Edge]:
        cur = self.con.execute("SELECT * FROM edges WHERE a=? UNION ALL SELECT * FROM edges WHERE b=?",
                               (c, c))
        return [Edge(*r) for r in cur]

    def edges(self, a: str, b: str) -> list[Edge]:
        return [e for e in self.edges_of(a) if e.other(a) == b]

    def family(self, c: str, rels: Iterable[str] = S.FAMILY_RELS, srcs: Iterable[str] | None = None,
               depth: int = 1, drop_distinct: bool = True) -> dict[str, list[Edge]]:
        """c 的族：`{成员: [把它连进来的边…]}`，不含 c 自己。

        - `rels`：走哪些关系（缺省不含 通假／钓鱼形近／简繁／负边）；
        - `srcs`：只认这些来源（前缀匹配，`"zi"` 认 `zi`、`zi:GHZR`）；
        - `depth=2`：一跳成员再各走一跳，第二跳的边记在第二跳成员名下；
        - `drop_distinct`：c 与某成员之间有人审定的 `distinct` 负边，就把它剔掉。"""
        rels = frozenset(rels)
        srcs = tuple(srcs) if srcs is not None else None

        def ok(e: Edge) -> bool:
            return e.rel in rels and (srcs is None or e.src.startswith(srcs))

        out: dict[str, list[Edge]] = {}
        frontier = [c]
        for _ in range(max(1, depth)):
            nxt = []
            for x in frontier:
                for e in self.edges_of(x):
                    if not ok(e):
                        continue
                    o = e.other(x)
                    if o == c or o == x:
                        continue
                    if o not in out:
                        nxt.append(o)
                    out.setdefault(o, []).append(e)
            frontier = nxt
        if drop_distinct:
            for e in self.edges_of(c):
                if e.rel == S.DISTINCT:
                    out.pop(e.other(c), None)
        return out

    def variants_of(self, c: str) -> list[tuple[str, tuple[str, ...]]]:
        """兼容 `open_guji_cv.variants.variants_of`：只用现役来源，`[(字, (标签…))]` 按码位排。"""
        acc: dict[str, set[str]] = {}
        for e in self.edges_of(c):
            if e.src in S.LEGACY_TAGS or e.src.startswith("local:keben"):
                acc.setdefault(e.other(c), set()).add(e.src)
        return [(b, tuple(sorted(acc[b]))) for b in sorted(acc)]

    def regulars_of(self, c: str) -> list[tuple[str, tuple[str, ...]]]:
        """c 作为异体／简体时，各来源指认的正字。"""
        acc: dict[str, set[str]] = {}
        for (a, src) in self.con.execute("SELECT a, src FROM edges WHERE b=? AND directed=1 "
                                         "AND rel NOT IN (?, ?)", (c, S.DISTINCT, S.BORROW)):
            acc.setdefault(a, set()).add(src)
        return [(r, tuple(sorted(acc[r]))) for r in sorted(acc)]

    def distinct(self, a: str, b: str) -> bool:
        return any(e.rel == S.DISTINCT for e in self.edges(a, b))

    # ── 形近 ─────────────────────────────────────────

    def near(self, c: str, k: int = 5, src: str = "near:v1") -> list[tuple[str, str, float, str]]:
        """形近字 `[(字, kind, score, detail)]`，分数降序；同分按原表行序（同 `confusables.load_pairs`）。"""
        cur = self.con.execute(
            "SELECT b, kind, score, detail, ln FROM near WHERE a=? AND src=? "
            "UNION ALL SELECT a, kind, score, detail, ln FROM near WHERE b=? AND src=?",
            (c, src, c, src))
        rows = sorted(cur, key=lambda r: (-r[2], r[4]))
        return [r[:4] for r in rows[:k]] if k else [r[:4] for r in rows]

    # ── 部件与 IDS（部件库）─────────────────────────

    def ids(self, c: str) -> list[tuple[str, str, str]]:
        self._parts()
        return list(self.con.execute("SELECT src, seq, regions FROM parts.ids WHERE ch=?", (c,)))

    def by_ids(self, seq: str) -> list[str]:
        self._parts()
        return sorted({r[0] for r in self.con.execute("SELECT ch FROM parts.ids WHERE seq=?", (seq,))})

    def components(self, c: str, max_depth: int = 1) -> list[str]:
        """c 的部件，逐层往下拆到 `max_depth` 层，按（层、码位）排。库里只存直接部件，多层现算。"""
        self._parts()
        depth: dict[str, int] = {}
        frontier = [c]
        for d in range(1, max_depth + 1):
            if not frontier:
                break
            q = f"SELECT part FROM parts.comps WHERE folded=0 AND ch IN ({','.join('?' * len(frontier))})"
            nxt = []
            for (p,) in self.con.execute(q, frontier):
                if p != c and p not in depth:
                    depth[p] = d
                    nxt.append(p)
            frontier = nxt
        return sorted(depth, key=lambda p: (depth[p], p))

    def _up(self, part: str, max_depth: int) -> dict[str, int]:
        """含 part 的字 → part 在其中第几层（逐层往上找、去重；认折叠形）。最常见的「口」约 3 万字、0.1 秒；
        结果上千字的常见部件留在进程内（控制台常驻时第二次就快了），最多 32 个。"""
        key = (part, max_depth)
        if key in self._up_cache:
            return self._up_cache[key]
        depth: dict[str, int] = {}
        frontier = [part]
        for d in range(1, max_depth + 1):
            nxt = []
            for i in range(0, len(frontier), 900):
                chunk = frontier[i:i + 900]
                q = f"SELECT ch FROM parts.comps WHERE part IN ({','.join('?' * len(chunk))})"
                for (ch,) in self.con.execute(q, chunk):
                    if ch != part and ch not in depth:
                        depth[ch] = d
                        nxt.append(ch)
            if not nxt:
                break
            frontier = nxt
        if len(depth) > 1000:
            if len(self._up_cache) >= 32:
                self._up_cache.pop(next(iter(self._up_cache)))
            self._up_cache[key] = depth
        return depth

    def by_components(self, parts: Iterable[str], max_depth: int = 6,
                      limit: int = 200) -> list[str]:
        """含全部给定部件（`max_depth` 层以内、认折叠形）的字，按「最深那个部件的层数、码位」排。
        从最少见的部件往上找；候选少时其余部件逐字往下核，多时也往上找再取交集。"""
        self._parts()
        parts = [p for p in dict.fromkeys(parts) if p]
        if not parts:
            return []
        n = {p: self.con.execute("SELECT COUNT(*) FROM parts.comps WHERE part=?", (p,)).fetchone()[0]
             for p in parts}
        parts.sort(key=lambda p: n[p])
        best = self._up(parts[0], max_depth)
        for p in parts[1:]:
            if not best:
                break
            if len(best) <= 300:
                found = {ch: self._depth_of(ch, p, max_depth) for ch in best}
            else:
                found = self._up(p, max_depth)
            best = {ch: max(d, found[ch]) for ch, d in best.items() if found.get(ch)}
        items = heapq.nsmallest(limit, best.items(), key=lambda t: (t[1], t[0]))
        return [ch for ch, _ in items]

    def _depth_of(self, ch: str, part: str, max_depth: int) -> int:
        """part 在 ch 里第几层（认折叠形）；不在 → 0。"""
        frontier, seen = [ch], {ch}
        for d in range(1, max_depth + 1):
            if not frontier:
                return 0
            q = f"SELECT part, folded FROM parts.comps WHERE ch IN ({','.join('?' * len(frontier))})"
            nxt = []
            for p, folded in self.con.execute(q, frontier):
                if p == part:
                    return d
                if not folded and p not in seen:
                    seen.add(p)
                    nxt.append(p)
            frontier = nxt
        return 0

    # ── 属性 ─────────────────────────────────────────

    def info(self, c: str) -> dict:
        """码位属性、主套 IDS（要部件库）＋归到 c 名下的未编码形。"""
        self._parts()
        row = self.con.execute("SELECT * FROM parts.chars WHERE ch=?", (c,)).fetchone()
        d = dict(zip(S.TABLES["chars"], row)) if row else {"ch": c}
        d["ids"] = self.ids(c)
        d["forms"] = [dict(zip(S.TABLES["forms"], r))
                      for r in self.con.execute("SELECT * FROM forms WHERE regular=?", (c,))]
        return d

    # ── 合成候选池 ───────────────────────────────────

    def pool(self, pivots: list[str], near_k: int = 5, srcs: Iterable[str] | None = None,
             extra: Callable[[str], dict[str, Iterable[str]]] | None = None) -> dict[str, dict]:
        """近似字 → `{字: {"p": 从哪个近似字来, "src": "piv,v,rt,zi,near"}}`。

        与 `variant_sources.family_pool` 同口径：v＝现役异体表（去通假、钓鱼形近）、rt＝部件檢索、
        zi＝字统网派生边、near＝形近表前 k；人审 distinct 不剔（池子只是候选，宁多勿少）。
        `extra(近似字) -> {简写: 字…}` 并进库外的来源（如本机字统网缓存里库还没收的族），
        与库里同一简写的合在一起排。"""
        from .importers import is_han
        want = set(srcs) if srcs is not None else None
        pool: dict[str, dict] = {}

        def add(c: str, p: str, tag: str) -> None:
            if not is_han(c) or (want is not None and tag not in want and tag != "piv"):
                return
            e = pool.setdefault(c, {"p": p, "src": []})
            if tag not in e["src"]:
                e["src"].append(tag)

        order = ("v", "rt", "zi", "web")
        for p in pivots:
            if not is_han(p):
                continue
            add(p, p, "piv")
            by_tag: dict[str, set[str]] = {}
            for e in self.edges_of(p):
                if e.rel == S.DISTINCT:
                    continue
                tag = _pool_tag(e.src)
                if tag:
                    by_tag.setdefault(tag, set()).add(e.other(p))
            for tag, cs in (extra(p) if extra else {}).items():
                by_tag.setdefault(tag, set()).update(cs)
            for tag in order:
                for c in sorted(by_tag.get(tag, ())):
                    add(c, p, tag)
            if near_k:
                for b, *_ in self.near(p, near_k):
                    add(b, p, "near")
        return {c: {"p": e["p"], "src": ",".join(e["src"])} for c, e in pool.items()}

    # ── 导出 ─────────────────────────────────────────

    def export_variants_json(self) -> dict:
        """按现役 `config/variants/variants.json` 的格式导出 `pairs`＋`directed`（不含 meta）。"""
        pairs: dict[str, dict[str, set[str]]] = {}
        directed: dict[str, dict[str, set[str]]] = {}
        for a, b, d, src in self.con.execute("SELECT a, b, directed, src FROM edges WHERE rel != ?",
                                             (S.DISTINCT,)):
            legacy = src in S.LEGACY_TAGS
            local = src.startswith("local:")
            if not (legacy or local):
                continue
            lo, hi = (a, b) if ord(a) < ord(b) else (b, a)
            pairs.setdefault(lo, {}).setdefault(hi, set()).add(src)
            if d and (src in S.LEGACY_DIRECTED_TAGS or local):
                directed.setdefault(b, {}).setdefault(a, set()).add(src)
        return {"pairs": {a: {b: sorted(t) for b, t in bs.items()} for a, bs in pairs.items()},
                "directed": {v: {r: sorted(t) for r, t in rs.items()} for v, rs in directed.items()}}


@lru_cache(maxsize=1)
def shared() -> HanziDB:
    """进程内共用的只读库（控制台常驻用；check_same_thread=False，只读可跨线程）。"""
    return HanziDB.open()
