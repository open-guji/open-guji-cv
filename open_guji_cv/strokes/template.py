"""笔画模板与模板库。

- 通用模板：Make Me a Hanzi `graphics.txt`（逐笔中线，9574 简繁）＋ cnchar-order（6939 简体的逐笔笔画名）。
  数据文件不进本仓，由调用方给路径（将来走模型系统按 sha 取回，见设计稿第二节、A20 口径）。
- 本书模板：用通用模板把本书该字的人裁刻例逐个贴一遍，逐笔轨迹按字框归一后取平均（`build_book_template`）。
- 模板库 `TemplateBank`：{字: 模板} ＋ 量几何用的类统计 {"<模板字>|<成员字>": 均值／标准差／例数}，一本书一份 JSON。

坐标：字框归一到 0–1000，(y, x)。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np

from ._ink import arclen, binarize, ink_bbox, resample

UNIT = 1000.0
#: 通用模板重采样步长（UNIT 坐标）。配准时按字框整体缩放，点数沿用到本书模板。
STEP = 12.0


@dataclass(frozen=True)
class TStroke:
    name: str               # 笔画名（cnchar 的 25 类）；繁体缺名时由中线几何推断，带 * 号
    pts: np.ndarray         # 中线 (n, 2)，(y, x)

    def to_json(self) -> dict:
        return {"name": self.name, "pts": np.round(self.pts, 1).tolist()}


@dataclass(frozen=True)
class StrokeTemplate:
    char: str
    strokes: tuple
    source: str = "generic"     # "mmh" | "book:<书ID>@<库 rev>" | 自定
    n: int = 0                  # 本书模板用了几个刻例；通用模板为 0

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.strokes]

    def to_json(self) -> dict:
        return {"char": self.char, "source": self.source, "n": self.n,
                "strokes": [s.to_json() for s in self.strokes]}

    @classmethod
    def from_json(cls, d: dict) -> "StrokeTemplate":
        return cls(char=d["char"], source=d.get("source", ""), n=int(d.get("n", 0)),
                   strokes=tuple(TStroke(s["name"], np.asarray(s["pts"], float)) for s in d["strokes"]))

    @property
    def fingerprint(self) -> str:
        return _sha(self.to_json())


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def normalize(strokes: Iterable[tuple[str, np.ndarray]], bbox=None) -> tuple:
    """把 [(名, 点)] 按 bbox（缺省取点的外框）归一到 0–UNIT。"""
    strokes = [(n, np.asarray(p, float)) for n, p in strokes]
    if bbox is None:
        allp = np.vstack([p for _, p in strokes])
        lo, hi = allp.min(0), allp.max(0)
    else:
        lo, hi = np.array(bbox[:2], float), np.array(bbox[2:], float)
    span = np.maximum(hi - lo, 1e-6)
    return tuple(TStroke(n, (p - lo) / span * UNIT) for n, p in strokes)


# ---------------------------------------------------------------- 通用模板

def _infer_name(pts: np.ndarray) -> str:
    from .skeleton import orient_and_name
    sts = orient_and_name(resample(pts, 4.0), 20.0, 1024.0, False)
    return "".join(s.name for s in sts) + "*"


def load_generic(mmh_path, cnchar_path=None, chars: Iterable[str] | None = None) -> dict[str, StrokeTemplate]:
    """读 Make Me a Hanzi graphics.txt（每行一个 JSON，含 character、medians）与 cnchar-order
    （{"order": {字: [笔码…]}, "map": {笔码: {"name": "横|…"}}}），出 {字: 通用模板}。
    MMH 坐标 1024 见方、y 朝上：图像 y = 900 − y。"""
    want = set(chars) if chars is not None else None
    order, cmap = {}, {}
    if cnchar_path:
        cn = json.loads(Path(cnchar_path).read_text(encoding="utf-8"))
        order, cmap = cn["order"], cn["map"]
    out = {}
    with open(mmh_path, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            ch = d["character"]
            if want is not None and ch not in want:
                continue
            meds = [np.array([[900 - y, x] for x, y in m], float) for m in d["medians"]]
            names = None
            if ch in order and len(order[ch]) == len(meds):
                names = [cmap[c]["name"].split("|")[0] for c in order[ch]]
            sts = [(names[k] if names else _infer_name(p), p) for k, p in enumerate(meds)]
            out[ch] = from_polylines(ch, sts, source="mmh")
    return out


def from_polylines(char: str, strokes: Iterable[tuple[str, np.ndarray]], source: str = "generic") -> StrokeTemplate:
    """[(笔名, 中线点 (y,x))] → 模板（外框归一、等距重采样）。测试与自定模板用。"""
    norm = normalize(strokes)
    return StrokeTemplate(char=char, source=source,
                          strokes=tuple(TStroke(s.name, resample(s.pts, STEP)) for s in norm))


# ---------------------------------------------------------------- 本书模板

def fit_to_unit(fit) -> list[np.ndarray]:
    """一次配准的逐笔轨迹，按字图墨框归一到 0–UNIT。"""
    lo = np.array(fit.bbox[:2], float)
    span = np.maximum(np.array(fit.bbox[2:], float) - lo, 1e-6)
    return [(s.pts - lo) / span * UNIT for s in fit.strokes]


def build_book_template(images: Iterable[np.ndarray], base: StrokeTemplate, params=None,
                        source: str = "book", min_n: int = 1) -> StrokeTemplate | None:
    """用通用模板 base 把本书刻例逐个贴上，逐笔平均成本书模板。刻例少于 min_n 返回 None（调用方退回通用模板）。"""
    from .register import register
    runs = [fit_to_unit(register(g, base, params)) for g in images]
    if len(runs) < max(1, min_n):
        return None
    return average(base, runs, source=source)


def average(base: StrokeTemplate, runs: list[list[np.ndarray]], source: str = "book") -> StrokeTemplate:
    """逐笔平均若干次归一后的轨迹（点数沿用 base）。留一评测时调用方自己去掉那一例再平均。"""
    sts = tuple(TStroke(base.strokes[k].name, np.mean([r[k] for r in runs], 0))
                for k in range(len(base.strokes)))
    return StrokeTemplate(char=base.char, strokes=sts, source=source, n=len(runs))


# ---------------------------------------------------------------- 模板库

@dataclass
class TemplateBank:
    templates: dict = field(default_factory=dict)     # {字: StrokeTemplate}
    stats: dict = field(default_factory=dict)         # {"<模板字>|<成员字>": {"mean": [...], "sd": [...], "n": k}}
    meta: dict = field(default_factory=dict)          # {"book": …, "rev": …, "params": …}

    def get(self, ch: str) -> StrokeTemplate | None:
        return self.templates.get(ch)

    def to_json(self) -> dict:
        return {"meta": self.meta, "stats": self.stats,
                "templates": {c: t.to_json() for c, t in sorted(self.templates.items())}}

    @classmethod
    def from_json(cls, d: dict) -> "TemplateBank":
        return cls(templates={c: StrokeTemplate.from_json(t) for c, t in d.get("templates", {}).items()},
                   stats=d.get("stats", {}), meta=d.get("meta", {}))

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "TemplateBank":
        return cls.from_json(json.loads(Path(path).read_text(encoding="utf-8")))

    @property
    def fingerprint(self) -> str:
        return _sha(self.to_json())


__all__ = ["TStroke", "StrokeTemplate", "TemplateBank", "UNIT", "load_generic", "from_polylines",
           "build_book_template", "average", "fit_to_unit", "normalize", "arclen", "binarize", "ink_bbox"]
