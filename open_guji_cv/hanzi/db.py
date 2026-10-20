# -*- coding: utf-8 -*-
"""hanzi 库的查询（总设计 §6.3）。只读打开 sqlite，进程内常驻。

    from open_guji_cv.hanzi import HanziDB
    db = HanziDB.open()            # $GUJI_HANZI_DB，否则 $GUJI_DATA_HOME/_shared/hanzi/current
    db.family("互")                # {字: [Edge…]}，星形一跳，剔掉人审定的 distinct
    db.pool(["歷", "注"])          # 与 variant_sources.family_pool 同形

**异体关系不传递**：这里只给以查询字为中心的星形；`depth=2` 也只是「一跳成员再走一跳」，
从不做连通分量（需求 §7 坑 1）。
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable
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


def default_path() -> Path:
    env = os.environ.get("GUJI_HANZI_DB")
    if env:
        p = Path(env)
        return p / "hanzi.sqlite" if p.is_dir() else p
    from .build import data_root
    root = data_root()
    cur = root / "current"
    if not cur.exists():
        raise FileNotFoundError(f"没有 hanzi 库：{cur} 不存在。先跑 python scripts/build_hanzi_db.py --fetch")
    return root / cur.read_text(encoding="utf-8").strip() / "hanzi.sqlite"


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


class HanziDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"没有 hanzi 库：{self.path}")
        uri = self.path.resolve().as_uri() + "?mode=ro"     # Windows 下是 file:///C:/…
        self.con = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.meta = dict(self.con.execute("SELECT k, v FROM meta"))
        self.version = self.meta.get("version", "")

    @classmethod
    def open(cls, path: str | Path | None = None) -> HanziDB:
        return cls(path or default_path())

    def manifest(self) -> dict:
        p = self.path.parent / "manifest.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

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

    # ── 部件与 IDS ───────────────────────────────────

    def ids(self, c: str, src: str | None = None) -> list[tuple[str, str, str]]:
        q = "SELECT src, seq, regions FROM ids WHERE ch=?" + (" AND src=?" if src else "")
        return list(self.con.execute(q, (c, src) if src else (c,)))

    def by_ids(self, seq: str) -> list[str]:
        return sorted({r[0] for r in self.con.execute("SELECT ch FROM ids WHERE seq=?", (seq,))})

    def components(self, c: str, max_depth: int = 1) -> list[str]:
        return [r[0] for r in self.con.execute(
            "SELECT part FROM comps WHERE ch=? AND depth<=? AND folded=0 ORDER BY depth, part",
            (c, max_depth))]

    def by_components(self, parts: Iterable[str], max_depth: int = 6,
                      limit: int = 200) -> list[str]:
        """含全部给定部件（任意深度、认折叠形）的字，按「最深那个部件的深度、码位」排。"""
        parts = [p for p in dict.fromkeys(parts) if p]
        if not parts:
            return []
        joins = " ".join(f"JOIN comps c{i} ON c{i}.ch = c0.ch AND c{i}.part = ? AND c{i}.depth <= ?"
                         for i in range(1, len(parts)))
        deepest = "MAX(" + ", ".join(f"c{i}.depth" for i in range(len(parts))) + ")" \
            if len(parts) > 1 else "c0.depth"
        sql = (f"SELECT c0.ch, MIN({deepest}) AS d FROM comps c0 {joins} "
               f"WHERE c0.part = ? AND c0.depth <= ? GROUP BY c0.ch")
        args: list = []
        for p in parts[1:]:
            args += [p, max_depth]
        args += [parts[0], max_depth]
        items = sorted(self.con.execute(sql, args), key=lambda t: (t[1], ord(t[0][0]), t[0]))
        return [ch for ch, _ in items[:limit]]

    # ── 属性 ─────────────────────────────────────────

    def info(self, c: str) -> dict:
        row = self.con.execute("SELECT * FROM chars WHERE ch=?", (c,)).fetchone()
        d = dict(zip(S.TABLES["chars"], row)) if row else {"ch": c}
        d["ids"] = self.ids(c)
        d["forms"] = [dict(zip(S.TABLES["forms"], r))
                      for r in self.con.execute("SELECT * FROM forms WHERE regular=?", (c,))]
        return d

    # ── 合成候选池 ───────────────────────────────────

    def pool(self, pivots: list[str], near_k: int = 5, srcs: Iterable[str] | None = None
             ) -> dict[str, dict]:
        """近似字 → `{字: {"p": 从哪个近似字来, "src": "piv,v,rt,zi,near"}}`。

        与 `variant_sources.family_pool` 同口径：v＝现役异体表（去通假、钓鱼形近）、rt＝部件檢索、
        zi＝字统网派生边、near＝形近表前 k；人审 distinct 不剔（池子只是候选，宁多勿少）。"""
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
    """进程内共用的只读库（控制台常驻用）。"""
    return HanziDB.open()
