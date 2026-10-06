"""多 OCR 引擎在同一黄金集上的准确率对比。

黄金集构建原则：取**双来源共识**（VLM 与 OCR 独立给出同一首选）的簇——
它们几乎确定正确，且不偏向任何被测引擎（tesseract 未参与构建）。

用法：
    python -m open_guji_cv bench-ocr <book_out_dir> [--engines rapidocr,tesseract]
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np



def build_goldset(book_out_dir: str | Path, min_size: int = 2,
                  mode: str = "consensus") -> list[dict]:
    """黄金集：[{cluster, char, size, rep_id}]。

    两种模式（评测不同引擎时须选无偏的那个）：

    - ``consensus``：候选首选同时被 vlm 与 ocr 命中——两个独立来源给出
      同一个字，几乎确定正确。**但对参与构建的 ocr 引擎有利**，
      评测 rapidocr 自身时有偏。
    - ``vlm_only``：只取 vlm 独立给出、且无歧义（单候选、非低置信）的簇。
      对所有 OCR 引擎都是外部标准，**跨引擎对比应当用这个**。
    """
    book = Path(book_out_dir)
    with open(book / "phase6_labels" / "candidates.json", encoding="utf-8") as f:
        cands = json.load(f)["clusters"]
    with open(book / "phase5_clusters" / "clusters.json", encoding="utf-8") as f:
        clusters = {c["cluster_id"]: c for c in json.load(f)["clusters"]}

    gold = []
    for x in cands:
        cs = x["candidates"]
        if not cs or x["size"] < min_size:
            continue
        if mode == "consensus":
            top = cs[0]
            if not ({"vlm", "ocr"} <= set(top["sources"])):
                continue
            char = top["char"]
        elif mode == "vlm_only":
            vlm = [k for k in cs if "vlm" in k["sources"]]
            # 无歧义：vlm 只给了一个候选（多候选=我当时就不确定）
            if len(vlm) != 1 or vlm[0]["p"] < 0.5:
                continue
            char = vlm[0]["char"]
        else:
            raise ValueError(f"未知模式: {mode}")
        c = clusters.get(x["cluster_id"])
        if not c:
            continue
        gold.append({"cluster": x["cluster_id"], "char": char,
                     "size": x["size"],
                     "rep_id": (c["reps"] or c["members"])[0]})
    return gold


# ── 引擎适配器（统一接口：patch → 候选字列表，首个为 top-1）────

class Engine:
    name = "base"

    def recognize(self, patch: np.ndarray) -> list[str]:
        raise NotImplementedError


class RapidOcrEngine(Engine):
    name = "rapidocr"

    def __init__(self, s2t: bool = True):
        from .candidates import RapidOcrSource
        self.src = RapidOcrSource(s2t=s2t)
        self.name = "rapidocr+s2t" if s2t else "rapidocr"

    def recognize(self, patch):
        return [p.char for p in self.src.propose([patch], [])]


class TesseractEngine(Engine):
    """Tesseract 繁体模型：纯繁体字表，不会输出简体（与 PP-OCR 互补）。"""

    name = "tesseract"

    def __init__(self, lang: str = "chi_tra", psm: int = 10,
                 scale: float = 3.0):
        self.lang, self.psm, self.scale = lang, psm, scale
        self.name = f"tesseract:{lang}"

    def recognize(self, patch):
        import pytesseract
        from PIL import Image
        img = cv2.resize(patch, None, fx=self.scale, fy=self.scale,
                         interpolation=cv2.INTER_CUBIC)
        txt = pytesseract.image_to_string(
            Image.fromarray(img), lang=self.lang,
            config=f"--psm {self.psm}").strip().replace(" ", "")
        return [c for c in txt[:1] if not c.isascii()]


def make_engine(spec: str) -> Engine:
    if spec == "rapidocr":
        return RapidOcrEngine(s2t=True)
    if spec == "rapidocr-raw":
        return RapidOcrEngine(s2t=False)
    if spec.startswith("tesseract"):
        lang = spec.split(":", 1)[1] if ":" in spec else "chi_tra"
        return TesseractEngine(lang=lang)
    raise ValueError(f"未知引擎: {spec}")


