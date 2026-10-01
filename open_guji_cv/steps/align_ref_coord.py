"""Step5-d 按坐标对位（`align: coord`，2026-09-28，D 道 overview#195）。

## 为什么要有这一路

`align_ref` 的现役对位是「整页定字串 8-gram 锚定 + `difflib`」：拿**认出来的字**去
对整理本。整页认字烂掉的地方——用户点名的 vol03 p3，一枚大印章压住半页，背景满是
噪点——锚定串全是错字，整页锚不上，那一块的格就一个整理本字都拿不到，人裁只能对着
噪点一格一格猜。

四庫總目的整理本（光盘版 `zongmu_wenyuange_wikisource.txt`，以及 P 道正在导的
daizhige 逐列本）是**逐行分开**的：一行 = 刻本一列，版式 21 格/列。所以只要
①知道这一列对的是整理本哪一行、②Step3 切出来的格与这一行的字数对得上，就可以
**按位置**把整理本的字一格一格配上去，不依赖这一格认得出认不出。

## 算法

1. **行表**：整理本逐行解析成「单元」序列——正文一字一单元；`<…>` 双行小注按
   阅读顺序切成右行 a（前一半，向上取整）/左行 b（后一半），每一行（a,b）是一个
   单元，与 Step3 的夹注格 `slot a/b` 同构。标点、空白丢掉。
2. **定窗**：先用现役 8-gram 投票（`_raw_vote_clusters`，不设票数下限）找页在语料
   里的大致位置；一票都没有就退到 4-gram 直接在语料里 `find`（只在锚不上的少数
   页走，4-gram 在全文里 `find` 几十次，毫秒级）。偏移换算成行号，前后各留十几行。
3. **页内列→行**：窗内每一行与每一列的锚定载体（`slots_from_evidence` 同一口径）
   算字对（bigram）重合数，按「第 i 个非空列 ↔ 第 d+i 行」对整页投 d。最高票要
   ≥ `COORD_MIN_PAGE_VOTES`、且压过次高票 1.5 倍，才认这一页的列行对应。
4. **列内按坐标配字**：这一列的格按阅读顺序排成单元（正文格一单元、同一 slot 的
   夹注 a/b 合一单元），**几何行号** `g = 格中心 y / period + 0.5`（1 起）。在格序列
   里找一段**长度正好等于该行单元数、类型逐个对得上**（正文↔正文、夹注↔夹注）的连续
   格，要求这段格的几何行号逐格递增 1（残差 ≤ `COORD_MAX_RESID` 行），段外多出来的
   格（印章/污点切出来的假格）几何上必须落在这段文字的**范围之外**——它们对的是
   整理本的空格位，记 `ref_char=""`。满足的段不止一个时（假格与字格混在一起），
   用载体字与整理本字的吻合数挑，最高者要比次高者多 ≥1，否则判「有歧义」退回。
5. **格数对不上的列退回现有锚定**（`coord_fallback` 记原因），本路不给任何字。

几何上逐格配位只用格的位置；载体字只用来 (a) 定页在语料里的位置 (b) 在几个几何上
都成立的配法里挑一个。所以印章把字压得认不出时，只要这一列有两三个字认得出、
或者这一列根本没有假格，就能配上。

## 换源：daizhige 逐列本（同日，P 道 `siku_daizhige.txt`）

逐列本带 `#@` 半叶头、全角空格格位、`<右|左>` 小注、空列留行，于是：列→行按列号（不按
非空列序号）、页首只能落在半叶头；列内按**格位**配（run 之间的空格位也算，假格可以落在
空格位上）；几何上多解时用同页唯一解列量出的「格位→行号」偏移来分。`〓`（没码表的 PUA）
照记，下游当「有字、不知道是哪个」。

vol03 104 页实测（`cloud-20260927-4e2e0b7-iron` 快照）：

| 源 | 坐标对位列 | 退回列 | 与现役对位不一致 |
|---|---|---|---|
| 光盘版 | 856 / 891 | 35（其中「分行错一位」14） | 0 |
| daizhige | **876 / 900** | 24（分行错一位 1） | 0 |

两条同日加的闸：**斜率**——只拟偏移时 21 格长列会因 Step3 period 差 2~3% 在末端漂出半行
（daizhige 源 21 列正文因此退回），改成字位 ≥5 就拟 `g = a·格位 + b`、a∈[0.9, 1.1]；
**错位闸**——挪一格后载体吻合 ≥2 且高于原配法就退回（vol01 p102 列6 职名页：Step3 把
「文」切成两格、「官」又刚好漏切，格数对上、整列错一位，页锚不上没有现役对位可比）。
vol01（卷首，职名/目录多）daizhige 源 1,752 列里坐标对位 1,286、退回 466，退回的绝大多数是
职名/目录的分散排版（行 5~16 字对不上几何），P 道提醒的「卷首二职名页退回锚定」由几何闸
自然兑现；对位独有的 200 格（去 `〓`）抽 30 看图 29 对，1 格是版本异文（刻「各」、daizhige「名」）。

## 与现役对位的关系

**不改现役 `chars`**（8-gram + difflib 的结果逐字节不变），坐标对位另记在
`PageAlignRef.coord`。下游只有三处读它：
- `seed_admit` 的 `occluded`（印章污损）格：默认字取坐标对位的字（没有才退到
  现役对位字）；
- 人审卡 `ref`：现役对位没给字的格，用坐标对位的字补上显示；
- 本模块的对照报告（坐标对位 vs 现役对位 一致/不一致格数）。

**不进任何准入通道**——`admission_decision` 读的仍然只是现役 `chars`。所以打开这一路
不会让任何一格从「待审」变成「放行」（验收口径：其余册 admit 只许减少）。
"""

