# -*- coding: utf-8 -*-
"""hanzi 库的表结构、关系类型与来源登记（总设计 §6）。

规范形是排好序、逐字节可复现的 tsv；sqlite 由它们在各机本地灌出，只为查得快，不分发。
每张表的列序就是 tsv 的列序。分两个包（总设计 §6.1，10-19 晚用户定）：

- **核心包**（关系边、未编码形、来源登记；形近对直接读 `config/ids/` 的两张表）：tsv 进 git
  `config/hanzi/core/`，云会话克隆完就能用；
- **部件包**（字属性、主套 IDS、直接部件）：按 sha 进 R2，第一次用到部件检索时才拉。
"""
from __future__ import annotations

#: 表 → 列。tsv 不带表头，列序以此为准；sqlite 的列名同此。
TABLES: dict[str, tuple[str, ...]] = {
    "sources": ("src", "name", "url", "license", "tier", "note"),
    "chars": ("ch", "cp", "block", "rs", "strokes", "kangxi", "def"),
    "forms": ("key", "regular", "src", "ref"),
    "edges": ("a", "b", "rel", "directed", "src", "sense", "ref", "note"),
    "ids": ("ch", "src", "seq", "regions"),
    "comps": ("ch", "part", "depth", "folded"),
    "near": ("a", "b", "src", "kind", "score", "detail", "ln"),
}

#: 整数列（tsv 里是十进制文本，sqlite 里是 INTEGER）。
INT_COLS = {"cp", "directed", "depth", "folded", "ln", "strokes"}
#: 实数列。
REAL_COLS = {"score"}

#: 包 → 表。两个包各灌一个 sqlite（`core.sqlite`、`parts.sqlite`），查询时把部件库 ATTACH 上。
PACKS: dict[str, tuple[str, ...]] = {
    "core": ("sources", "edges", "forms", "near"),
    "parts": ("chars", "ids", "comps"),
}

INDEXES: dict[str, tuple[str, ...]] = {
    "edges": ("CREATE INDEX edges_a ON edges(a)", "CREATE INDEX edges_b ON edges(b)"),
    "near": ("CREATE INDEX near_a ON near(a)", "CREATE INDEX near_b ON near(b)"),
    "forms": ("CREATE INDEX forms_regular ON forms(regular)",),
    "chars": ("CREATE UNIQUE INDEX chars_ch ON chars(ch)",),
    "ids": ("CREATE INDEX ids_ch ON ids(ch)", "CREATE INDEX ids_seq ON ids(seq)"),
    "comps": ("CREATE INDEX comps_part ON comps(part, ch)", "CREATE INDEX comps_ch ON comps(ch)"),
}

#: 形近对不进包：本机灌库时直接读这两张已在 git 里的表（清单里记 sha，对不上就去 R2 取那一版）。
NEAR_FILES: dict[str, str] = {
    "near:v1": "config/ids/confusable_pairs_v1.tsv",
    "near:ids-v1": "config/ids/ids_confusable_pairs_v1.tsv",
}

# ── 关系类型（edges.rel）────────────────────────────────
#: 来源说是异体。
VARIANT = "variant"
#: 只在部分义项同（kSpecializedSemanticVariant）。
VARIANT_PARTIAL = "variant_partial"
#: 字形微差、同字（kZVariant）。
Z = "z"
#: 简繁：a 繁、b 简。只作关系证据，对繁体刻本方向是反的，不当桥。
SIMP = "simp"
#: 部件對應／类推（部件檢索 rt 里不带 ~ 的那段），来源没细分是异体还是简化类推。
RELATED = "related"
#: 通假：不同的词，永不当异体。
BORROW = "borrow"
#: 形近易混（kSpoofingVariant，防钓鱼域名用的），永不当异体。
SPOOF = "spoof"
#: 人审定「永不并组」（never_group.json）：负边。
DISTINCT = "distinct"

RELS = (VARIANT, VARIANT_PARTIAL, Z, SIMP, RELATED, BORROW, SPOOF, DISTINCT)

#: `family()` 缺省走的关系：宁多勿少的候选池，但不含通假、钓鱼形近、简繁、负边。
FAMILY_RELS = frozenset({VARIANT, VARIANT_PARTIAL, Z, RELATED})

