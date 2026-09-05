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
import os
import numpy as np

from ..utils.image_io import imread
from .extractor import CharInstance, load_index
from .variants import VariantMap

# 各来源的融合权重（可靠性先验）
SOURCE_WEIGHTS = {"glyph_knn": 3.0, "vlm": 2.0, "ocr": 1.5,
                  "prior": 1.0, "tess": 0.5}


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


def residual_simplified(chars) -> dict[str, int]:
    """质量检查：统计**纯简体**残留（真正的 OCR 字表偏差）。

    判据不能用 `opencc.s2t(ch) != ch`——那会把"云/干/里/范/游/于/斗/卷"
    这类**一简多繁且自身合法**的字全部误报为简体，而它们在古籍中
    正是本字（子云、干支、里巷、范姓、游覽、于姓、星斗、十二卷）。
    只有 char 不在自身繁体列表中的才是无歧义简体。

    Args:
        chars: 字符可迭代对象（如全书识别结果）。
    Returns:
        {纯简体字: 出现次数}，空表示无残留。
    """
    table = _load_s2t()
    out: dict[str, int] = {}
    for ch in chars:
        forms = table.get(ch)
        if forms and ch not in forms:
            out[ch] = out.get(ch, 0) + 1
    return out


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
    """字形库检索：特征 kNN 粗排 → verify_pair 精验。

    默认**只查刻本来源**（kinds=("woodblock",)）。字体渲染来源动辄数万
    字形，混进来有两重害处：粗排把百来个刻本 exemplar 直接淹没；而实测
    （scripts/bench_font_glyphs.py）字体命中的「对」与「错」f1 分布是重叠
    的（正确命中 p10 反而低于错误命中 p90 0.06~0.13），阈值划不出来，
    当精确字形用只会注入错字。字体字形的用法见
    .claude/doc/glyph_db_expansion_research.md §5 P1。
    """

    name = "glyph_knn"

    def __init__(self, library, edition_hint: str | None = None,
                 kinds=("woodblock",)):
        self.library = library
        self.edition_hint = edition_hint
        self.kinds = kinds

    def propose(self, rep_patches, members) -> list[Proposal]:
        from .canonical import to_canonical
        from .normalize import normalize_patch
        votes: dict[str, float] = {}
        # 旧的 GlyphLibrary.query 不认 kinds，按能力降级
        kw = {"kinds": self.kinds} if self.kinds and hasattr(
            self.library, "_feat_kind") else {}
        for patch in rep_patches:
            # 库侧 exemplar 的派生物算自 canonical 图（glyph_db 入库时
            # 统一转换），查询侧走同一条路，两边预处理才对称
            norm = normalize_patch(to_canonical(patch))
            for hit in self.library.query(norm, edition_hint=self.edition_hint,
                                          k=3, **kw):
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


class PaddleOcrSource:
    """PP-OCRv5 识别器（paddleocr 3.x）：单字块 → CTC 主导时间步 top-k。

    ## 为什么加第二个引擎

    2026-09-05 横评（dev_set + p15-29 的 600 条整理本金标字块，同一批样本）：

    | 引擎 | 字典 | top-1 | 异体/简繁算对 | rare-char 21 条 |
    |---|---|---|---|---|
    | rapidocr（PP-OCRv4 mobile）| 6,278 汉字 | 83.5% | — | 8/21 |
    | **PP-OCRv5_server_rec** | **15,907 汉字** | **93.5%** | **96.5%** | **13/21（异体算对 17/21）** |

    整理本 4,636 字种：v4 字典不可达 1,814（39.5%），v5 只有 116（2.5%）。
    生僻字要靠候选里**有没有那个字**，字典大小是硬上限。

    残余错误全是老朋友：入/人、宋/朱、曰/日 这些形近对，以及「一」输出为空
    （单横笔在 rec 模型眼里像空白）。置信度分得开：对的中位 1.00，错的 0.60。

    ## 走独立进程，不装进主 venv

    paddlepaddle 3.3 与本 venv 的 numpy/torch 解不开，且装的时候要换 numpy 的
    DLL——控制台开着就「拒绝访问」（实测两次）。所以 paddle 留在它自己的环境，
    本类通过 `ocr/paddle_worker.py` 常驻子进程按行收发 JSON。单字块 ~50ms。

    仍然**只供候选、不投票**（OCR 永不与库配对放行，97.1% 那条老账）。
    """

    DEFAULT_PYTHON = r"D:/古籍整理/.venv/Scripts/python.exe"

    def __init__(self, model_name: str = "PP-OCRv5_server_rec",
                 s2t: bool = True, topk: int = 5, device: str = "cpu",
                 python: str | None = None):
        self._proc = None
        self.model_name = model_name
        self.s2t = s2t
        self.topk = topk
        self.device = device
        self.python = python or os.environ.get("GUJI_PADDLE_PYTHON", self.DEFAULT_PYTHON)

    def _ensure(self):
        if self._proc is not None and self._proc.poll() is None:
            return
        import subprocess
        from pathlib import Path
        worker = Path(__file__).resolve().parents[1] / "ocr" / "paddle_worker.py"
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        self._proc = subprocess.Popen(
            [self.python, str(worker), self.model_name, self.device],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1, env=env)
        # 等 ready 行（模型加载约 2~5 秒）；中间可能夹着 paddle 的 warning 行
        for _ in range(500):
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError(f"paddle worker 起不来（{self.python}）")
            line = line.strip()
            if line.startswith("{") and '"ready"' in line:
                return
        raise RuntimeError("paddle worker 没有回 ready")

    def rec_topk(self, patch: np.ndarray) -> list[tuple[str, float]]:
        self._ensure()
        import base64
        img = patch
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            return []
        req = {"png": base64.b64encode(buf.tobytes()).decode("ascii"), "k": self.topk}
        self._proc.stdin.write(json.dumps(req) + "\n")
        self._proc.stdin.flush()
        for _ in range(50):
            line = self._proc.stdout.readline()
            if not line:
                self._proc = None
                return []
            line = line.strip()
            if line.startswith("{"):
                d = json.loads(line)
                return [(c, float(p)) for c, p in d.get("topk", [])]
        return []

    def close(self):
        if self._proc is not None:
            try:
                self._proc.stdin.close()
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None


