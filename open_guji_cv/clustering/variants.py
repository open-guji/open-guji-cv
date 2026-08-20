"""异体字→正字（语义层）映射表。

字形层原则：标签、候选、字形库、转写全部保留精确异体字形，绝不合并；
本映射只提供语义层注记，供语言模型打分与用户阅读。

映射表文件：config/dicts/variants.tsv，每行 "异体字<TAB>正字"，# 开头为注释。
查不到的字 semantic == 自身。
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_VARIANTS_PATH = Path(__file__).resolve().parents[2] / "config" / "dicts" / "variants.tsv"


class VariantMap:
    def __init__(self, mapping: dict[str, str] | None = None):
        self._map = dict(mapping or {})

    @classmethod
    def load(cls, path: str | Path | None = None) -> "VariantMap":
        p = Path(path) if path else DEFAULT_VARIANTS_PATH
        mapping: dict[str, str] = {}
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 2 and parts[0] and parts[1]:
                        mapping[parts[0]] = parts[1]
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