from __future__ import annotations

import bisect
import math
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

#: 与 `align_ref._NON_HAN_RE` 同一口径：8-gram 索引/`_corpus_text` 只留这一段汉字，
#: 偏移 → 行号的换算必须按同一把尺子数。
_HAN_RE = re.compile(r"[一-鿿]")
_NOTE_OPEN, _NOTE_CLOSE = "<", ">"

COORD_MIN_PAGE_VOTES = 6       # 页级列→行投票的最低票数（字对重合总数）
COORD_PAGE_DOMINANCE = 1.5     # 最高票 / 次高票
COORD_MAX_RESID = 0.45         # 列内几何行号的最大残差（单位：行）
COORD_OUTSIDE_MARGIN = 0.5     # 段外假格离文字范围至少多远（行）
COORD_WINDOW_LINES = 14        # 定窗时锚点前后各留几行
COORD_MAX_CANDIDATE_RUNS = 64  # 一列里几何上都成立的配法上限（防病态列）
COORD_MERGE_MIN_AGREE = 3      # 少一格（并格）救援：最高配法的载体吻合下限
COORD_MERGE_MIN_CELLS = 4      # 少一格救援：共识后至少要给出这么多格的字，否则整列不认


def is_text_char(ch: str) -> bool:
    """整理本里算「一个字位」的字符：CJK/字母类、数字类（〇）、私用区、`□`（阙字）。"""
    if ch in "□〓":            # 〓：daizhige 逐列本里没有码表的 PUA 生僻字占位
        return True
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "N") or cat == "Co"


@dataclass(frozen=True)
class Unit:
    """整理本一行里的一个字位单元。`kind="c"` 正文一字；`kind="n"` 夹注一行（a 右、b 左）；
    `kind="b"` 空格位（逐列本的列首缩进/run 之间的空格，全角空格记）。"""
    kind: str
    a: str
    b: str = ""


@dataclass
class RefLine:
    idx: int                 # 在非空行表里的序号
    units: list[Unit]
    han_start: int           # 本行在 `_corpus_text`（只留 [一-鿿]）里的起始偏移
    text: str = ""           # 本行全部字（正文 + 夹注 a + 夹注 b，阅读顺序），算重合用
    leaf_start: bool = False # 逐列本（带 `#@` 半叶头）里半叶的第一列

    @property
    def n(self) -> int:
        """字位单元数（不含空格位）。"""
        return sum(1 for u in self.units if u.kind != "b")

    def text_units(self) -> list[tuple[int, "Unit"]]:
        """[(格位, 单元)]：格位是在本行里的序号（含空格位），逐列本即 daizhige 的格位。"""
        return [(i, u) for i, u in enumerate(self.units) if u.kind != "b"]


