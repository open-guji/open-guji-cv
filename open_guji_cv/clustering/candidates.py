"""M4 簇级候选生成：每个簇（而非每个实例）生成候选字分布。

候选来源（按可靠性）：
- glyph_knn : 字形库 kNN + 配准精验（人工确认过的字形，命中即高置信）
- vlm       : 视觉语言模型识别种子（vlm_assist 产物；强在字形整体与异体字）
- ocr       : PaddleOCR / RapidOCR 对簇代表图块的单字识别
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
SOURCE_WEIGHTS = {"glyph_knn": 3.0, "vlm": 2.0, "ocr": 1.5, "prior": 1.0}


@dataclass
class Proposal:
    char: str
    p: float          # 该来源内部的置信度 (0~1]
    source: str
    surface_uncertain: bool = False   # OCR 字表可能不含该异体字形


# ── 简→繁候选扩展（OCR 字表偏差修正）────────────────────

_S2T_TABLE: dict[str, list[str]] | None = None


def _load_s2t() -> dict[str, list[str]]:
    """加载 opencc 的 STCharacters（简 → [繁...]，含一简多繁）。

    opencc 不可用时返回空表（该修正静默跳过）。
    """
    global _S2T_TABLE
    if _S2T_TABLE is not None:
        return _S2T_TABLE
    table: dict[str, list[str]] = {}
    try:
        import opencc, os
        path = os.path.join(os.path.dirname(opencc.__file__),
                            "dictionary", "STCharacters.txt")
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    table[parts[0]] = parts[1:]
    except Exception:
        pass
    _S2T_TABLE = table
    return table


def traditional_variants(char: str) -> list[str]:
    """简体字 → 对应繁体形式列表（一简多繁全给）；非简体返回 []。

    刻本古籍不可能出现简体字形——OCR（PP-OCR 等简体中文模型）
    输出简体说明字表覆盖不足，真实字形应是对应的繁体之一。
    这是**扩展候选**而非合并异体字：各繁体形式各自独立计票，
    最终字形仍由人工审查确认。

    **自身即合法繁体形式的字不做替换**：opencc 表中"卷→卷 捲"、
    "万→萬 万"这类条目，简体字本身也是通行繁体字形（"卷"在刻本中
    就写作"卷"），替换成另一形式反而引入错误。保守起见返回空。
    """
    forms = _load_s2t().get(char, [])
    if not forms or char in forms:
        return []
    return forms


def traditional_candidates(char: str) -> list[tuple[str, float]]:
    """OCR 输出的字 → [(候选字形, 相对权重)]，权重和为 1。

    三种情形（都不做"合并"，只是给出候选让上下文/人工裁决）：
    - 非简体字（書/之）：原样，权重 1.0
    - 纯简体字（内/检/群）：繁体为主候选（唯一形式 0.9；一简多繁时
      主形 0.7、次形分 0.2），原简体输出降权保留 0.1
      （刻本几乎不可能是简体，但不武断排除）
    - 自身即合法繁体（卷/万/后/里）：原字仍为首选 0.55，其他繁体形式
      作**平级候选**分 0.45 —— "卷"该留"卷"、"万"可能是"萬"，
      二元替换必错其一，交给上下文与人工。
    """
    forms = _load_s2t().get(char, [])
    if not forms:
        return [(char, 1.0)]
    if char in forms:
        others = [f for f in forms if f != char]
        if not others:
            return [(char, 1.0)]
        w = 0.45 / len(others)
        return [(char, 0.55)] + [(f, w) for f in others]
    rest = forms[1:]
    if rest:                     # 一简多繁：主形 0.7，次形分 0.2
        out = [(forms[0], 0.7)] + [(f, 0.2 / len(rest)) for f in rest]
    else:                        # 唯一繁体形式：独得 0.9
        out = [(forms[0], 0.9)]
    return out + [(char, 0.1)]   # 原简体输出降权兜底


def props_from_votes(votes: dict[str, float], source: str,
                     s2t: bool = True, top_k: int = 5) -> list["Proposal"]:
    """字→票数 → Proposal 列表（含简→繁扩展）。

    OCR 类来源共用：归一化票数为置信度，简体输出扩展为繁体候选
    （繁体主候选 0.7、一简多繁次形 0.2、原简体降权保留 0.1）。
    """
    total = sum(votes.values())
    if not total:
        return []
    props: list[Proposal] = []
    for c, v in sorted(votes.items(), key=lambda x: -x[1])[:top_k]:
        p = v / total
        forms = traditional_candidates(c) if s2t else [(c, 1.0)]
        for ch, w in forms:
            props.append(Proposal(ch, p * w, source, surface_uncertain=True))
    return props


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

    def __init__(self, s2t: bool = True):
        self.s2t = s2t

    def propose(self, rep_patches, members) -> list[Proposal]:
        votes: dict[str, float] = {}
        for m in members:
            if m.ocr_text:
                votes[m.ocr_text] = votes.get(m.ocr_text, 0.0) + max(m.ocr_confidence, 0.1)
        return props_from_votes(votes, self.name, self.s2t)


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

    def __init__(self, s2t: bool = True):
        self._detector = None
        self.s2t = s2t

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
        return props_from_votes(votes, self.name, self.s2t)


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
        failures: dict[str, int] = {}
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
                    n_fail = failures.get(source.name, 0) + 1
                    failures[source.name] = n_fail
                    if n_fail <= 3:      # 只详报前几次，避免刷屏
                        print(f"  {c['cluster_id']} 来源 {source.name} 失败: "
                              f"{type(e).__name__}: {e}")
            out.append({
                "cluster_id": c["cluster_id"],
                "size": c["size"],
                "candidates": fuse_candidates(proposals, self.variant_map),
            })
            if n % 200 == 0 or n == total:
                print(f"  候选生成 [{n}/{total}]")

        # 失败汇总：高失败率几乎必然是编程错误而非数据问题，必须显式告警
        for name, n in failures.items():
            rate = n / max(1, total)
            level = "错误" if rate > 0.5 else "警告"
            print(f"  [{level}] 来源 {name} 在 {n}/{total} 个簇上失败 "
                  f"({rate*100:.0f}%)")

        phase6 = book_out_dir / "phase6_labels"
        phase6.mkdir(parents=True, exist_ok=True)
        payload = {"sources": [s.name for s in self.sources], "clusters": out,
                   "source_failures": failures}
        with open(phase6 / "candidates.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return payload


class RapidOcrSource(CandidateSource):
    """RapidOCR（PP-OCRv4 ONNX）单字识别。

    模型随 pip 包分发、无需联网下载，是无 GPU/无模型源环境下
    OcrSource 的等价替代；识别的是同一套 PP-OCR 权重。

    top-k 通过**增强投票**获得（设计文档 M4 的回退方案）：对图块做
    多种轻微变换分别识别，按加权频次汇总，天然反映识别稳定性。

    PP-OCR 是简体中文模型，对繁体刻本有系统性简体偏差（内/检/谕/则…），
    故默认开启 s2t：简体输出扩展为对应繁体候选（见 traditional_variants）。
    """

    name = "ocr"

    # 古籍单字识别的常见噪声：标点、拉丁字母数字（"一"→"1" 之类）
    _NOISE = set(" \t　“”‘’\"'`.,，。、·;；:：!！?？()（）[]【】{}<>《》-—_=+*/\\|~^$#@%&")

    def __init__(self, scale: float = 3.0, votes: int = 3, s2t: bool = True):
        self._engine = None
        self.scale = scale
        self.votes = votes
        self.s2t = s2t     # 简体输出 → 繁体候选（刻本必为繁体）

    def _ensure(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self._engine = RapidOCR()

    @classmethod
    def _clean(cls, text: str) -> str:
        """取首个 CJK 字符（丢弃标点/字母数字噪声）。"""
        for ch in text:
            if ch in cls._NOISE or ch.isascii():
                continue
            return ch
        return ""

    def _variants(self, patch: np.ndarray):
        """增强变体：原图 + 轻微缩放/平移，用于投票。"""
        img = patch
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        big = cv2.resize(img, None, fx=self.scale, fy=self.scale,
                         interpolation=cv2.INTER_CUBIC)
        yield big
        if self.votes > 1:
            h, w = big.shape[:2]
            pad = int(min(h, w) * 0.08)
            yield cv2.copyMakeBorder(big, pad, pad, pad, pad,
                                     cv2.BORDER_CONSTANT, value=(255, 255, 255))
        if self.votes > 2:
            yield cv2.resize(big, None, fx=0.8, fy=0.8,
                             interpolation=cv2.INTER_AREA)

    def propose(self, rep_patches, members) -> list[Proposal]:
        self._ensure()
        votes: dict[str, float] = {}
        for patch in rep_patches:
            for img in self._variants(patch):
                res, _ = self._engine(img, use_det=False, use_cls=False,
                                      use_rec=True)
                if not res:
                    continue
                ch = self._clean(res[0][0])
                if ch:
                    votes[ch] = votes.get(ch, 0.0) + float(res[0][1])
        return props_from_votes(votes, self.name, self.s2t)


class VlmSeedSource(CandidateSource):
    """视觉语言模型（VLM）识别种子。

    读 vlm_assist 产出的 mapping.json + recognitions.json，按簇提供候选。
    与 OCR 是互补来源：VLM 强在字形整体理解与繁体/异体字，OCR 强在
    高频常用字的稳定性——两者分歧的簇自然浮上审查队列。

    propose() 只拿得到成员元数据，故内部建 instance_id → spec 索引。
    """

    name = "vlm"

    def __init__(self, seed_dir: str | Path, clusters_json: str | Path):
        from .vlm_assist import parse_spec
        self._parse = parse_spec
        seed = Path(seed_dir)
        with open(seed / "mapping.json", encoding="utf-8") as f:
            mapping = json.load(f)
        with open(seed / "recognitions.json", encoding="utf-8") as f:
            recs = json.load(f)
        with open(clusters_json, encoding="utf-8") as f:
            members_of = {c["cluster_id"]: c["members"]
                          for c in json.load(f)["clusters"]}
        self._spec_by_instance: dict[str, str | None] = {}
        for bname, bmap in mapping.items():
            brec = recs.get(bname, {})
            for num, info in bmap.items():
                spec = brec.get(num)
                for iid in members_of.get(info["cluster"], []):
                    self._spec_by_instance[iid] = spec

    def propose(self, rep_patches, members) -> list[Proposal]:
        for m in members:
            if m.id in self._spec_by_instance:
                return [Proposal(ch, p, self.name, surface_uncertain=unc)
                        for ch, p, unc in self._parse(
                            self._spec_by_instance[m.id])]
        return []
