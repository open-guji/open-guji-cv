"""M8 跨书字形库：人工确认过的 (精确字形, 书版, 图块, 特征) 条目库。

- 只进人工确认过的字形（不进机器猜测）→ 命中即高置信；
- char 是精确异体字形（爲/為是独立条目）；semantic 仅用于按正字检索；
- 检索两级：特征 kNN 粗排 → verify_pair 精验。

存储（glyph_store/）：
    glyphs.jsonl            条目元数据
    patches/{glyph_id}.png  归一二值字形图（64×64）
    features_{backend}.npz  特征矩阵（与 glyphs.jsonl 行对齐）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from ..utils.image_io import imread, imwrite
from .features import DEFAULT_FEATURE, get_feature
from .normalize import NORM_SIZE
from .verify import PairVerdict, verify_pair


@dataclass
class GlyphEntry:
    glyph_id: str
    char: str               # 精确异体字形（字形层）
    semantic: str           # 通行正字（语义层，仅供检索）
    book: str
    edition_tag: str
    n_confirmed: int        # 确认实例数
    source_instances: list[str]   # 代表来源（最多存前若干个）


@dataclass
class GlyphHit:
    glyph_id: str
    char: str
    f1: float
    verdict: str


class GlyphLibrary:
    def __init__(self, store_dir: str | Path,
                 feature_backend: str = DEFAULT_FEATURE):
        self.store_dir = Path(store_dir)
        self.feature_name = feature_backend
        self._feature = get_feature(feature_backend)
        self.entries: list[GlyphEntry] = []
        self._patches: np.ndarray | None = None   # (N, S, S)
        self._feats: np.ndarray | None = None     # (N, D)
        if (self.store_dir / "glyphs.jsonl").exists():
            self._load()

    # ── 持久化 ────────────────────────────────────────────

    def _load(self) -> None:
        with open(self.store_dir / "glyphs.jsonl", encoding="utf-8") as f:
            self.entries = [GlyphEntry(**json.loads(line))
                            for line in f if line.strip()]
        feats_path = self.store_dir / f"features_{self.feature_name}.npz"
        patches = []
        for e in self.entries:
            img = imread(str(self.store_dir / "patches" / f"{e.glyph_id}.png"))
            if img is None:
                patches.append(np.zeros((NORM_SIZE, NORM_SIZE), dtype=np.uint8))
            else:
                if img.ndim == 3:
                    img = img[:, :, 0]
                patches.append((img < 128).astype(np.uint8))  # 存储为白底黑字
        self._patches = np.stack(patches) if patches else None
        if feats_path.exists():
            self._feats = np.load(feats_path)["feats"]
        elif self._patches is not None and len(self._patches):
            self._feats = self._feature.extract(self._patches)

    def save(self) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        with open(self.store_dir / "glyphs.jsonl", "w", encoding="utf-8") as f:
            for e in self.entries:
                f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
        if self._feats is not None:
            np.savez_compressed(
                self.store_dir / f"features_{self.feature_name}.npz",
                feats=self._feats)

    # ── 写入 ─────────────────────────────────────────────

    def add(self, char: str, semantic: str, patch: np.ndarray,
            book: str, edition_tag: str | None = None,
            n_confirmed: int = 1,
            source_instances: list[str] | None = None) -> GlyphEntry:
        """patch: S×S uint8 {0,1} 归一二值图（1=墨迹）。"""
        glyph_id = f"g_{len(self.entries):06d}"
        entry = GlyphEntry(
            glyph_id=glyph_id, char=char, semantic=semantic,
            book=book, edition_tag=edition_tag or book,
            n_confirmed=n_confirmed,
            source_instances=(source_instances or [])[:10])
        self.entries.append(entry)

        (self.store_dir / "patches").mkdir(parents=True, exist_ok=True)
        imwrite(str(self.store_dir / "patches" / f"{glyph_id}.png"),
                (255 - patch * 255).astype(np.uint8))

        feat = self._feature.extract(patch[None, ...])
        if self._feats is None:
            self._feats = feat
            self._patches = patch[None, ...]
        else:
            self._feats = np.vstack([self._feats, feat])
            self._patches = np.concatenate([self._patches, patch[None, ...]])
        return entry

    # ── 检索 ─────────────────────────────────────────────

    def query(self, patch: np.ndarray, edition_hint: str | None = None,
              k: int = 5) -> list[GlyphHit]:
        """特征 kNN 粗排 → verify_pair 精验。patch 为归一二值图。

        edition_hint 命中的条目排序优先（同书版字形几乎一致）。
        """
        if self._feats is None or not len(self.entries):
            return []
        feat = self._feature.extract(patch[None, ...])[0]
        sims = self._feats @ feat
        if edition_hint:
            boost = np.array([0.05 if e.edition_tag == edition_hint else 0.0
                              for e in self.entries])
            sims = sims + boost
        top = np.argsort(-sims)[:k]
        hits: list[GlyphHit] = []
        for i in top:
            v: PairVerdict = verify_pair(patch, self._patches[int(i)])
            e = self.entries[int(i)]
            hits.append(GlyphHit(e.glyph_id, e.char, v.f1, v.verdict))
        hits.sort(key=lambda h: -h.f1)
        return hits

    # ── 按正字检索（"这本书里'遊'用的什么形体"）────────────

    def variants_in_edition(self, semantic: str,
                            edition_tag: str | None = None) -> list[GlyphEntry]:
        return [e for e in self.entries
                if e.semantic == semantic
                and (edition_tag is None or e.edition_tag == edition_tag)]

    def __len__(self) -> int:
        return len(self.entries)