GRID_HEADER = "#@"
_BLANK = "\u3000"


def parse_lines(raw: str) -> list[RefLine]:
    """整理本原文 → 行表。

    两种格式：
    - **光盘版**（整段按列断行、没有格位）：丢掉空行，标点/空白一律不算字位；
      `<…>` 小注按一半一半切 a/b（右行取前一半，向上取整），跨行的小注按行各自切。
    - **逐列本**（P 道 `siku_daizhige.txt`，2026-09-28）：每半叶前一行 `#@ …` 头，其后
      一行一列（**空列也留一行**，列号靠它对齐）；全角空格＝空格位（列首 `start`、run
      之间的空格），`<右行|左行>` 按 `|` 分右行/左行。"""
    grid = any(ln.startswith(GRID_HEADER) for ln in raw.splitlines()[:50])
    out: list[RefLine] = []
    han = 0
    in_note = False
    leaf_start = False
    for line in raw.splitlines():
        if grid and line.startswith("#"):
            leaf_start = True
            continue
        units: list[Unit] = []
        note: list[str] = []
        text: list[str] = []

        def flush_note():
            if "|" in note:
                k = note.index("|")
                a, b = note[:k], note[k + 1:]
            else:
                k = math.ceil(len(note) / 2)
                a, b = note[:k], note[k:]
            for i in range(max(len(a), len(b))):
                units.append(Unit("n", a[i] if i < len(a) else "", b[i] if i < len(b) else ""))
            text.extend(ch for ch in note if ch != "|")
            note.clear()

        for ch in line:
            if ch == _NOTE_OPEN:
                in_note = True
                continue
            if ch == _NOTE_CLOSE:
                flush_note()
                in_note = False
                continue
            if in_note and ch == "|":
                note.append(ch)
                continue
            if grid and ch == _BLANK and not in_note:
                units.append(Unit("b", ""))
                continue
            if not is_text_char(ch):
                continue
            if in_note:
                note.append(ch)
            else:
                units.append(Unit("c", ch))
                text.append(ch)
        if note:
            flush_note()
        while units and units[-1].kind == "b":
            units.pop()
        n_han = len(_HAN_RE.findall(line))
        if units or grid:
            out.append(RefLine(idx=len(out), units=units, han_start=han, text="".join(text),
                               leaf_start=grid and leaf_start))
            leaf_start = False
        han += n_han
    return out


@lru_cache(maxsize=4)
def ref_lines(path: str) -> tuple[list[RefLine], list[int]]:
    p = Path(path)
    if not p.exists():
        return [], []
    lines = parse_lines(p.read_text(encoding="utf-8"))
    return lines, [ln.han_start for ln in lines]


def line_at(starts: list[int], offset: int) -> int:
    return max(0, bisect.bisect_right(starts, offset) - 1)


# ── 定窗 ────────────────────────────────────────────────────────────────
def scan_offset(query: str, text: str, gram: int = 4, step: int = 2,
                max_hits: int = 40, pool: int = 8) -> tuple[int | None, int]:
    """n-gram 直接在语料里 `find` 投票（锚不上的页才走）。返回 (偏移, 峰簇票数)。

    常见 n-gram（命中超过 `max_hits` 处）不投票——套语到处都是，只会把票摊平。"""
    from collections import Counter
    votes: Counter[int] = Counter()
    for i in range(0, max(0, len(query) - gram + 1), step):
        g = query[i:i + gram]
        hits: list[int] = []
        pos = text.find(g)
        while pos >= 0 and len(hits) <= max_hits:
            hits.append(pos)
            pos = text.find(g, pos + 1)
        if not hits or len(hits) > max_hits:
            continue
        for h in hits:
            votes[h - i] += 1
    if not votes:
        return None, 0
    best, best_v = None, 0
    for o in votes:
        v = sum(votes[o2] for o2 in range(o - pool, o + pool + 1) if o2 in votes)
        if v > best_v or (v == best_v and best is not None and o < best):
            best, best_v = o, v
    return best, best_v


