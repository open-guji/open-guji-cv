# -*- coding: utf-8 -*-
"""异体族的三家来源，合成「以字找字」的候选池（只出候选，不进放行）。

研究与读数见 `doc/research/人审找字-以字找字与异体族按图排序.md` §8.3：三家各自都有漏
（同一批 414 对里字统网覆盖 358、部件檢索 379），合并后池子从 7 扩到 24、按图排序后
top-1/3/5 几乎不变，所以**并表、再按字块图排序**。

| 来源 | 文件 | 说明 |
|---|---|---|
| `v` 本仓异体表 | `config/variants/variants.json`（`variants.variants_of`） | 去掉 `NEVER_SOURCES`（形近钓鱼、通假） |
| `rt` 部件檢索 | `config/variants/charcomp_rt.tsv` | WFG「部件檢索」rt 表派生，非商业授权、须标来源（文件头） |
| `zi` 字统网 | 缓存目录 `$GUJI_ZITOOLS_CACHE`（缺省 `$GUJI_DATA_HOME/_shared/zitools/`），**不进 git** | `/api/zi/<字>` 的 yi 图解析成一跳族；站点无数据许可，只按需低频取、缓存（§9.4） |
| `near` 形近表 | `config/ids/confusable_pairs_v1.tsv`（`confusables.load_pairs`） | IDS 派生形近对，取前几名 |

字统网的族按「字典义项」连，混有通假、同音、构件关系（歷 的族里有 勒栗壢），
所以只当池子、必须按图排；而且**不对称**（查 𫎇 得 蒙，查 蒙 的一跳里没有 𫎇），
缓存里每取一个字就把反向边一起记下（`ZiCache.family` 合并两个方向）。

本模块不在任何 Step 的 `code_deps` 里，改它不让产物过期。
"""
from __future__ import annotations

import json
import os
import time
import unicodedata
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHARCOMP_TSV = REPO / "config" / "variants" / "charcomp_rt.tsv"
ZI_API = "https://zi.tools/api/zi/"
ZI_MIN_INTERVAL = 3.0          # 秒；对字统网的礼貌间隔
ZI_UA = "open-guji (low-rate, cached; https://github.com/open-guji)"


def is_han(c: str) -> bool:
    """单个汉字（含扩展区、兼容区归一后不变的），不要私用区、部首、标点。"""
    if len(c) != 1:
        return False
    o = ord(c)
    if 0xE000 <= o <= 0xF8FF or o >= 0xF0000:
        return False
    if unicodedata.normalize("NFC", c) != c:          # 兼容区重复字（歷 U+F98C → 歷）
        return False
    return unicodedata.category(c) == "Lo" and o >= 0x3400


# ── 本仓异体表 ────────────────────────────────────────

def ours(c: str) -> set[str]:
    from ..variants import NEVER_SOURCES, variants_of
    try:
        return {v for v, tags in variants_of(c) if set(tags) - NEVER_SOURCES and is_han(v)}
    except FileNotFoundError:
        return set()


# ── 部件檢索 rt ───────────────────────────────────────

@lru_cache(maxsize=4)
def _charcomp(path: str) -> dict[str, frozenset[str]]:
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, frozenset[str]] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        head, _, rest = line.partition("\t")
        out[head] = frozenset(c for c in rest if is_han(c) and c != head)
    return out


def charcomp(c: str, path: str | Path | None = None) -> set[str]:
    return set(_charcomp(str(path or CHARCOMP_TSV)).get(c, ()))


# ── 字统网 ────────────────────────────────────────────

def zi_parse(doc: dict, q: str) -> list[str]:
    """`/api/zi/<q>` 的 yi 图 → 一跳族（已编码单字，不含 q）。

    从「字形＝q」或「正字＝q」的节点出发，沿 `yi.edges` 走一跳，收节点字形（`nodes[k][4]`）。
    未编码形（IDS 串）不收——它们落不成一个码位，留给以后的无码字通道。"""
    yi = doc.get("yi") or {}
    nodes = yi.get("nodes") or {}
    adj: dict[str, set[str]] = {}
    for e in yi.get("edges") or []:
        if len(e) >= 2:
            adj.setdefault(e[0], set()).add(e[1])
            adj.setdefault(e[1], set()).add(e[0])
    start = {k for k, n in nodes.items()
             if isinstance(n, list) and len(n) > 10 and (n[4] == q or n[10] == q)}
    keys = start | {m for k in start for m in adj.get(k, ())}
    out = {nodes[k][4] for k in keys if k in nodes and isinstance(nodes[k][4], str)}
    return sorted(c for c in out if c != q and is_han(c))


