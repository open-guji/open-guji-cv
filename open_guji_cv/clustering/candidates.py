"""M4 簇级候选生成：每个簇（而非每个实例）生成候选字分布。

候选来源（按可靠性）：
- glyph_knn : 字形库 kNN + 配准精验（人工确认过的字形，命中即高置信）
- ocr       : PaddleOCR 对簇代表图块的单字识别（延迟加载，无 paddle 环境可不选）
- prior     : Phase 3 整列 OCR 对位字的簇内投票（弱先验，无额外依赖）

字形层原则：候选按精确字形独立计票，异体字绝不合并；
semantic 仅为语义层注记（供 M5 语言模型），不参与合并与标签。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..utils.image_io import imread
from .extractor import CharInstance, load_index
from .variants import VariantMap

# 各来源的融合权重（可靠性先验）
SOURCE_WEIGHTS = {"glyph_knn": 3.0, "ocr": 1.5, "prior": 1.0}


@dataclass
class Proposal:
    char: str
    p: float          # 该来源内部的置信度 (0~1]
    source: str
    surface_uncertain: bool = False   # OCR 字表可能不含该异体字形


class CandidateSource:
    """候选来源基类。"""

    name: str = "base"

    def propose(self, rep_patches: list[np.ndarray],
                members: list[CharInstance]) -> list[Proposal]:
        """rep_patches: 簇代表的原始灰度图块；members: 簇全部成员元数据。"""
        raise NotImplementedError


class PriorSource(CandidateSource):
    """Phase 3 整列 OCR 对位字的簇内投票（对位可能错位，权重最低）。"""

    name = "prior"

    def propose(self, rep_patches, members) -> list[Proposal]:
        votes: dict[str, float] = {}
        for m in members:
            if m.ocr_text:
                votes[m.ocr_text] = votes.get(m.ocr_text, 0.0) + max(m.ocr_confidence, 0.1)
        total = sum(votes.values())
        if not total:
            return []
        return [Proposal(c, v / total, self.name, surface_uncertain=True)
                for c, v in sorted(votes.items(), key=lambda x: -x[1])[:5]]


class GlyphKnnSource(CandidateSource):
    """字形库检索：特征 kNN 粗排 → verify_pair 精验。"""

    name = "glyph_knn"

    def __init__(self, library, edition_hint: str | None = None):
        self.library = library
        self.edition_hint = edition_hint

    def propose(self, rep_patches, members) -> list[Proposal]:
        from .normalize import normalize_patch
        votes: dict[str, float] = {}
        for patch in rep_patches:
            norm = normalize_patch(patch)
            for hit in self.library.query(norm, edition_hint=self.edition_hint, k=3):
                if hit.verdict == "same":
                    votes[hit.char] = max(votes.get(hit.char, 0.0), hit.f1)
        return [Proposal(c, f1, self.name)
                for c, f1 in sorted(votes.items(), key=lambda x: -x[1])]


class OcrSource(CandidateSource):
    """PaddleOCR 对簇代表的单字识别（框架期取 top-1；CTC top-k 为 P2 增强）。

    OCR 字表可能不含生僻异体字（输出通行正字），故 surface_uncertain=True，
    精确字形以人工审查确认为准。
    """

    name = "ocr"

    def __init__(self):
        self._detector = None

    def _ensure(self):
        if self._detector is None:
            from ..detectors.ocr_detector import OcrDetector
            self._detector = OcrDetector()

    def propose(self, rep_patches, members) -> list[Proposal]:
        self._ensure()
        votes: dict[str, float] = {}
        for patch in rep_patches:
            img = patch
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            img = cv2.resize(img, None, fx=2.0, fy=2.0,
                             interpolation=cv2.INTER_CUBIC)  # 小图放大有利识别
            boxes = self._detector.detect_chars(img)
            if not boxes:
                continue
            best = max(boxes, key=lambda b: b.confidence)
            if best.text:
                ch = best.text[0]      # 单字图块只取首字
                votes[ch] = votes.get(ch, 0.0) + best.confidence
        total = sum(votes.values())
        if not total:
            return []
        return [Proposal(c, v / total, self.name, surface_uncertain=True)
                for c, v in sorted(votes.items(), key=lambda x: -x[1])[:5]]


def fuse_candidates(proposals: list[Proposal], variant_map: VariantMap,
                    weights: dict[str, float] | None = None,
                    top_k: int = 5) -> list[dict]:
    """多来源融合（纯函数）。按精确字形计票，异体字不合并。"""
    weights = weights or SOURCE_WEIGHTS
    score: dict[str, float] = {}
    sources: dict[str, set[str]] = {}
    uncertain: dict[str, bool] = {}
    for prop in proposals:
        w = weights.get(prop.source, 1.0) * prop.p
        score[prop.char] = score.get(prop.char, 0.0) + w
        sources.setdefault(prop.char, set()).add(prop.source)
        # 只要有一个"字形确定"的来源（如字形库），就不再 uncertain
        prev = uncertain.get(prop.char, True)
        uncertain[prop.char] = prev and prop.surface_uncertain
    total = sum(score.values())
    if not total:
        return []
    ranked = sorted(score.items(), key=lambda x: -x[1])[:top_k]
    return [
        {"char": c, "semantic": variant_map.semantic(c),
         "p": round(s / total, 4), "sources": sorted(sources[c]),
         "surface_uncertain": uncertain[c]}
        for c, s in ranked
    ]


class CandidateGenerator:
    """IO 壳：读 phase5_clusters/ + phase4_chars/ → 写 phase6_labels/candidates.json"""

    def __init__(self, sources: list[CandidateSource],
                 variant_map: VariantMap | None = None):
        self.sources = sources
        self.variant_map = variant_map or VariantMap.load()

    def run_book(self, book_out_dir: Path) -> dict:
        book_out_dir = Path(book_out_dir)
        phase4 = book_out_dir / "phase4_chars"
        with open(book_out_dir / "phase5_clusters" / "clusters.json",
                  encoding="utf-8") as f:
            clusters = json.load(f)
        inst_by_id = {i.id: i for i in load_index(phase4)}

        out: list[dict] = []
        total = len(clusters["clusters"])
        for n, c in enumerate(clusters["clusters"], 1):
            members = [inst_by_id[m] for m in c["members"] if m in inst_by_id]
            rep_patches = []
            for rid in c["reps"]:
                inst = inst_by_id.get(rid)
                if inst is None:
                    continue
                img = imread(str(phase4 / inst.patch_path))
                if img is not None:
                    rep_patches.append(img)

            proposals: list[Proposal] = []
            for source in self.sources:
                try:
                    proposals.extend(source.propose(rep_patches, members))
                except Exception as e:   # 单簇失败不中断全书
                    print(f"  {c['cluster_id']} 来源 {source.name} 失败: {e}")
            out.append({
                "cluster_id": c["cluster_id"],
                "size": c["size"],
                "candidates": fuse_candidates(proposals, self.variant_map),
            })
            if n % 200 == 0 or n == total:
                print(f"  候选生成 [{n}/{total}]")

        phase6 = book_out_dir / "phase6_labels"
        phase6.mkdir(parents=True, exist_ok=True)
        payload = {"sources": [s.name for s in self.sources], "clusters": out}
        with open(phase6 / "candidates.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return payload