# ── 页内列 → 行 ─────────────────────────────────────────────────────────
def _bigrams(s: str) -> set[str]:
    return {s[i:i + 2] for i in range(len(s) - 1)}


def line_sim(carrier: str, line: RefLine) -> int:
    """列载体串与整理本一行的字对（bigram）重合数。"""
    if len(carrier) < 2 or line.n == 0:
        return 0
    return len(_bigrams(carrier) & _bigrams(line.text))


@dataclass
class PageMap:
    base: int | None                          # 第 0 个非空列对应的行号（`lines` 下标）
    votes: int = 0
    runner_up: int = 0
    col_line: dict[int, int] = field(default_factory=dict)
    note: str = ""


def map_columns(carriers: list[tuple[int, str]], lines: list[RefLine],
                lo: int, hi: int, grid: bool = False) -> PageMap:
    """`carriers`：[(列号, 该列载体串)]，只含非空列、按列号升序（= 阅读顺序）。

    光盘版：第 i 个**非空列**对第 d+i 行（空列在光盘版里没有行）。
    逐列本（`grid`）：第 c 列对第 d+c−1 行（空列也有行），d 只取半叶的第一列。"""
    if not carriers:
        return PageMap(None, note="没有非空列")
    lo, hi = max(0, lo), min(len(lines), hi)
    offs = [(col - 1) if grid else ci for ci, (col, _c) in enumerate(carriers)]
    sims = {(ci, li): line_sim(c, lines[li])
            for ci, (_col, c) in enumerate(carriers) for li in range(lo, hi + offs[-1] + 1)
            if li < len(lines)}
    scores: list[tuple[int, int]] = []
    for d in range(lo, hi):
        if grid and not lines[d].leaf_start:
            continue
        s = sum(sims.get((ci, d + offs[ci]), 0) for ci in range(len(carriers)))
        scores.append((s, d))
    if not scores:
        return PageMap(None, note="窗口内没有整理本行")
    scores.sort(key=lambda t: (-t[0], t[1]))
    best_s, best_d = scores[0]
    second = next((s for s, d in scores[1:] if d != best_d), 0)
    pm = PageMap(best_d, best_s, second)
    if best_s < COORD_MIN_PAGE_VOTES:
        pm.base, pm.note = None, f"列行投票太少（{best_s}）"
        return pm
    if second and best_s < COORD_PAGE_DOMINANCE * second:
        pm.base, pm.note = None, f"列行投票无优势（{best_s} vs {second}）"
        return pm
    for ci, (col, _c) in enumerate(carriers):
        li = best_d + offs[ci]
        if li >= len(lines):
            continue
        # 这一列自己明显更像别的行 → 不认（光盘版与刻本分行不一致时的保险）
        own = sims.get((ci, li), 0)
        other = max((v for (cj, l2), v in sims.items() if cj == ci and l2 != li), default=0)
        if other >= own + 3 and other >= 2 * max(own, 1):
            continue
        pm.col_line[col] = li
    return pm


# ── 列内按坐标配字 ──────────────────────────────────────────────────────
@dataclass
class CellUnit:
    """列内一个格单元：正文格一个；同一 slot 的夹注 a/b 合成一个。"""
    kind: str                 # "c" | "n"
    slot: int
    g: float                  # 几何行号（1 起）
    ids: dict[str, str]       # {"": id} 或 {"a": id, "b": id}
    carrier: dict[str, str]   # 同上，载体字


@dataclass
class ColumnCoord:
    ok: bool
    note: str = ""
    recs: list[tuple[str, int, str | None, str, float]] = field(default_factory=list)
    """[(id, slot, sub, ref_char, g)]；`ref_char=""` = 整理本这一位是空格（假格）。"""
    agree: int = 0
    b: float | None = None       # 「格位 → 几何行号」偏移
    unique: bool = False         # 几何上只有这一种配法（拿来估页级偏移）
    merged: bool = False         # 走了「少一格（并格）共识」救援，只给了共识格的字


def _agree(u: CellUnit, ref: Unit) -> int:
    if u.kind == "c":
        return int(u.carrier.get("", "") == ref.a)
    return int(u.carrier.get("a", "") == ref.a) + int(bool(ref.b) and u.carrier.get("b", "") == ref.b)