def zi_cache_dir() -> Path:
    if os.environ.get("GUJI_ZITOOLS_CACHE"):
        return Path(os.environ["GUJI_ZITOOLS_CACHE"])
    home = Path(os.environ.get("GUJI_DATA_HOME") or Path.home() / ".guji-data")
    return home / "_shared" / "zitools"


class ZiCache:
    """字统网一跳族的本地缓存：每字一个 `U+XXXX.json`（`{"q", "fam", "ts"}`），外加反向边。

    `fetch=False`（缺省）只读缓存，查不到就当没有；`fetch=True` 时缺的字去取一次
    （≥3 秒一次），取到写缓存。取失败（断网、站点改版）不报错，当没有，不写缓存，下次再试。"""

    def __init__(self, root: Path | None = None, fetch: bool = False,
                 interval: float = ZI_MIN_INTERVAL, opener=None):
        self.root = Path(root) if root else zi_cache_dir()
        self.fetch = fetch
        self.interval = interval
        self._opener = opener or urllib.request.urlopen
        self._last = 0.0
        self._mem: dict[str, list[str] | None] = {}
        self._rev: dict[str, set[str]] | None = None
        self.n_fetched = 0

    def _path(self, c: str) -> Path:
        return self.root / f"U+{ord(c):04X}.json"

    def _reverse(self) -> dict[str, set[str]]:
        if self._rev is None:
            self._rev = {}
            if self.root.exists():
                for f in self.root.glob("U+*.json"):
                    try:
                        d = json.loads(f.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    for v in d.get("fam") or ():
                        self._rev.setdefault(v, set()).add(d["q"])
        return self._rev

    def _get(self, c: str) -> list[str] | None:
        if c in self._mem:
            return self._mem[c]
        fam = None
        f = self._path(c)
        if f.exists():
            try:
                fam = json.loads(f.read_text(encoding="utf-8")).get("fam")
            except Exception:
                fam = None
        elif self.fetch:
            fam = self._download(c)
        self._mem[c] = fam
        return fam

    def _download(self, c: str) -> list[str] | None:
        wait = self.interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        req = urllib.request.Request(ZI_API + urllib.parse.quote(c), headers={"User-Agent": ZI_UA})
        try:
            with self._opener(req, timeout=30) as r:
                doc = json.loads(r.read().decode("utf-8"))
        except Exception:
            return None
        fam = zi_parse(doc, c)
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(c).write_text(json.dumps({"q": c, "fam": fam, "ts": int(time.time())},
                                            ensure_ascii=False), encoding="utf-8")
        self.n_fetched += 1
        if self._rev is not None:
            for v in fam:
                self._rev.setdefault(v, set()).add(c)
        return fam

    def ensure(self, c: str) -> None:
        """不论 `fetch` 开关，缓存里没有 c 就去取一次（控制台里人键入的近似字用）。"""
        if self._mem.get(c) is None and not self._path(c).exists():
            self._mem.pop(c, None)
            self._mem[c] = self._download(c)

    def family(self, c: str) -> set[str]:
        """c 的字统网一跳族 ∪ 缓存里以 c 为族成员的字（反向边）。"""
        return set(self._get(c) or ()) | self._reverse().get(c, set())


_SHARED_ZI: ZiCache | None = None


def shared_zi() -> ZiCache:
    """进程内共用的只读缓存（控制台常驻用；反向边只扫一次目录）。"""
    global _SHARED_ZI
    if _SHARED_ZI is None:
        _SHARED_ZI = ZiCache(fetch=False)
    return _SHARED_ZI


# ── 合并 ─────────────────────────────────────────────

def near(c: str, k: int = 5) -> set[str]:
    from .confusables import load_pairs
    return {b for b, *_ in load_pairs().get(c, [])[:k] if is_han(b)}


def family_pool(pivots: list[str], zi: ZiCache | None = None,
                near_k: int = 5) -> dict[str, dict]:
    """近似字 → 合并池 `{字: {"p": 从哪个近似字来, "src": "v,rt,zi,near,piv"}}`。

    同一个字从几路来时 `src` 合并、`p` 取第一个（pivots 按优先级排好传进来）。近似字自己也进池（`piv`）。"""
    pool: dict[str, dict] = {}

    def add(c: str, p: str, src: str) -> None:
        if not is_han(c):
            return
        e = pool.setdefault(c, {"p": p, "src": []})
        if src not in e["src"]:
            e["src"].append(src)

    for p in pivots:
        if not is_han(p):
            continue
        add(p, p, "piv")
        for c in ours(p):
            add(c, p, "v")
        for c in charcomp(p):
            add(c, p, "rt")
        if zi is not None:
            for c in zi.family(p):
                add(c, p, "zi")
        if near_k:
            for c in near(p, near_k):
                add(c, p, "near")
    return {c: {"p": e["p"], "src": ",".join(e["src"])} for c, e in pool.items()}
