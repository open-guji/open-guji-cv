"""3b `glyph_near` 的字形方法登记表（2026-11-27，第三步重构）。

一个字组可以挂几个方法，写在书配置 `params.glyph_near.groups.<组>.methods` 里：`{方法名: 模型目录}`。
方法只回答「这张字块图在组内各字里更像哪个」，给组内每个字一个分，外加证据；**不定字、不放行**。
校准（分 → p）也由方法自己带的校准表做，但只在收尾 `glyph_analyzer` 里调，3b 产物里存的是原始分。

接口（以后的方法照这个写，第四步那些看图判字的方法迁过来也照这个）：

    m = load_method(name, model_dir)          # name 如 "cnn_small"
    outs = m.score(patches, book_id)          # patches: 灰度原图裁块（uint8，白底黑字，任意尺寸）
                                              # → [{"sims": {字: 分}, "evidence": {...}}, …]，与 patches 一一对应
    p = m.calibrate(sims)                     # {字: 校准后的 p} 或 None（没有校准表）
    m.fingerprint()                           # 模型目录里各文件的 sha256 拼起来的短哈希，进参数指纹

## cnn_small（宫／宮／官 是第一个）

殿本 ZM 11-26 训的四段卷积小 CNN，二分类，输入 64×64 灰度（原图按 `bbox_page` 裁、白底补成正方形、双线性缩放）。
模型目录：

    model.json   {"format": "near-cnn/1", "classes": ["官", "宫"], "merge": {"宮": "宫"},
                  "folds": ["fold0.pt", …], "fold_by": "vol_mod"}
    fold0.pt …   按册 5 折各训一个（册号 % 5 为留出折）
    calib.json   {"format": "near-calib/1", "knots": {"宫": [[原始分…], [p…]]}}（可缺）

`fold_by: vol_mod`：册 id 末尾的数字对折数取模，用**没见过这一册**的那个折模型打分（训练标签就是这些册的现行文本，
用全量模型给训练册打分会把它背过的错字原样吐回来）；册 id 里读不出数字（别的书）就各折取平均。
`merge`：异体不分的字（宮）和它归的字（宫）给同一个分（Sheldon 11-26：宫／宮 异体不分）。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
SIZE = 64


def resolve_dir(path: str) -> Path:
    """模型目录：绝对路径原样；相对路径先找数据目录（随中心库走），再找仓根（模型表 `repo` 类，`models/…`）。"""
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    from ..core.workspace import data_root
    droot = data_root()
    if droot is not None and (droot / p).exists():
        return droot / p
    return REPO / p


def prep_patch(gray: np.ndarray) -> np.ndarray:
    """灰度裁块 → 64×64（白底补成正方形再双线性缩放），与训练时的 `extract.py` 同一做法。"""
    from PIL import Image
    im = Image.fromarray(np.asarray(gray, dtype=np.uint8))
    w, h = im.size
    m = max(w, h)
    canvas = Image.new("L", (m, m), 255)
    canvas.paste(im, ((m - w) // 2, (m - h) // 2))
    return np.asarray(canvas.resize((SIZE, SIZE), Image.BILINEAR), dtype=np.uint8)


def vol_number(book_id: str) -> int | None:
    m = re.search(r"(\d+)\s*$", str(book_id or ""))
    return int(m.group(1)) if m else None


def _dir_fingerprint(d: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(d.iterdir()) if d.exists() else []:
        if f.is_file():
            h.update(f.name.encode())
            h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()[:16] if d.exists() else "missing"


def _small_net():
    import torch.nn as nn

    class Net(nn.Module):
        def __init__(self, n_out: int = 2):
            super().__init__()

            def blk(i, o):
                return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(),
                                     nn.Conv2d(o, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(), nn.MaxPool2d(2))
            self.f = nn.Sequential(blk(1, 16), blk(16, 32), blk(32, 64), blk(64, 96))
            self.d = nn.Dropout(0.3)
            self.o = nn.Linear(96, n_out)

        def forward(self, x):
            return self.o(self.d(self.f(x).mean((2, 3))))
    return Net


class CnnSmall:
    """四段卷积小 CNN，组内 N 分类（现役只有 宫／官 二分类）。"""

    def __init__(self, model_dir: Path):
        self.dir = Path(model_dir)
        meta = json.loads((self.dir / "model.json").read_text(encoding="utf-8"))
        if meta.get("format") != "near-cnn/1":
            raise ValueError(f"{self.dir}/model.json format 不是 near-cnn/1：{meta.get('format')!r}")
        self.classes: list[str] = list(meta["classes"])
        self.merge: dict[str, str] = dict(meta.get("merge") or {})
        self.folds: list[str] = list(meta["folds"])
        self.fold_by: str = str(meta.get("fold_by") or "")
        cal = self.dir / "calib.json"
        self.calib = json.loads(cal.read_text(encoding="utf-8")) if cal.exists() else None
        self._nets: dict[int, object] = {}

    def _net(self, k: int):
        net = self._nets.get(k)
        if net is None:
            import torch
            net = _small_net()(len(self.classes))
            net.load_state_dict(torch.load(self.dir / self.folds[k], map_location="cpu"))
            net.eval()
            self._nets[k] = net
        return net

    def _fold_of(self, book_id: str) -> int | None:
        if self.fold_by == "vol_mod":
            v = vol_number(book_id)
            return None if v is None else v % len(self.folds)
        return None

    def score(self, patches: list[np.ndarray], book_id: str) -> list[dict]:
        if not patches:
            return []
        import torch
        import torch.nn.functional as F
        x = np.stack([prep_patch(p) for p in patches])
        xt = torch.tensor(255 - x, dtype=torch.float32).unsqueeze(1) / 255.0      # 墨＝1，同训练
        k = self._fold_of(book_id)
        ks = [k] if k is not None else list(range(len(self.folds)))
        with torch.no_grad():
            prob = np.mean([F.softmax(self._net(i)(xt), 1).numpy() for i in ks], axis=0)
        fold = f"fold{k}" if k is not None else "mean"
        out = []
        for row in prob:
            sims = {c: round(float(v), 4) for c, v in zip(self.classes, row)}
            for a, b in self.merge.items():
                if b in sims:
                    sims[a] = sims[b]
            out.append({"sims": sims, "evidence": {"fold": fold}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        """二分类：按校准表把正类原始分映到 p，另一类取 1−p；异体（merge）跟它归的字同 p，但不重复算进总和。"""
        if not self.calib or len(self.classes) != 2:
            return None
        knots = self.calib.get("knots") or {}
        pos = next((c for c in self.classes if c in knots), None)
        if pos is None or pos not in sims:
            return None
        xs, ys = knots[pos]
        p_pos = float(np.interp(sims[pos], xs, ys))
        neg = next(c for c in self.classes if c != pos)
        out = {pos: round(p_pos, 4), neg: round(1.0 - p_pos, 4)}
        return out

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.dir)


METHODS = {"cnn_small": CnnSmall}

_CACHE: dict[tuple[str, str], object] = {}


def load_method(name: str, model_dir: str):
    cls = METHODS.get(name)
    if cls is None:
        raise ValueError(f"glyph_near：不认识的方法 {name!r}（已登记：{sorted(METHODS)}）")
    d = resolve_dir(model_dir)
    key = (name, str(d))
    m = _CACHE.get(key)
    if m is None:
        if not d.exists():
            raise FileNotFoundError(f"glyph_near 方法 {name} 的模型目录不存在：{d}")
        m = cls(d)
        _CACHE[key] = m
    return m


def method_fingerprint(name: str, model_dir: str) -> str:
    return f"{name}={_dir_fingerprint(resolve_dir(model_dir))}"