class RapidOcrSource(CandidateSource):
    """RapidOCR（PP-OCRv4 ONNX）单字识别，**CTC top-k** 输出。

    模型随 pip 包分发、无需联网下载。不走封装的 top-1 接口，而是直接
    读 rec 模型的 CTC softmax（T×C 概率矩阵），取主导时间步的 top-k
    ——设计文档 M4 的 "PaddleTopK" 方案。黄金集实测（book9, n=434）：
    top-1 85.2% → top-5+s2t 扩展召回 94.0%，为上下文修正提供了
    "正确答案在候选里"的前提。

    PP-OCR 是简体中文模型（字典 6625 字，无繁体扩展区），对繁体刻本
    有系统性简体偏差，故默认开启 s2t 扩展（见 traditional_candidates）。
    """

    name = "ocr"

    def __init__(self, scale: float = 3.0, s2t: bool = True, topk: int = 5):
        self._engine = None
        self.scale = scale
        self.s2t = s2t
        self.topk = topk

    def _ensure(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self._engine = RapidOCR()

    def rec_topk(self, patch: np.ndarray) -> list[tuple[str, float]]:
        """单字图块 → CTC 主导时间步的 top-k (char, prob)。"""
        rec = self._engine.text_rec
        img = patch
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        img = cv2.resize(img, None, fx=self.scale, fy=self.scale,
                         interpolation=cv2.INTER_CUBIC)
        _, im_h, im_w = rec.rec_image_shape[:3]
        norm = rec.resize_norm_img(img, im_w / im_h)
        preds = rec.session(norm[None].astype(np.float32))[0][0]   # (T, C)
        chars = rec.postprocess_op.character                        # [0]=blank
        non_blank = preds[:, 1:]
        t = int(np.unravel_index(np.argmax(non_blank), non_blank.shape)[0])
        order = np.argsort(-preds[t])
        out: list[tuple[str, float]] = []
        for i in order:
            if i == 0:            # blank
                continue
            ch = chars[i] if i < len(chars) else ""
            if ch and not ch.isascii():
                out.append((ch, float(preds[t][i])))
            if len(out) >= self.topk:
                break
        return out

    def propose(self, rep_patches, members) -> list[Proposal]:
        self._ensure()
        votes: dict[str, float] = {}
        for patch in rep_patches:
            for ch, p in self.rec_topk(patch):
                votes[ch] = votes.get(ch, 0.0) + p
        return props_from_votes(votes, self.name, self.s2t,
                                top_k=self.topk)


class TesseractSource(CandidateSource):
    """Tesseract 5 chi_tra 补充候选源（低权重兜底）。

    黄金集实测 top-1 仅 52.8%，但错误模式与 PP-OCR 不同：能救回
    rapidocr 错误中的 8.8%。**只宜作补充候选，绝不平权**
    （平权投票把整体从 85.2% 拖到 82.0%）——融合权重见 SOURCE_WEIGHTS。
    """

    name = "tess"

    def __init__(self, lang: str = "chi_tra", scale: float = 3.0):
        self.lang = lang
        self.scale = scale

    def propose(self, rep_patches, members) -> list[Proposal]:
        import pytesseract
        from PIL import Image
        votes: dict[str, float] = {}
        for patch in rep_patches:
            img = patch
            if img.ndim == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img = cv2.resize(img, None, fx=self.scale, fy=self.scale,
                             interpolation=cv2.INTER_CUBIC)
            txt = pytesseract.image_to_string(
                Image.fromarray(img), lang=self.lang,
                config="--psm 10").strip().replace(" ", "")
            for ch in txt[:1]:
                if not ch.isascii():
                    votes[ch] = votes.get(ch, 0.0) + 1.0
        return props_from_votes(votes, self.name, s2t=False)


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