# ── 现役标签（config/variants/variants.json 用的）─────────────────
#: `export_variants_json` 只导这些来源，保证与 scripts/build_variants.py 同口径。
LEGACY_TAGS = frozenset({
    "unihan:kSemanticVariant", "unihan:kSpecializedSemanticVariant", "unihan:kZVariant",
    "unihan:kSimplifiedVariant", "unihan:kTraditionalVariant", "unihan:kSpoofingVariant",
    "twedu", "hydzd", "hydzd-borrowed", "dypytz", "cjkvi-simplified", "yitizi",
})
#: 现役 `directed` 段收的来源（另加 local:*）。
LEGACY_DIRECTED_TAGS = frozenset({
    "twedu", "hydzd", "dypytz", "cjkvi-simplified",
    "unihan:kSimplifiedVariant", "unihan:kTraditionalVariant",
})
#: 现役 `variant_sources.ours()` 去掉的来源。
LEGACY_NEVER_TAGS = frozenset({"unihan:kSpoofingVariant", "hydzd-borrowed"})

# ── 来源登记 ────────────────────────────────────────────
# tier：open 可商用／nc 非商业／unclear 无 LICENSE／own 本项目／fact-ref 针对性查询所得事实。
# 用户 2026-10-19 定：关系是事实，tier 只作出处标注与日后对外打包的过滤键，不挡导入（总设计 §3）。
UNIHAN_URL = "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip"
CJKVI_BASE = "https://raw.githubusercontent.com/cjkvi/cjkvi-variants/master/"
YIBAI_BASE = "https://raw.githubusercontent.com/yi-bai/ids/master/"
YITIZI_URL = "https://cdn.jsdelivr.net/npm/yitizi@0.1.3/index.js"
CHARCOMP_BASE = "https://raw.githubusercontent.com/frankslin/char-components/main/web/data/"

SOURCES: dict[str, dict[str, str]] = {
    "unihan:kSemanticVariant": {"name": "Unihan kSemanticVariant", "url": UNIHAN_URL,
                                "license": "Unicode License v3", "tier": "open"},
    "unihan:kSpecializedSemanticVariant": {"name": "Unihan kSpecializedSemanticVariant",
                                           "url": UNIHAN_URL, "license": "Unicode License v3",
                                           "tier": "open"},
    "unihan:kZVariant": {"name": "Unihan kZVariant", "url": UNIHAN_URL,
                         "license": "Unicode License v3", "tier": "open"},
    "unihan:kSimplifiedVariant": {"name": "Unihan kSimplifiedVariant", "url": UNIHAN_URL,
                                  "license": "Unicode License v3", "tier": "open"},
    "unihan:kTraditionalVariant": {"name": "Unihan kTraditionalVariant", "url": UNIHAN_URL,
                                   "license": "Unicode License v3", "tier": "open"},
    "unihan:kSpoofingVariant": {"name": "Unihan kSpoofingVariant（形近，非异体）", "url": UNIHAN_URL,
                                "license": "Unicode License v3", "tier": "open"},
    "unihan": {"name": "Unihan 码位属性", "url": UNIHAN_URL,
               "license": "Unicode License v3", "tier": "open"},
    "twedu": {"name": "cjkvi-variants twedu（台湾教育部異體字字典）",
              "url": CJKVI_BASE + "twedu-variants.txt", "license": "无 LICENSE（版权声明）",
              "tier": "unclear"},
    "hydzd": {"name": "cjkvi-variants hydzd（漢語大字典）",
              "url": CJKVI_BASE + "hydzd-variants.txt", "license": "无 LICENSE（版权声明）",
              "tier": "unclear"},
    "hydzd-borrowed": {"name": "cjkvi-variants hydzd-borrowed（漢語大字典 通假）",
                       "url": CJKVI_BASE + "hydzd-borrowed.txt", "license": "无 LICENSE（版权声明）",
                       "tier": "unclear"},
    "dypytz": {"name": "cjkvi-variants dypytz（第一批异体字整理表）",
               "url": CJKVI_BASE + "dypytz-variants.txt", "license": "无 LICENSE（版权声明）",
               "tier": "unclear"},
    "cjkvi-simplified": {"name": "cjkvi-variants 简繁", "url": CJKVI_BASE + "cjkvi-simplified.txt",
                         "license": "无 LICENSE（版权声明）", "tier": "unclear"},
    "yitizi": {"name": "nk2028/yitizi 0.1.3", "url": YITIZI_URL,
               "license": "两份文档记 CC0／MIT 不一致", "tier": "unclear"},
    "charcomp:rt": {"name": "部件檢索 rt（中研院漢字構形資料庫等整理）", "url": CHARCOMP_BASE + "rt.jsonl",
                    "license": "部件檢索公開授權（非商业，须标注来源）", "tier": "nc"},
    "charcomp:vt": {"name": "部件檢索 vt 部件变体折叠", "url": CHARCOMP_BASE + "vt.json",
                    "license": "部件檢索公開授權（非商业，须标注来源）", "tier": "nc"},
    "yibai:lv1": {"name": "yi-bai/ids lv1", "url": YIBAI_BASE + "ids_lv1.txt", "license": "MIT",
                  "tier": "open"},
    "local:keben": {"name": "本项目刻本实证手工边", "url": "config/variants/local_edges.json",
                    "license": "自有", "tier": "own"},
    "local:never": {"name": "本项目人审定永不并组", "url": "config/variants/never_group.json",
                    "license": "自有", "tier": "own"},
    "near:v1": {"name": "本项目形近对表 v1（IDS＋字体模板余弦）", "url": "config/ids/confusable_pairs_v1.tsv",
                "license": "自有", "tier": "own"},
    "near:ids-v1": {"name": "本项目 IDS 形近对表 v1", "url": "config/ids/ids_confusable_pairs_v1.tsv",
                    "license": "自有", "tier": "own"},
    "zi": {"name": "字统网 zi.tools 针对性查询所得的一跳族（派生事实）", "url": "https://zi.tools/",
           "license": "无数据许可；只收派生的关系事实，不收原文与图", "tier": "fact-ref"},
}

