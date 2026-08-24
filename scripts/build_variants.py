"""P0 异体字关系层：把三个公开数据源合并成「字 ↔ 异体字」无向关系表。

    python scripts/build_variants.py [--cache config/variants/cache] [--force]

数据源（全部批量下载，缓存在 ``config/variants/cache/``，该目录不入库）：

1. **Unihan_Variants.txt** —— https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip
   取 kSemanticVariant / kSpecializedSemanticVariant / kZVariant /
   kSimplifiedVariant / kTraditionalVariant / kSpoofingVariant。
   注意 kSpoofingVariant 是**形近易混字，不是异体字**（charset_and_lm.md
   的纪律）——这里仍然收录，但打独立标签 ``unihan:kSpoofingVariant``，
   且查询模块的默认高置信来源集**不含**它；对 OCR 来说形近易混对
   构造混淆集合有用，前提是标签分明、绝不混进异体归并。
2. **cjkvi-variants** —— https://github.com/cjkvi/cjkvi-variants
   twedu（台湾教育部异体字字典）/ hydzd（汉语大字典）/ dypytz（第一批
   异体字整理表）/ cjkvi-simplified（简繁对照）。逗号分隔三列
   ``字,关系,字``，混有元数据行（首列带 ``/``）、# 注释、第四列注记、
   以及第三列为 IDS 序列（⿰…）或 ``字[部件]`` 括注形的行——都要容错
   跳过并计数。
3. **yitizi** —— nk2028/yitizi 聚合表（教育部異體字字典/漢語大字典/
   開放康熙字典的并集）。npm 发布物 ``dist/yitizi.json`` 实际不存在
   （404），数据内嵌在 ``index.js`` 的 ``yitiziData: {…}`` 里，从
   jsdelivr 拉 index.js 再抽出 JSON。版本固定 0.1.3 保证可复现。

产出（`config/variants/`）：

- ``variants.json`` —— ``pairs[a][b] = [来源标签…]``，只存
  ``ord(a) < ord(b)`` 的一侧（关系无向，查询模块负责双向展开）。
  键排序、紧凑分隔符，输出确定性（同输入必同输出，便于 diff）。
- ``report.json`` —— 各来源规模 / 跳过行数 / 合并后统计。

## 与 charset 的 variants.tsv 是什么关系

`config/charset/variants.tsv` 是「异体 → 本版正字」的**语义层归并**，
方向由本书语料频次决定，且默认只留语料相关的边——那是给 LM 用的。
这份 `variants.json` 是**关系层**：无向、全量、带来源标签，不选正字、
不做归并，供候选融合的异体归一与字形库检索的同义展开自行取舍。
关系层可以派生语义层，反之不行，所以两份并存。

## 异体关系不传递（这一节容易出事）

「甲是乙的异体」与「乙是丙的异体」推不出「甲是丙的异体」——多义字
会把不相干的组桥接起来（经典例：于↔於、於↔于 各自成立，但沿着多义
桥一路连通能把几十个字连成一团）。所以本表只存**边**，不存连通分量；
`open_guji_cv/variants.py` 的 `variant_group()` 做展开时默认只走高置信
来源，风险见其 docstring。
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "config" / "variants"
CACHE_DIR = OUT_DIR / "cache"

UNIHAN_URL = "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip"
CJKVI_BASE = "https://raw.githubusercontent.com/cjkvi/cjkvi-variants/master/"
# dist/yitizi.json 在 npm 包里并不存在（404）；数据内嵌在 index.js 里。
YITIZI_URL = "https://cdn.jsdelivr.net/npm/yitizi@0.1.3/index.js"

# 采信的 Unihan 变体属性 → 标签。kSpoofingVariant 单独打标签收录：
# 它是形近易混字，不是异体字，下游默认不得当异体用（见模块 docstring）。
UNIHAN_PROPS = (
    "kSemanticVariant", "kSpecializedSemanticVariant", "kZVariant",
    "kSimplifiedVariant", "kTraditionalVariant", "kSpoofingVariant",
)

# cjkvi-variants：文件名 → 来源标签
CJKVI_FILES = {
    "twedu-variants.txt": "twedu",
    "hydzd-variants.txt": "hydzd",
    "dypytz-variants.txt": "dypytz",
    "cjkvi-simplified.txt": "cjkvi-simplified",
}

CJK_BLOCKS = [
    (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF), (0x2A700, 0x2B73F), (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF), (0x2CEB0, 0x2EBEF), (0x2EBF0, 0x2EE5F),
    (0x2F800, 0x2FA1F), (0x30000, 0x3134F), (0x31350, 0x323AF),
    (0x323B0, 0x3347F),
]
_CP_RE = re.compile(r"U\+([0-9A-Fa-f]+)")


def is_cjk_char(s: str) -> bool:
    """恰好一个已编码汉字（单码位；IDS 序列 / 括注形 / 空串都不算）。"""
    if len(s) != 1:
        return False
    cp = ord(s)
    return any(lo <= cp <= hi for lo, hi in CJK_BLOCKS)


# ── 下载（缓存优先）───────────────────────────────────────

def fetch(url: str, dest: Path, force: bool = False) -> Path:
    """下载到 dest，已有缓存则跳过。走环境代理与系统 CA（不关证书校验）。"""
    if dest.exists() and not force:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载 {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "open-guji-cv"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    dest.write_bytes(data)
    return dest


def fetch_unihan_variants(cache: Path, force: bool = False) -> Path:
    txt = cache / "Unihan_Variants.txt"
    if txt.exists() and not force:
        return txt
    zip_path = fetch(UNIHAN_URL, cache / "Unihan.zip", force)
    with zipfile.ZipFile(zip_path) as z:
        z.extract("Unihan_Variants.txt", cache)
    return txt


# ── 解析 ─────────────────────────────────────────────────
# 每个解析函数返回 (edges, stats)：
#   edges: list[(a, b, tag)]，a/b 均为单个汉字，未去重、未定向
#   stats: 该来源的行数 / 跳过数等

def parse_unihan_variants(text: str) -> tuple[list[tuple[str, str, str]], dict]:
    """Unihan_Variants.txt → 带 ``unihan:<属性>`` 标签的边。

    值形如 ``U+4E94<kMatthews,kMeyerWempe``：尖括号后是词典来源标注，
    剥掉只取码位。自环（少数字自我引用）跳过。
    """
    edges: list[tuple[str, str, str]] = []
    stats = Counter()
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        cp_s, prop, val = parts
        if prop not in UNIHAN_PROPS:
            stats["prop_ignored"] += 1
            continue
        a = chr(int(cp_s[2:], 16))
        tag = f"unihan:{prop}"
        for tok in val.split():
            m = _CP_RE.match(tok)          # match 锚定开头，天然剥掉 <kXxx
            if not m:
                stats["token_bad"] += 1
                continue
            b = chr(int(m.group(1), 16))
            if a == b:
                stats["self_loop"] += 1
                continue
            edges.append((a, b, tag))
    stats["edges"] = len(edges)
    return edges, dict(stats)


def parse_cjkvi_variants(text: str, tag: str) -> tuple[list[tuple[str, str, str]], dict]:
    """cjkvi-variants 逗号分隔文件 → 带来源标签的边。

    数据行是 ``字,关系,字``；要跳过的有：# 注释、元数据行（首列带
    ``/``，如 ``twedu/variant,<rev>,…``）、第四列 IDS 注记（只取前三列）、
    第三列不是单个汉字的行（IDS 序列 ``⿰革𡲬``、括注形 ``虜[田]``、
    dypytz 的 x→y 之类特殊行）——跳过并计数，别让脏行毒化整表。
    """
    edges: list[tuple[str, str, str]] = []
    stats = Counter()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        if len(parts) < 3:
            stats["line_short"] += 1
            continue
        a, _rel, b = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if "/" in a or a.startswith("<"):
            stats["line_meta"] += 1
            continue
        if not is_cjk_char(a):
            stats["col1_bad"] += 1
            continue
        if not is_cjk_char(b):
            stats["col3_bad"] += 1
            continue
        if a == b:
            stats["self_loop"] += 1
            continue
        edges.append((a, b, tag))
    stats["edges"] = len(edges)
    return edges, dict(stats)


_YITIZI_RE = re.compile(r"yitiziData\s*:\s*(\{.*?\n\})", re.DOTALL)


def parse_yitizi_js(js_text: str) -> tuple[list[tuple[str, str, str]], dict]:
    """yitizi 的 index.js → 边。数据内嵌为 ``yitiziData: {"㐀":"丘丠坵",…}``，
    值字符串的每个字符都是键字的一个异体。"""
    m = _YITIZI_RE.search(js_text)
    if not m:
        raise ValueError("index.js 里找不到 yitiziData 对象——上游格式变了")
    data = json.loads(m.group(1))
    edges: list[tuple[str, str, str]] = []
    stats = Counter()
    for a, variants in data.items():
        if not is_cjk_char(a):
            stats["key_bad"] += 1
            continue
        for b in variants:
            if not is_cjk_char(b):
                stats["value_bad"] += 1
                continue
            if a == b:
                stats["self_loop"] += 1
                continue
            edges.append((a, b, "yitizi"))
    stats["entries"] = len(data)
    stats["edges"] = len(edges)
    return edges, dict(stats)


# ── 合并 ─────────────────────────────────────────────────

def merge_edges(edge_lists: list[list[tuple[str, str, str]]]) -> dict[str, dict[str, list[str]]]:
    """全部边 → ``pairs[a][b] = sorted(标签集合)``，只存 ord(a)<ord(b) 一侧。"""
    acc: dict[tuple[str, str], set[str]] = defaultdict(set)
    for edges in edge_lists:
        for a, b, tag in edges:
            key = (a, b) if ord(a) < ord(b) else (b, a)
            acc[key].add(tag)
    pairs: dict[str, dict[str, list[str]]] = {}
    for (a, b), tags in acc.items():
        pairs.setdefault(a, {})[b] = sorted(tags)
    return pairs


def group_stats(pairs: dict[str, dict[str, list[str]]],
                trusted: frozenset[str] | None) -> dict:
    """连通分量统计（只为报告展示桥接风险，不写进 variants.json）。"""
    adj: dict[str, set[str]] = defaultdict(set)
    for a, bs in pairs.items():
        for b, tags in bs.items():
            if trusted is not None and not (set(tags) & trusted):
                continue
            adj[a].add(b)
            adj[b].add(a)
    seen: set[str] = set()
    sizes: list[int] = []
    biggest: set[str] = set()
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
        sizes.append(len(comp))
        if len(comp) > len(biggest):
            biggest = comp
    sizes.sort(reverse=True)
    return {
        "groups": len(sizes),
        "chars": len(adj),
        "largest": sizes[0] if sizes else 0,
        "top10_sizes": sizes[:10],
        "largest_sample": "".join(sorted(biggest)[:40]),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="构建异体字关系层 variants.json")
    ap.add_argument("--cache", default=str(CACHE_DIR),
                    help="下载缓存目录（默认 config/variants/cache，不入库）")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--force", action="store_true", help="忽略缓存重新下载")
    args = ap.parse_args()

    cache = Path(args.cache)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. 下载（缓存优先）
    unihan_txt = fetch_unihan_variants(cache, args.force)
    cjkvi_paths = {tag: fetch(CJKVI_BASE + fname, cache / fname, args.force)
                   for fname, tag in CJKVI_FILES.items()}
    yitizi_js = fetch(YITIZI_URL, cache / "yitizi-index.js", args.force)

    # 2. 解析
    edge_lists: list[list[tuple[str, str, str]]] = []
    source_stats: dict[str, dict] = {}

    edges, st = parse_unihan_variants(unihan_txt.read_text(encoding="utf-8"))
    edge_lists.append(edges)
    st["by_prop"] = dict(Counter(t for _, _, t in edges))
    source_stats["unihan"] = {"url": UNIHAN_URL, **st}

    for tag, path in cjkvi_paths.items():
        edges, st = parse_cjkvi_variants(path.read_text(encoding="utf-8"), tag)
        edge_lists.append(edges)
        source_stats[tag] = {"url": CJKVI_BASE + path.name, **st}

    edges, st = parse_yitizi_js(yitizi_js.read_text(encoding="utf-8"))
    edge_lists.append(edges)
    source_stats["yitizi"] = {"url": YITIZI_URL, **st}

    # 3. 合并
    pairs = merge_edges(edge_lists)
    n_pairs = sum(len(bs) for bs in pairs.values())
    chars = set(pairs)
    for bs in pairs.values():
        chars.update(bs)
    tag_pair_count = Counter()
    for bs in pairs.values():
        for tags in bs.values():
            for t in tags:
                tag_pair_count[t] += 1

    # 4. 写 variants.json（确定性：键排序 + 紧凑分隔符）
    doc = {
        "meta": {
            "what": "字↔异体字 无向关系表（P0 关系层）。"
                    "pairs[a][b]=来源标签列表，只存 ord(a)<ord(b) 一侧；"
                    "查询用 open_guji_cv/variants.py。",
            "caution": "unihan:kSpoofingVariant 是形近易混字不是异体字；"
                       "异体关系不传递，连通展开须限制来源（见查询模块）。",
            "sources": {tag: source_stats[tag]["url"] for tag in sorted(source_stats)},
        },
        "pairs": pairs,
    }
    out_json = out_dir / "variants.json"
    out_json.write_text(
        json.dumps(doc, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")) + "\n",
        encoding="utf-8")

    # 5. 报告
    trusted = frozenset(
        {f"unihan:{p}" for p in UNIHAN_PROPS if p != "kSpoofingVariant"}
        | {"twedu", "yitizi"})
    report = {
        "chars": len(chars),
        "pairs": n_pairs,
        "pairs_by_source": dict(sorted(tag_pair_count.items())),
        "sources": source_stats,
        "groups_trusted_default": group_stats(pairs, trusted),
        "groups_all_sources": group_stats(pairs, None),
        "variants_json_bytes": out_json.stat().st_size,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
