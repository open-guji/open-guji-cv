"""异体字→正字（语义层）映射表。

字形层原则：标签、候选、字形库、转写全部保留精确异体字形，绝不合并；
本映射只提供语义层注记，供语言模型打分与用户阅读。

两张表叠加（2026-09-05 起，variant_strategy.md §3.4）：

- ``config/dicts/variants.auto.tsv``——**派生物**，由 ``scripts/build_semantic_variants.py``
  从关系层（``open_guji_cv/variants.py``）+ 本书用字账（``variant_ledger``）生成，
  方向 = 整理本用形；
- ``config/dicts/variants.tsv``——手工表，人工确认过的条目，**永远覆盖**自动表。

每行 "异体字<TAB>正字[<TAB>来源]"，# 开头为注释。查不到的字 semantic == 自身。
``load(path)`` 显式给路径时只读那一份（测试、CLI 覆盖用）。

**永不并组名单 ``config/variants/never_group.json`` 也管语义层**（2026-09-28，overview#201）：
名单里的对从**自动表**剔掉（两形不再归同一语义）；手工表是人定的，照旧覆盖。起因是整理本做
简繁转换留下的假异体（沙/砂、僕/仆、冶/治、咸/鹹、嘗/嚐）经关系图派生进自动表，seed_admit
的 `match_replace` 靠「语义相同」按整理本字放行，刻「沙」存成「砂」（qtw v010:73:2:21）。
"""

from __future__ import annotations

from pathlib import Path

_DICTS = Path(__file__).resolve().parents[2] / "config" / "dicts"
DEFAULT_VARIANTS_PATH = _DICTS / "variants.tsv"          # 手工表（覆盖）
DEFAULT_AUTO_PATH = _DICTS / "variants.auto.tsv"         # 派生表
NEVER_GROUP_PATH = _DICTS.parent / "variants" / "never_group.json"   # 永不并组（人工审定）


def _read_tsv(p: Path, into: dict[str, str]) -> None:
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] and parts[1]:
                into[parts[0]] = parts[1]


def never_group_pairs(path: Path = NEVER_GROUP_PATH) -> frozenset[frozenset[str]]:
    """人工审定的「不是异体」对（无序）。文件缺失 → 空集。"""
    if not path.exists():
        return frozenset()
    import json
    d = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(frozenset(p) for p in d.get("pairs", []) if len(p) == 2 and p[0] != p[1])


def _drop_never(mapping: dict[str, str], never: frozenset[frozenset[str]]) -> None:
    """自动表里名单对不许同语义：直接映射（砂→沙）删掉；两形经第三字归一的，两条都删。"""
    for pair in never:
        a, b = tuple(pair)
        if mapping.get(a) == b:
            del mapping[a]
        if mapping.get(b) == a:
            del mapping[b]
        if a in mapping and mapping.get(a) == mapping.get(b):
            del mapping[a]
            del mapping[b]


class VariantMap:
    def __init__(self, mapping: dict[str, str] | None = None):
        self._map = dict(mapping or {})

    @classmethod
    def load(cls, path: str | Path | None = None) -> "VariantMap":
        """默认：自动表在下、手工表在上；给了 ``path`` 就只读它。"""
        mapping: dict[str, str] = {}
        if path:
            _read_tsv(Path(path), mapping)
        else:
            _read_tsv(DEFAULT_AUTO_PATH, mapping)
            _drop_never(mapping, never_group_pairs())     # 名单只剔自动表
            _read_tsv(DEFAULT_VARIANTS_PATH, mapping)     # 手工条目覆盖自动条目
        return cls(mapping)

    def semantic(self, char: str) -> str:
        """字形层字符 → 语义层正字（查不到返回自身）。"""
        return self._map.get(char, char)

    def variants_of(self, semantic: str) -> list[str]:
        """某正字的全部已知异体字形（含自身）。"""
        out = [c for c, s in self._map.items() if s == semantic]
        if semantic not in out:
            out.append(semantic)
        return sorted(out)

    def normalize_text(self, text: str) -> str:
        """字形层文本 → 语义层文本（LM 训练/打分空间）。"""
        return "".join(self._map.get(c, c) for c in text)

    def __len__(self) -> int:
        return len(self._map)
