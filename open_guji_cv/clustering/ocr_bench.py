"""多 OCR 引擎在同一黄金集上的准确率对比。

黄金集构建原则：取**双来源共识**（VLM 与 OCR 独立给出同一首选）的簇——
它们几乎确定正确，且不偏向任何被测引擎（tesseract 未参与构建）。

用法：
    python -m open_guji_cv bench-ocr <book_out_dir> [--engines rapidocr,tesseract]
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np

from ..utils.image_io import imread


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


def run_bench(book_out_dir: str | Path, engine_specs: list[str],
              limit: int | None = None, mode: str = "vlm_only") -> dict:
    """在黄金集上评测各引擎，并给出多引擎投票融合的效果。"""
    book = Path(book_out_dir)
    gold = build_goldset(book, mode=mode)
    if limit:
        gold = gold[:limit]
    inst = {}
    with open(book / "phase4_chars" / "index.jsonl", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            inst[d["id"]] = d

    patches = []
    for g in gold:
        img = imread(str(book / "phase4_chars" / inst[g["rep_id"]]["patch_path"]))
        if img is not None and img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        patches.append(img)

    results: dict[str, dict] = {}
    preds: dict[str, list[list[str]]] = {}
    for spec in engine_specs:
        eng = make_engine(spec)
        t0 = time.time()
        out = [eng.recognize(p) if p is not None else [] for p in patches]
        dt = time.time() - t0
        top1 = sum(1 for g, o in zip(gold, out) if o and o[0] == g["char"])
        topk = sum(1 for g, o in zip(gold, out) if g["char"] in o)
        w_top1 = sum(g["size"] for g, o in zip(gold, out)
                     if o and o[0] == g["char"])
        w_tot = sum(g["size"] for g in gold)
        results[eng.name] = {
            "top1": round(top1 / len(gold), 4),
            "topk": round(topk / len(gold), 4),
            "top1_weighted": round(w_top1 / w_tot, 4),
            "chars_per_sec": round(len(gold) / dt, 1),
        }
        preds[eng.name] = out

    # 多引擎投票：首选加权 1.0，次选 0.3；平票取先列引擎
    if len(preds) > 1:
        vote_ok = 0
        for i, g in enumerate(gold):
            score: dict[str, float] = {}
            for k, (name, out) in enumerate(preds.items()):
                for j, ch in enumerate(out[i][:3]):
                    score[ch] = score.get(ch, 0.0) + (1.0 if j == 0 else 0.3) \
                        * (1.0 - 0.01 * k)
            if score and max(score, key=score.get) == g["char"]:
                vote_ok += 1
        results["投票融合"] = {"top1": round(vote_ok / len(gold), 4)}

    return {"goldset_mode": mode, "goldset_size": len(gold),
            "goldset_instances": sum(g["size"] for g in gold),
            "engines": results}