#: 原始下载文件 → URL（构建只读本地 src/，`--fetch` 时才按这张表下载缺的）。
#: Unihan.zip 下载后只留这几个文本文件（`unihan-<名>`），原始资料进 R2 时都是文本。
UNIHAN_PARTS = ("Unihan_Variants.txt", "Unihan_IRGSources.txt", "Unihan_Readings.txt",
                "Unihan_DictionaryLikeData.txt", "Unihan_DictionaryIndices.txt")

SRC_FILES: dict[str, str] = {
    **{f"unihan-{n}": UNIHAN_URL for n in UNIHAN_PARTS},
    "cjkvi-twedu-variants.txt": CJKVI_BASE + "twedu-variants.txt",
    "cjkvi-hydzd-variants.txt": CJKVI_BASE + "hydzd-variants.txt",
    "cjkvi-hydzd-borrowed.txt": CJKVI_BASE + "hydzd-borrowed.txt",
    "cjkvi-dypytz-variants.txt": CJKVI_BASE + "dypytz-variants.txt",
    "cjkvi-cjkvi-simplified.txt": CJKVI_BASE + "cjkvi-simplified.txt",
    "yitizi-index.js": YITIZI_URL,
    "yibai-ids_lv1.txt": YIBAI_BASE + "ids_lv1.txt",
    "charcomp-rt.jsonl": CHARCOMP_BASE + "rt.jsonl",
    "charcomp-dt.jsonl": CHARCOMP_BASE + "dt.jsonl",
    "charcomp-vt.json": CHARCOMP_BASE + "vt.json",
}

# ── 码位区块 ────────────────────────────────────────────
BLOCKS: tuple[tuple[int, int, str], ...] = (
    (0x3400, 0x4DBF, "A"), (0x4E00, 0x9FFF, "URO"), (0xF900, 0xFAFF, "compat"),
    (0x20000, 0x2A6DF, "B"), (0x2A700, 0x2B73F, "C"), (0x2B740, 0x2B81F, "D"),
    (0x2B820, 0x2CEAF, "E"), (0x2CEB0, 0x2EBEF, "F"), (0x2EBF0, 0x2EE5F, "I"),
    (0x2F800, 0x2FA1F, "compat-sup"), (0x30000, 0x3134F, "G"), (0x31350, 0x323AF, "H"),
    (0x323B0, 0x3347F, "J"),
)


def block_of(ch: str) -> str:
    if len(ch) != 1:
        return ""
    cp = ord(ch)
    for lo, hi, name in BLOCKS:
        if lo <= cp <= hi:
            return name
    return ""


def is_legacy_cjk(s: str) -> bool:
    """`scripts/build_variants.py:is_cjk_char` 的同一口径（含兼容区），导现役来源时用，保证能重放。"""
    return block_of(s) != ""
