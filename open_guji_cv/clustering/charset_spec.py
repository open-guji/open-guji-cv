# -*- coding: utf-8 -*-
"""候选字表的**册级配置**：基集 + 阶梯 + 白名单。

## 为什么要有这个模块（2026-09-17）

此前候选字表只有一个来源：**本册证人整理本的用字**
（`font_candidates.book_charset` → `rare_panel._rare_charsets`）。
整理本一缺字、或者压根没有整理本，候选池就塌——北行日錄刻本的证人是
**同书异版**（现代排印本《攻媿集》），「甫 鳥 扣 斲」在校对本里出现 **0 次**，
于是 22.5% 的正确答案压根不在候选池里，top-10 查不到就是查不到，
排序再好也救不回来（`scripts/build_charset.py` 模块头管这叫**可达性上界**）。

所以字表来源要能按册配：

- **有整理本且用字齐**（四庫總目那种，8,827 字种、同书整理本）→ 照旧用整理本；
- **没整理本 / 整理本是异版**（北行刻本）→ 用 Unicode 区段基集兜底；
- **现代排印本** → GBK / 台湾正体这类现代字表更贴题，扩B 那些罕见异写只会添乱。

## 三件事，别混起来

| | 是什么 | 谁在用 |
|---|---|---|
| **基集 `base`** | 候选**能出现**的字的全集（可达性上界） | `_rare_charsets` |
| **阶梯 `escalate`** | 基集之外、分数低时**追加**的一档（不是替换） | `rare_for_batch` |
| **白名单 `allow`** | 候选里**不该出现**的字（简体/现代字）的否决表 | `filter_candidates` |

## 阶梯为什么是「并集」而不是「替换」（实测）

北行 383 条用户裁决实测，扩B 加进来：top-10 94.5 → 96.6（+2.1），
但 top-1 82.0 → 79.9（**−2.1**）。扩B 里全是常用字的罕见异写，形状极近
**且得分更高**：

    金标 斲 → T1 首选 斲(0.816) → 加扩B 后首选 𣂪(0.831)
    金标 言 → T1 首选 言(0.818) → 加扩B 后首选 𧥜(0.832)

抢答 10 例、救回 2 例，净亏 8 例。

⚠️ **「最高分低才升级」这个判据单独用不成立**——实测 T1 top-1 分数分布
命中 p10=0.798、未命中 p90=0.896，两个分布严重重叠，没有阈值能分开。

成立的做法是**并集 + 按分数归并**：分数低时把升级档候选并进来，
与基集候选**同台按余弦分排序**，基集候选仍在列表里。这样抢答不发生
（基集首选凭分数留在原位），救回照样发生。

⚠️ **归并方式是关键，拼接不行**（2026-09-17 实测）：先做的是
`emb + extra` 直接拼在后面，结果阈值从 0.80 扫到 1.0 **一个点都不涨**——
RRF 只看**名次**，拼在后面的升级档一律从第 11 位起，权重 `4/(60+10)` 打到底；
金标明明在升级档的第 2~3 名（𠊓 𨕖 𠀉 实测都在）也挤不进最终 top-10。

阈值扫描（北行 383 条用户裁决，基集 `unicode-cjk-a`+corpus+variants 29,360 字、
升级档 42,716 字，真实余弦分归并）：

| 阈值 | 升级率 | top-1 | top-10 |
|---|---|---|---|
| 不升级 | 0% | 75.5% | 94.3% |
| 0.80 | 15.7% | 75.7% | 95.6% |
| **0.85** | **43.1%** | **76.8%** | **96.3%** |
| 0.90 | 88.0% | 78.9% | 96.1% |
| 全升级 | 100% | 79.6% | 96.1% |

**0.85 是甜点**：top-10 最高，且 top-1 比不升级还高 1.3 点。
⚠️ 这个数是**在这套基集上**标的——换 `base`（比如改成 `kangxi` 或加
`unicode-compat`）分数分布会变，要重标，别抄。

## 白名单：能挡住东西的判据只有一个（实测订正）

盘过仓里三档现成字表对全量语料的 OOV：

| 档 | 来源 | 字数 | 语料 OOV |
|---|---|---|---|
| 宽 | `config/ids/ids_lv1.txt` | 102,032 | **0 / 0** |
| 中 | `fonts/jigmo/*.ttf` cmap | 98,682 | **0 / 0** |
| 严 | `config/kangxi/kirgkangxi.tsv` | 70,228 | 50 字种 / 0.04% 字次 |

前两档 OOV 全是 0——**它们挡不住任何东西**。真正的垃圾候选不是
「不在 Unicode 里的字」，而是 s2t/异体扩展造出来的**简体字**。

⚠️ 原本打算用 kangxi 那档（以为康熙字典天然不含简体），**实测是错的**：
「国 学 体 这 说 为 无」全在表里且都带康熙页码（`U+56FD	国	0218.041`）——
康熙收了大量后来被选作简化字的古字/俗字。

真正有判别力的是 **OpenCC 的简繁判据**：`s2t(ch) != ch` ⇒ 该字是简体。
实测精确：国/学/体/为/无 判真；這/說/國/學/體/甫/鳥/斲/之/人 判假，
罕见字与扩B 字一律判假、不误伤。故白名单做成 `no-simplified` 模式，
并留 `keep`（本册语料用过的字）无条件放行兜底。

"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 内置基集。值是 (起, 止) 码位区间列表，闭区间。
#: 取名尽量贴 Unicode 的官方块名，别自造缩写。
BASE_RANGES: dict[str, list[tuple[int, int]]] = {
    # 古籍默认档：基本区 + 扩A。27,584 字。
    # 覆盖绝大多数刻本用字，且**不含扩B 那批常用字的罕见异写**（抢答的元凶）。
    "unicode-cjk-a": [(0x4E00, 0x9FFF), (0x3400, 0x4DBF)],
    # 全档：+ 扩B 42,720 字 = 70,304。一般不直接用它当 base，
    # 而是把扩B 放 `escalate`（见模块头）。
    "unicode-cjk-ab": [(0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x20000, 0x2A6DF)],
    # 只有扩B，给 `escalate` 用。
    "unicode-ext-b": [(0x20000, 0x2A6DF)],
    # 兼容汉字区，个别刻本会用到。
    "unicode-compat": [(0xF900, 0xFAFF)],
}

#: 文件型基集：值是仓内相对路径。这些是**逐字表**，不是区间。
BASE_FILES: dict[str, str] = {
    # 康熙字典收字（Unihan kIRG_KangXi），70,228 字。
    # ⚠️ 它**含简体**（国 学 体 这 说 都在，带康熙页码）——康熙收了大量后来
    # 被选作简化字的古字/俗字。要挡简体请用 allow: no-simplified，别指望这份表。
    "kangxi": "config/kangxi/kirgkangxi.tsv",
    # Unicode 编过码的汉字全集（IDS 表首列），102,032 字，MIT。
    "unicode-all": "config/ids/ids_lv1.txt",
}

#: 白名单/否决档位。
#:
#: ⚠️ **2026-09-17 实测订正**：原以为 `kirgkangxi.tsv`（康熙收字）天然不含简体，
#: 可以拿它当「刻本用字白名单」——**是错的**。实测「国 学 体 这 说 为 无」
#: 全在表里且都带康熙页码（`U+56FD\t国\t0218.041`）。康熙字典收了大量后来被
#: 选作简化字的古字/俗字，所以它**挡不住简体**。
#:
#: 真正有判别力的是 OpenCC 的简繁判据：`s2t(ch) != ch` ⇒ 这个字是简体
#: （有对应繁体形式）。实测精确：国/学/体 判真，這/說/國/學/甫/鳥/斲/之/人 判假。
ALLOW_MODES = ("none", "no-simplified", "charset")
"""- `none`：不过滤；
- `no-simplified`：**推荐**，否决简体字（繁体刻本用）；
- `charset`：用 `allow_charset_file` 指定的逐字表当白名单（几乎挡不住东西，
  见模块头三档 OOV 实测，留作特殊需要）。"""

#: `charset` 模式的可选来源。
ALLOW_SOURCES: dict[str, str] = {
    "kangxi": "config/kangxi/kirgkangxi.tsv",
    "unicode-all": "config/ids/ids_lv1.txt",
}

#: 册配置没写 `font.charset` 时，按 `edition` 取的默认档。
#: 刻本走 Unicode 区段（整理本常常是异版或缺席），现代排印本走康熙以外的现代字表
#: ——但现代链暂时也用 unicode-cjk-a，等有现代书的实测数据再细分（别凭空写）。
DEFAULT_BY_EDITION: dict[str, str] = {
    "keben": "unicode-cjk-a",
    "modern_body": "unicode-cjk-a",
}

#: 册配置没写 `font.charset.allow` 时，按 `edition` 取的默认否决档。
#: 繁体刻本默认开简体否决——s2t/异体扩展会把简体塞进候选，而刻本不可能印简体。
#: 现代排印本可能真的是简体排印，默认不过滤。
DEFAULT_ALLOW_BY_EDITION: dict[str, str] = {
    "keben": "no-simplified",
    "modern_body": "none",
}

#: 阶梯默认阈值：基集 top-1 余弦低于它才追加升级档。实测甜点，见模块头。
DEFAULT_ESCALATE_THRESHOLD = 0.85


def _cjk(ch: str) -> bool:
    return ("㐀" <= ch <= "鿿") or ("\U00020000" <= ch <= "\U0002ffff") \
        or ("豈" <= ch <= "﫿")


@lru_cache(maxsize=8)
def _load_file_charset(rel: str) -> tuple[str, ...]:
    """读逐字表文件。兼容三种行格式，取每行**第一个 CJK 字**。

    - `config/ids/ids_lv1.txt`：`㐀\t...` 首列就是字；
    - `config/kangxi/kirgkangxi.tsv`：`U+3400\t㐀\t0078.010` 字在第二列。

    所以不能只认某一列，逐行找第一个 CJK 字最稳。
    """
    p = REPO_ROOT / rel
    if not p.exists():
        raise FileNotFoundError(f"字表文件不存在: {p}")
    out: list[str] = []
    seen: set[str] = set()
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line or line.startswith("#"):
            continue
        for ch in line:
            if _cjk(ch):
                if ch not in seen:
                    seen.add(ch)
                    out.append(ch)
                break          # 每行只取一个字
    return tuple(out)


@lru_cache(maxsize=16)
def base_charset(name: str) -> tuple[str, ...]:
    """基集名 → 字表元组。**返回值按名字记忆化**，元组身份稳定——
    `cnn_candidates._emb_index` 与 `font_candidates._index` 的缓存都按
    charset 的对象身份/值命中，每次现拼新元组会让索引反复重建（8 分钟一次）。
    """
    if name in BASE_RANGES:
        return tuple(chr(c) for lo, hi in BASE_RANGES[name] for c in range(lo, hi + 1))
    if name in BASE_FILES:
        return _load_file_charset(BASE_FILES[name])
    raise ValueError(f"未知基集 {name!r}；可用: "
                     f"{sorted(set(BASE_RANGES) | set(BASE_FILES))}")


@lru_cache(maxsize=4)
def _s2t():
    """OpenCC 简→繁转换器；装不上就返回 None（降级为不过滤，并出声）。"""
    try:
        import opencc
        return opencc.OpenCC("s2t")
    except Exception:
        import warnings
        warnings.warn("opencc 不可用，简体否决（no-simplified）降级为不过滤。",
                      RuntimeWarning, stacklevel=3)
        return None


@lru_cache(maxsize=1 << 16)
def is_simplified(ch: str) -> bool:
    """这个字是不是简体（有对应的繁体形式）。

    判据 `s2t(ch) != ch`。实测（2026-09-17）：
    国/学/体/为/无 → True；這/說/國/學/體/甫/鳥/斲/之/人 → False。
    罕见字与扩B 字一律 False，不会误伤。
    """
    cc = _s2t()
    if cc is None or not ch:
        return False
    try:
        return cc.convert(ch) != ch
    except Exception:
        return False


@lru_cache(maxsize=8)
def allow_charset(name: str) -> frozenset[str] | None:
    """`charset` 模式的白名单表；未配置来源返回 None。"""
    rel = ALLOW_SOURCES.get(name)
    if rel is None:
        return None
    return frozenset(_load_file_charset(rel))


def spec_for_book(book: str | None, edition: str = "keben") -> dict:
    """册配置 `font.charset` → 规格化后的字表规格。

    yaml 写法（全部可省，省了走 `DEFAULT_BY_EDITION`）::

        font:
          charset:
            base: unicode-cjk-a     # 基集，见 BASE_RANGES / BASE_FILES
            escalate: unicode-ext-b # 分数低时追加的一档；null = 不做阶梯
            escalate_threshold: 0.85
            corpus: true            # 叠加本册整理本用字（有就吃，没有不报错）
            variants: true          # 叠加异体展开
            allow: no-simplified    # 简体否决（繁体刻本推荐）；none = 不过滤
            extra: [甫, 鳥]          # 手工补字

    **`corpus` 从「唯一来源」降级成「叠加项」**——这是本次改造的要点。
    整理本仍有独立价值（给 `freq` 排序与 `std` 正字提示），
    但不该决定**能不能查到**。
    """
    cfg: dict = {}
    if book:
        try:
            from ..core.book import load_book
            b = load_book(book)
            cfg = dict(((b.font or {}).get("charset")) or {})
            edition = b.edition or edition
        except Exception:
            cfg = {}
    base = cfg.get("base") or DEFAULT_BY_EDITION.get(edition, "unicode-cjk-a")
    esc = cfg.get("escalate", "unicode-ext-b")
    return {
        "base": base,
        "escalate": esc or None,
        "escalate_threshold": float(cfg.get("escalate_threshold",
                                            DEFAULT_ESCALATE_THRESHOLD)),
        "corpus": bool(cfg.get("corpus", True)),
        "variants": bool(cfg.get("variants", True)),
        "allow": cfg.get("allow") or DEFAULT_ALLOW_BY_EDITION.get(edition, "none"),
        "extra": list(cfg.get("extra") or []),
    }


@lru_cache(maxsize=8)
def _corpus_chars(corpus: str | None) -> tuple[str, ...]:
    if not corpus or not Path(corpus).exists():
        return ()
    from .font_candidates import book_charset
    return tuple(book_charset(corpus))


@lru_cache(maxsize=8)
def build_charsets(base: str, escalate: str | None, corpus: str | None,
                   use_corpus: bool, use_variants: bool,
                   extra: tuple[str, ...] = ()) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """→ `(基集字表, 升级档字表)`，都已含 corpus/variants/extra 叠加。

    升级档 = `escalate` 基集的字 **减去**基集已有的（只留增量，
    RRF 融合时才知道哪些是「追加进来的」）。`escalate` 为 None 时返回空元组。

    ⚠️ 参数全是可哈希的标量/元组：`lru_cache` 要命中，返回的元组身份才稳定，
    下游 `_emb_index` 的索引才不会每页重建。
    """
    base_set = set(base_charset(base))
    esc_set = {c for c in base_charset(escalate)} if escalate else set()

    cs = set(base_set)
    if use_corpus:
        cs.update(_corpus_chars(corpus))
    cs.update(extra)

    # ⚠️ **异体展开的产物必须留在基集的区段内**（2026-09-17 实测订正）。
    # 第一版直接把 `variants_of` 的结果无条件并进基集——实测 `unicode-cjk-a`
    # 27,584 字展开后新增 20,348 字，其中 **17,584 个是扩B**，等于把整个升级档
    # 抬进了基集，阶梯完全被架空（基集 27,584 → 46,942，升级档只剩 25,134）。
    # 现在：异体产物落在升级档区段的，**归升级档**，不进基集。
    if use_variants:
        try:
            from ..variants import variants_of
            spill: set[str] = set()
            for ch in list(cs):
                for v in (variants_of(ch) or ()):
                    vv = v[0] if isinstance(v, (tuple, list)) else v
                    if vv in base_set or vv in cs:
                        continue
                    (spill if vv in esc_set else cs).add(vv)
            esc_set |= spill
        except Exception:
            pass

    cs = {c for c in cs if _cjk(c)}
    esc = {c for c in esc_set if _cjk(c)} - cs
    return tuple(sorted(cs)), tuple(sorted(esc))


def filter_candidates(cands: list, allow: str, keep: frozenset[str] = frozenset()):
    """按 `allow` 模式剔除不该出现的候选。

    `keep` 是**无条件放行集**（本册语料真实用过的字）——判据再准也可能有
    例外（某些刻本确实印了后来的简化字形），语料是这本书自己的证据，优先。

    `cands` 是 `[{"char": ...}, ...]` 或 `[(char, score), ...]`，两种都吃。
    """
    if allow == "none":
        return cands

    def _ch(c):
        # 三种形状都要吃：dict（_fuse 的输出）、(char, score) 元组（CNN/库两路）、
        # FontHit 数据类（HOG 那路，有 .char 属性）。
        if isinstance(c, dict):
            return c.get("char")
        if isinstance(c, (tuple, list)):
            return c[0] if c else None
        return getattr(c, "char", c)

    if allow == "no-simplified":
        return [c for c in cands
                if (not _ch(c)) or _ch(c) in keep or not is_simplified(_ch(c))]

    al = allow_charset(allow)
    if al is None:
        return cands
    return [c for c in cands if (not _ch(c)) or _ch(c) in keep or _ch(c) in al]
