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
"""

from __future__ import annotations

from pathlib import Path

_DICTS = Path(__file__).resolve().parents[2] / "config" / "dicts"
DEFAULT_VARIANTS_PATH = _DICTS / "variants.tsv"          # 手工表（覆盖）
DEFAULT_AUTO_PATH = _DICTS / "variants.auto.tsv"         # 派生表


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
