"""字表标准：把「字体 cmap ↔ Unicode」与 Unihan 异体字关系固化成两份表。

    python scripts/build_charset.py --unihan <解压后的 Unihan 目录> \
        [--font <字体.ttf> ...] [--corpus corpus/xxx.txt ...] [--ocr-dict]

Unihan 数据从 https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip 取，
解压后目录里要有 ``Unihan_Variants.txt``（异体字关系）与
``Unihan_IRGSources.txt``（全部已编码汉字，即 Unicode 的字表全集）。

产出（`config/charset/`）：

- ``charset.ranges.tsv`` —— 合法字表，按 **码位区间** 存（一行一个区间，
  ``起\t止\t来源``）。十万级的字表逐字存要 1.5MB 且几乎全是连续段，
  区间形式几千行就够，`charset.load_charset()` 负责展开。
- ``variants.tsv`` —— 异体字 → 正字（语义层），与既有手工表同格式，
  多一列 provenance 说明这条是哪来的。手工条目**永远覆盖**自动条目。
- ``report.json`` —— 各来源覆盖率与「本书有多少字落在字表外」。

## 为什么要有这份表

实测（`corpus/zongmu_wuyingdian_reference.txt`，341,166 字 / 4,593 字种）：
PP-OCR 的识别字表只有 6,625 项（其中汉字 6,270），**本书 11.01% 的字
根本不在字表里**——不是识别错，是压根输出不了。opencc 简→繁扩展把它
压到 1.79%，再加 Unihan 异体字扩展压到 1.20%。剩下的 1.20%（彖 詁 筮
帙 歟 弁 墀 禘 蓍 …）是没有简体对应、也没有异体字通路的**冷僻正字**，
任何字典式的扩展都够不着，只能靠「字体渲染模板 + 字形匹配」这一路。

所以这份表有两个互不相同的用途，别混起来：

1. **白名单**：候选里出现字表外的字 → 那多半是 s2t / 异体扩展造出来的
   垃圾，可以直接否掉；
2. **可达性上界**：字表覆盖不到的字，是排序再好也救不回来的**结构性
   天花板**。报识别准确率时必须把这个上界一起报，否则会把「字表不够」
   误诊成「排序不好」。

## 异体字边的取舍（这一节容易出事）

Unihan 的变体属性可靠性差别很大：

- ``kTraditionalVariant`` / ``kSimplifiedVariant``：简繁对应，正字法关系，
  安全；
- ``kSemanticVariant`` / ``kSpecializedSemanticVariant`` / ``kZVariant``：
  异体/古今字，本项目要的正是这一类（葢=蓋、畧=略、疎=疏、頴=穎），
  但也混着在古籍中并不通用的对应；
- ``kSpoofingVariant``：**形近易混字，不是异体字**（专为防钓鱼域名而设）。
  一律排除——把它当异体字会直接制造混淆。

即便排除了 spoofing，语义层合并仍有下游代价：`context_refine` 的「本版
用字习惯」会把同语义组里语料最常用的表面形**补进候选**。一条错误的
异体边，就等于往候选里注入一个错字。故默认 ``--restrict-to-corpus``：
只保留**至少一端在参考语料里出现过**的边——本书用不到的异体关系，
留着只有风险没有收益。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "config" / "charset"
HAND_VARIANTS = REPO / "config" / "dicts" / "variants.tsv"

# 采信的 Unihan 变体属性。kSpoofingVariant 是形近易混字，绝不能进。
VARIANT_PROPS = ("kSemanticVariant", "kSpecializedSemanticVariant",
                 "kZVariant", "kTraditionalVariant", "kSimplifiedVariant")

CJK_BLOCKS = [
    (0x3400, 0x4DBF, "ExtA"), (0x4E00, 0x9FFF, "URO"),
    (0xF900, 0xFAFF, "Compat"), (0x20000, 0x2A6DF, "ExtB"),
    (0x2A700, 0x2B73F, "ExtC"), (0x2B740, 0x2B81F, "ExtD"),
    (0x2B820, 0x2CEAF, "ExtE"), (0x2CEB0, 0x2EBEF, "ExtF"),
    (0x2EBF0, 0x2EE5F, "ExtI"), (0x2F800, 0x2FA1F, "CompatSup"),
    (0x30000, 0x3134F, "ExtG"), (0x31350, 0x323AF, "ExtH"),
    (0x323B0, 0x3347F, "ExtJ"),
]
_CP_RE = re.compile(r"U\+([0-9A-Fa-f]+)")


def is_cjk(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi, _ in CJK_BLOCKS)


def block_of(cp: int) -> str:
    for lo, hi, name in CJK_BLOCKS:
        if lo <= cp <= hi:
            return name
    return "other"


# ── 来源读取 ────────────────────────────────────────────

def read_unihan_variants(path: Path) -> tuple[dict[str, set[str]], set[int]]:
    """Unihan_Variants.txt → (无向异体图, 出现过的码位集合)。"""
    graph: dict[str, set[str]] = defaultdict(set)
    seen: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        cp_s, prop, val = parts
        cp = int(cp_s[2:], 16)
        seen.add(cp)
        if prop not in VARIANT_PROPS:
            continue
        a = chr(cp)
        for tok in val.split():
            m = _CP_RE.match(tok)
            if not m:
                continue
            b = chr(int(m.group(1), 16))
            if a == b:
                continue
            graph[a].add(b)
            graph[b].add(a)
    return graph, seen


def read_unihan_repertoire(path: Path) -> set[int]:
    """Unihan_IRGSources.txt → 全部已编码汉字码位。

    不能拿 ``Unihan_Variants.txt`` 里出现过的码位当字表全集——那份文件
    只收「有异体关系的字」（1.6 万），会把字表规模少算六倍。
    """
    cps: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        cp_s = line.split("\t", 1)[0]
        if cp_s.startswith("U+"):
            cps.add(int(cp_s[2:], 16))
    return cps


def read_font_cmap(path: Path) -> set[int]:
    """字体 cmap → 码位集合。只读映射表，不碰任何字形外框。

    这一步刻意只取 cmap：码位表是**事实数据**，字形外框才是受版权保护的
    表达。商业字体可以拿来当字表来源，但它的外框不该进这个仓库。
    """
    from fontTools.ttLib import TTFont
    font = TTFont(str(path), fontNumber=0, lazy=True)
    cps: set[int] = set()
    for table in font["cmap"].tables:
        cps.update(table.cmap.keys())
    font.close()
    return cps


def read_ocr_dict() -> set[int]:
    from rapidocr_onnxruntime import RapidOCR
    return {ord(c) for c in RapidOCR().text_rec.postprocess_op.character
            if len(c) == 1}


def read_corpus(paths: list[Path]) -> Counter:
    cnt: Counter = Counter()
    for p in paths:
        for f in (sorted(p.glob("**/*.txt")) if p.is_dir() else [p]):
            for ch in f.read_text(encoding="utf-8"):
                if is_cjk(ord(ch)):
                    cnt[ch] += 1
    return cnt


# ── 区间编码 ────────────────────────────────────────────

def to_ranges(cps: set[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for cp in sorted(cps):
        if out and cp == out[-1][1] + 1:
            out[-1] = (out[-1][0], cp)
        else:
            out.append((cp, cp))
    return out


# ── 正字选择 ────────────────────────────────────────────

def pick_orthodox(group: set[str], corpus_freq: Counter,
                  simplified: set[str]) -> str:
    """从一个异体字组里挑正字（语义层的代表）。

    优先级：**语料频次** > 非简体 > 码位小（URO 优先于扩展区）。
    以语料频次为首要判据，是因为语义层代表的唯一用途是给语言模型
    做统计——用本版最常写的那个形做代表，n-gram 的计数才不会被
    同一个词分散到几个表面形上。
    """
    return sorted(group, key=lambda c: (-corpus_freq.get(c, 0),
                                        c in simplified, ord(c)))[0]


def read_hand_variants(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] and parts[1]:
            out[parts[0]] = parts[1]
    return out


def connected_groups(graph: dict[str, set[str]],
                     keep: set[str] | None) -> list[set[str]]:
    """异体图的连通分量。keep 非空时只保留至少一端在 keep 里的边。"""
    adj: dict[str, set[str]] = defaultdict(set)
    for a, bs in graph.items():
        for b in bs:
            if keep is not None and a not in keep and b not in keep:
                continue
            adj[a].add(b)
            adj[b].add(a)
    seen: set[str] = set()
    groups: list[set[str]] = []
    for start in adj:
        if start in seen:
            continue
        comp, stack = set(), [start]
        while stack:
            n = stack.pop()
            if n in comp:
                continue
            comp.add(n)
            stack.extend(adj[n] - comp)
        seen |= comp
        if len(comp) > 1:
            groups.append(comp)
    return groups


def main() -> None:
    ap = argparse.ArgumentParser(description="构建字表标准与异体字表")
    ap.add_argument("--unihan", required=True,
                    help="解压后的 Unihan 目录（含 _Variants / _IRGSources）")
    ap.add_argument("--font", action="append", default=[],
                    help="字体文件（可重复）；只读 cmap，不提取字形")
    ap.add_argument("--corpus", action="append", default=[],
                    help="参考语料文件或目录（可重复）")
    ap.add_argument("--ocr-dict", action="store_true",
                    help="把当前 OCR 引擎的识别字表也计入来源")
    ap.add_argument("--restrict-to-corpus", action="store_true", default=True,
                    help="异体字边只保留至少一端在语料中出现过的（默认开）")
    ap.add_argument("--all-variants", dest="restrict_to_corpus",
                    action="store_false", help="保留全部异体字边（有风险）")
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    unihan_dir = Path(args.unihan)
    if unihan_dir.is_file():          # 兼容直接传 Unihan_Variants.txt
        unihan_dir = unihan_dir.parent
    graph, _ = read_unihan_variants(unihan_dir / "Unihan_Variants.txt")
    repertoire_file = unihan_dir / "Unihan_IRGSources.txt"
    corpus_freq = read_corpus([Path(p) for p in args.corpus])

    sources: dict[str, set[int]] = {}
    if repertoire_file.exists():
        sources["unihan"] = {c for c in read_unihan_repertoire(repertoire_file)
                             if is_cjk(c)}
    for f in args.font:
        name = f"font:{Path(f).stem}"
        sources[name] = {c for c in read_font_cmap(Path(f)) if is_cjk(c)}
    font_names = [k for k in sources if k.startswith("font:")]
    if len(font_names) > 1:
        # 字体家族常按平面拆成多个文件（如 BMP 一档、扩充区一档），
        # 逐档报覆盖率会得出「扩充区那档漏了 99% 常用字」这种荒唐结论。
        # 家族的字表是各档的并集。
        union: set[int] = set()
        for k in font_names:
            union |= sources[k]
        sources["font:*"] = union
    if args.ocr_dict:
        sources["ocr"] = {c for c in read_ocr_dict() if is_cjk(c)}
    if corpus_freq:
        sources["corpus"] = {ord(c) for c in corpus_freq}

    # ── charset.ranges.tsv ──
    lines = ["# 合法字表（码位区间）。列：起\t止\t来源"]
    for name, cps in sorted(sources.items()):
        for lo, hi in to_ranges(cps):
            lines.append(f"U+{lo:04X}\tU+{hi:04X}\t{name}")
    (out_dir / "charset.ranges.tsv").write_text("\n".join(lines) + "\n",
                                                encoding="utf-8")

    # ── variants.tsv ──
    simplified = set()
    try:
        import sys
        sys.path.insert(0, str(REPO))
        from open_guji_cv.clustering.candidates import _load_s2t
        s2t = _load_s2t()
        simplified = {s for s, forms in s2t.items() if s not in forms}
    except Exception:
        pass

    keep = set(corpus_freq) if (args.restrict_to_corpus and corpus_freq) else None
    groups = connected_groups(graph, keep)
    hand = read_hand_variants(HAND_VARIANTS)

    auto: dict[str, tuple[str, str]] = {}
    for g in groups:
        head = pick_orthodox(g, corpus_freq, simplified)
        for c in g:
            if c != head:
                auto[c] = (head, "unihan")
    n_auto = len(auto)
    # 手工条目永远覆盖：它们是人工确认过的，自动表无权改判
    for c, head in hand.items():
        auto[c] = (head, "hand")

    vlines = [
        "# 异体字 → 正字（语义层映射，仅供语言模型与阅读辅助）。",
        "# 格式：异体字\t正字\t来源。字形层标签永远保留精确异体字形，绝不按此表合并。",
        f"# 自动来源：Unihan {'/'.join(VARIANT_PROPS)}（已排除 kSpoofingVariant）。",
        f"# 语料限定：{'是' if keep else '否'}；手工条目覆盖自动条目。",
    ]
    for c in sorted(auto):
        head, origin = auto[c]
        vlines.append(f"{c}\t{head}\t{origin}")
    (out_dir / "variants.tsv").write_text("\n".join(vlines) + "\n",
                                          encoding="utf-8")

    # ── report.json：本书落在各字表外的比例（可达性上界）──
    total_tokens = sum(corpus_freq.values())
    coverage = {}
    for name, cps in sources.items():
        if name == "corpus" or not corpus_freq:
            continue
        miss_types = [c for c in corpus_freq if ord(c) not in cps]
        miss_tokens = sum(corpus_freq[c] for c in miss_types)
        coverage[name] = {
            "charset_size": len(cps),
            "corpus_oov_types": len(miss_types),
            "corpus_oov_type_rate": round(len(miss_types) / len(corpus_freq), 4),
            "corpus_oov_tokens": miss_tokens,
            "corpus_oov_token_rate": round(miss_tokens / total_tokens, 4),
            "top_oov": "".join(c for c, _ in Counter(
                {c: corpus_freq[c] for c in miss_types}).most_common(30)),
        }
    report = {
        "sources": {k: len(v) for k, v in sources.items()},
        "corpus_types": len(corpus_freq),
        "corpus_tokens": total_tokens,
        "variant_groups": len(groups),
        "variant_entries_auto": n_auto,
        "variant_entries_hand": len(hand),
        "coverage": coverage,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