COORD_SLOPE = (0.9, 1.1)      # 列内几何行距 / period 的允许范围
COORD_SLOPE_MIN_N = 5         # 字位少于这个数只拟偏移（斜率固定 1）


def _fit(pos: list[int], g: list[float]) -> tuple[float | None, float]:
    """几何行号 `g ≈ a·格位 + b`。

    只拟偏移（a=1）在长列上不够：Step3 的 period 估得差 2~3%，21 格一列末端就漂出
    半行（vol03 daizhige 源实测 21 列 19 字的正文列全因此退回，格数其实一格不差）。
    所以字位 ≥ `COORD_SLOPE_MIN_N` 时最小二乘拟斜率，斜率超出 `COORD_SLOPE` 判不成立。"""
    n = len(pos)
    if n < COORD_SLOPE_MIN_N or max(pos) == min(pos):
        r = sorted(gi - p for gi, p in zip(g, pos))
        return 1.0, r[n // 2]
    mp, mg = sum(pos) / n, sum(g) / n
    a = sum((p - mp) * (gi - mg) for p, gi in zip(pos, g)) / sum((p - mp) ** 2 for p in pos)
    if not COORD_SLOPE[0] <= a <= COORD_SLOPE[1]:
        return None, 0.0
    return a, mg - a * mp


def _merge_rescue(units: list[CellUnit], text: list[tuple[int, Unit]]) -> ColumnCoord | None:
    """「少一格」救援（2026-09-30，L1 道 overview#318）：整列比整理本**恰好少一格**时的共识配位。

    起因：四庫 vol02 p3 卷首标题列「欽定四庫全書總目卷」9 字，Step3 在印章下只切出 8 格
    （+5 格印章假格）——某相邻两字被并进一格。1:1 配法要么几何过不了（斜率＞1.1，配上去
    从并格处起整列错一位），要么只剩把标题配到印章格上的两种假配法（载体吻合 0 vs 0），
    整列因此空着。

    做法：枚举「哪一对相邻正文字并进同一格 m」×「从哪一格起 j」，仍要求几何成立（格中心
    ≈ a·格位 + b，并格取两字格位的中点；段外假格离文字 > 半行）；按载体吻合数（并格命中
    两字之一也算）排，最高者 ≥ `COORD_MERGE_MIN_AGREE`，且**起点不同的配法吻合数都得比它
    至少少 2**（否则起点有歧义，整列不认）。并格位置分不出来（几何上靠载体挑不开，p3 上
    m∈{全書,庫全,四庫} 三者并列）时**只给共识格**——所有并列配法一致的格才给字，不一致的
    格（含并格本身）**不出记录**，让下游当「没有坐标对位」而不是「整理本这一位是空格」。
    给不出 `COORD_MERGE_MIN_CELLS` 格就不认。"""
    L = len(text)
    kinds = [u.kind for _p, u in text]
    pos = [p for p, _u in text]
    n = len(units)
    if L < 4 or n < L - 1 or any(u.kind != "c" for u in units):
        return None                                     # 夹注列不走这条（a/b 合一格，并格语义不同）
    cands: list[tuple[int, int, int, float]] = []       # (吻合, j, m, 残差)
    for m in range(L - 1):
        if kinds[m] != "c" or kinds[m + 1] != "c" or pos[m + 1] != pos[m] + 1:
            continue
        tp = [float(p) for i, p in enumerate(pos) if i != m + 1]
        tp[m] = pos[m] + 0.5
        tk = [k for i, k in enumerate(kinds) if i != m + 1]
        ref_i = [i for i in range(L) if i != m + 1]
        for j in range(0, n - (L - 1) + 1):
            run = units[j:j + L - 1]
            if [u.kind for u in run] != tk:
                continue
            a, b = _fit_f(tp, [u.g for u in run])
            if a is None:
                continue
            resid = max(abs(u.g - (a * p + b)) for u, p in zip(run, tp))
            if resid > COORD_MAX_RESID:
                continue
            extras = units[:j] + units[j + L - 1:]
            if any(min(abs(u.g - (a * p + b)) for p in tp) <= COORD_OUTSIDE_MARGIN * a
                   for u in extras):
                continue
            ag = 0
            for t, (u, ri) in enumerate(zip(run, ref_i)):
                if t == m:
                    if u.carrier.get("", "") in (text[m][1].a, text[m + 1][1].a):
                        ag += 1
                else:
                    ag += _agree(u, text[ri][1])
            cands.append((ag, j, m, resid))
            if len(cands) > COORD_MAX_CANDIDATE_RUNS * 4:
                return None
    if not cands:
        return None
    best = max(c[0] for c in cands)
    if best < COORD_MERGE_MIN_AGREE:
        return None
    top = [c for c in cands if c[0] == best]
    j0 = top[0][1]
    if any(c[1] != j0 and c[0] >= best - 1 for c in cands):
        return None                                     # 起点有歧义
    # 共识：每个格，所有并列配法给的字都一致才给
    verdict: dict[int, set[str]] = {}
    for _ag, j, m, _r in top:
        ref_i = [i for i in range(L) if i != m + 1]
        for t in range(L - 1):
            ch = None if t == m else text[ref_i[t]][1].a
            verdict.setdefault(j + t, set()).add(ch if ch is not None else "\0merged")
    recs: list[tuple[str, int, str | None, str, float]] = []
    n_ref = 0
    for i, u in enumerate(units):
        vs = verdict.get(i)
        if vs is None:                                  # 段外假格：整理本这一位是空格
            ch = ""
        elif len(vs) == 1 and "\0merged" not in vs:
            ch = next(iter(vs))
            n_ref += 1
        else:
            continue                                    # 分不开 / 并格：不出记录
        recs.append((u.ids[""], u.slot, None, ch, u.g))
    if n_ref < COORD_MERGE_MIN_CELLS:
        return None
    return ColumnCoord(True, note=f"少一格共识（{len(top)} 种并格位置并列，吻合 {best}）",
                       recs=recs, agree=best, b=None, unique=False, merged=True)


def _fit_f(pos: list[float], g: list[float]) -> tuple[float | None, float]:
    """`_fit` 的浮点格位版（并格取中点）。字位 ＜ `COORD_SLOPE_MIN_N` 只拟偏移。"""
    n = len(pos)
    if n < COORD_SLOPE_MIN_N or max(pos) == min(pos):
        r = sorted(gi - p for gi, p in zip(g, pos))
        return 1.0, r[n // 2]
    mp, mg = sum(pos) / n, sum(g) / n
    a = sum((p - mp) * (gi - mg) for p, gi in zip(pos, g)) / sum((p - mp) ** 2 for p in pos)
    if not COORD_SLOPE[0] <= a <= COORD_SLOPE[1]:
        return None, 0.0
    return a, mg - a * mp


def coord_column(units: list[CellUnit], line: RefLine,
                 b_hint: float | None = None) -> ColumnCoord:
    """列内按坐标配字。整理本字位的**相对格位**（光盘版＝连续序号；逐列本＝daizhige
    格位，run 之间的空格位也算）决定每个字该落在哪一行；格按几何行号 `g` 排好，取一段
    与整理本字位数相同、类型逐个对得上的连续格，要求 `g − 格位` 近似常数（残差 ≤
    `COORD_MAX_RESID`）；段外的格（印章/污点假格）必须离每个字位都超过半行——它们对的
    是整理本的空格位，记 `ref_char=""`。

    几何上成立的配法不止一个时先比载体吻合数；还分不出且给了 `b_hint`（同页别的列量出来
    的「格位 → 行号」偏移，只在逐列本这种格位是绝对值的源上有意义）就取偏移最接近的。"""
    text = line.text_units()
    L = len(text)
    if L == 0:
        return ColumnCoord(False, "整理本行为空")
    if len(units) < L:
        return ColumnCoord(False, f"格数少于整理本字数（{len(units)} < {L}）")
    kinds = [u.kind for _p, u in text]
    pos = [p for p, _u in text]
    cands: list[tuple[int, int, float]] = []   # (吻合数, j, b)
    for j in range(0, len(units) - L + 1):
        run = units[j:j + L]
        if [u.kind for u in run] != kinds:
            continue
        a, b = _fit(pos, [u.g for u in run])
        if a is None or max(abs(u.g - (a * p + b)) for u, p in zip(run, pos)) > COORD_MAX_RESID:
            continue
        extras = units[:j] + units[j + L:]
        if any(min(abs(u.g - (a * p + b)) for p in pos) <= COORD_OUTSIDE_MARGIN * a
               for u in extras):
            continue
        cands.append((sum(_agree(u, r) for u, (_p, r) in zip(run, text)), j, b))
        if len(cands) > COORD_MAX_CANDIDATE_RUNS:
            return ColumnCoord(False, "几何上成立的配法太多")
    if not cands:
        return _merge_rescue(units, text) or ColumnCoord(
            False, f"格与整理本 {L} 字对不上（格数/类型/几何）")
    cands.sort(key=lambda t: (-t[0], t[1]))
    top = [c for c in cands if c[0] == cands[0][0]]
    if len(top) > 1 and b_hint is not None:
        top.sort(key=lambda t: abs(t[2] - b_hint))
        if abs(top[1][2] - b_hint) - abs(top[0][2] - b_hint) >= 0.5:
            top = top[:1]
    if len(top) > 1:
        return _merge_rescue(units, text) or ColumnCoord(
            False, f"有歧义（{len(cands)} 种配法，载体吻合 {top[0][0]} vs {top[1][0]}）", b=None)
    agree, j, b = top[0]
    # 错位闸：整列挪一格后载体吻合明显更高 → 这一列配错了位（vol01 p102 列6 职名页：
    # 「天文算法纂修官」整列往上错一格，载体「算法纂修」在下一格；页锚不上，没有现役
    # 对位可比，只能靠这条挡）。
    for dj in (-1, 1):
        sh = sum(_agree(units[i], text[i - j - dj][1]) for i in range(len(units))
                 if 0 <= i - j - dj < L and units[i].kind == text[i - j - dj][1].kind)
        if sh >= 2 and sh > agree:
            return ColumnCoord(False, f"错位（挪一格载体吻合 {sh} > {agree}）")
    recs: list[tuple[str, int, str | None, str, float]] = []
    for i, u in enumerate(units):
        ref = text[i - j][1] if j <= i < j + L else None
        if u.kind == "c":
            recs.append((u.ids[""], u.slot, None, ref.a if ref else "", u.g))
        else:
            for sub in ("a", "b"):
                if sub in u.ids:
                    ch = (ref.a if sub == "a" else ref.b) if ref else ""
                    recs.append((u.ids[sub], u.slot, sub, ch, u.g))
    return ColumnCoord(True, recs=recs, agree=agree, b=b, unique=len(cands) == 1)


def column_units(book: str, page: int, col: int, match_col, cells_col,
                 carrier_of) -> list[CellUnit]:
    """`glyph_match` 的一列（字格）+ `cells` 的一列（几何）→ 阅读顺序的格单元。

    只收 `glyph_match` 里有的格（Step3 判 blank 的格不在里面）；几何取 `cells`
    同 (slot, sub) 的 y 中心。查不到几何的格让整列放弃（返回空）。"""
    if cells_col is None or not cells_col.period:
        return []
    per = float(cells_col.period)
    top = float(cells_col.border_top or 0.0)
    geo = {(c.slot, c.sub or ""): ((c.y0 + c.y1) / 2.0 - top) / per + 0.5
           for c in cells_col.cells}
    by_slot: dict[int, CellUnit] = {}
    order: list[int] = []
    for r in match_col.chars:
        sub = r.sub or ""
        g = geo.get((r.slot, sub))
        if g is None:
            return []
        if sub:
            u = by_slot.get(r.slot)
            if u is None:
                u = CellUnit("n", r.slot, g, {}, {})
                by_slot[r.slot] = u
                order.append(r.slot)
            u.ids[sub] = r.id
            u.carrier[sub] = carrier_of(r.id) or ""
        else:
            by_slot[r.slot] = CellUnit("c", r.slot, g, {"": r.id}, {"": carrier_of(r.id) or ""})
            order.append(r.slot)
    units = [by_slot[s] for s in order]
    units.sort(key=lambda u: u.g)
    return units
