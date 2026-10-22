# -*- coding: utf-8 -*-
"""「以字找字」的候选池（只出候选，不进放行）：近似字的异体族＋形近，交给字块图排序。

研究与读数见 `doc/research/人审找字-以字找字与异体族按图排序.md` §8.3：各家来源都有漏
（同一批 414 对里字统网覆盖 358、部件檢索 379），合并后池子从 7 扩到 24、按图排序后
top-1/3/5 几乎不变，所以**并表、再按字块图排序**。

2026-10-19 起族由自建汉字关系库 `open_guji_cv.hanzi` 给（`HanziDB.pool`，见
`doc/design/汉字字形与关系库-总设计.md` B3），本机不联网也有完整的族：

| 简写 | 来源 | 说明 |
|---|---|---|
| `v` | 库里的现役异体来源（Unihan、twedu、hydzd、dypytz、简繁、yitizi、`local:keben`） | 去掉形近钓鱼、通假 |
| `rt` | 库里的部件檢索 rt | 非商业授权、须标来源（库的 `sources` 表） |
| `zi` | 库里的字统网派生族 ∪ 本机缓存 `$GUJI_ZITOOLS_CACHE`（缺省 `$GUJI_DATA_HOME/_shared/zitools/`） | 库是出版本时汇总的；缓存里后来取的字照样并进来（`ZiCache`） |
| `near` | 形近表 `config/ids/confusable_pairs_v1.tsv` | 取前几名 |

字统网只按需、针对性地取（一次一字、≥3 秒间隔），只存派生的族，不存页面；
攒下的缓存出新版库时用 `scripts/build_hanzi_db.py --zi-dir` 汇总进库，全队共享。

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


#: 缓存格式版本：2 起除一跳族外还存逐节点的字典判断与连线（`zi_facts`）。
ZI_CACHE_V = 2


def zi_facts(doc: dict) -> dict[str, list]:
    """`/api/zi/<q>` 的 yi 图 → 派生事实（只留关系，不留释义原文、读音、图）：

    - `claims`：`[字典前缀, 节点 id, 字形, 正字]`——这部字典（GHZR 汉语大字典、TVAR 台湾异体字典、
      GHZH 汉字海、ZITOOLS 站方……）的这个条目说「字形」是「正字」的异体。字形可以是 IDS 串（未编码形）；
      正字只收单个已编码字。
    - `links`：`[节点 A, 字形 A, 节点 B, 字形 B]`——图上两个节点相连，两头都是已编码单字且不同的才收。"""
    yi = doc.get("yi") or {}
    nodes = {k: n for k, n in (yi.get("nodes") or {}).items() if isinstance(n, list) and len(n) > 10}
    claims = []
    for k, n in sorted(nodes.items()):
        g, r = n[4], n[10]
        if isinstance(g, str) and g and isinstance(r, str) and is_han(r) and g != r:
            claims.append([n[1], k, g, r])
    links = []
    for e in yi.get("edges") or []:
        if len(e) >= 2 and e[0] in nodes and e[1] in nodes:
            ga, gb = nodes[e[0]][4], nodes[e[1]][4]
            if isinstance(ga, str) and isinstance(gb, str) and ga != gb and is_han(ga) and is_han(gb):
                links.append([e[0], ga, e[1], gb])
    return {"claims": claims, "links": sorted(links)}


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
        self._path(c).write_text(json.dumps({"q": c, "v": ZI_CACHE_V, "fam": fam, **zi_facts(doc),
                                             "ts": int(time.time())}, ensure_ascii=False), encoding="utf-8")
        self.n_fetched += 1
        if self._rev is not None:
            for v in fam:
                self._rev.setdefault(v, set()).add(c)
        return fam

    def ensure(self, c: str, upgrade: bool = False) -> bool:
        """不论 `fetch` 开关，缓存里没有 c 就去取一次（控制台里人键入的近似字用）；返回这次联网了没有。
        `upgrade=True` 时旧格式（没有逐节点事实）的也重取一次（`scripts/zi_fetch.py` 批量补查用）。"""
        f = self._path(c)
        stale = upgrade and f.exists() and self._version(f) < ZI_CACHE_V
        if stale or (self._mem.get(c) is None and not f.exists()):
            self._mem.pop(c, None)
            self._mem[c] = self._download(c)
            return True
        return False

    @staticmethod
    def _version(f: Path) -> int:
        try:
            return int(json.loads(f.read_text(encoding="utf-8")).get("v") or 1)
        except (OSError, ValueError):
            return 0

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

@lru_cache(maxsize=1)
def _hanzi():
    from ..hanzi import HanziDB
    return HanziDB.open()


def family_pool(pivots: list[str], zi: ZiCache | None = None, near_k: int = 5,
                db=None) -> dict[str, dict]:
    """近似字 → 合并池 `{字: {"p": 从哪个近似字来, "src": "piv,v,rt,zi,near"}}`。

    同一个字从几路来时 `src` 合并、`p` 取第一个（pivots 按优先级排好传进来）。近似字自己也进池（`piv`）。
    近似字里有特殊符号（`hanzi.symbols`）时整张符号表并进来（`sym`）。
    `db` 缺省用当前版 hanzi 库（核心包在 git，不联网）；`zi` 给了就把本机缓存的族并进 `zi`。"""
    db = db if db is not None else _hanzi()
    extra = (lambda p: {"zi": zi.family(p)}) if zi is not None else None
    pool = db.pool(pivots, near_k=near_k, extra=extra)
    # 特殊符号（○□△…）不是汉字，库里没有它们的边；近似字里有符号时整张符号表进池（符号之间互为形近），按图排
    from ..hanzi.symbols import is_symbol, symbols
    sym = next((p for p in pivots if is_symbol(p)), None)
    if sym:
        for c in symbols():
            pool.setdefault(c, {"p": sym, "src": "piv" if c == sym else "sym"})
    return pool
