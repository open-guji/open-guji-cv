"""3b `glyph_near` 的字形方法登记表（2026-11-27，第三步重构）。

一个字组可以挂几个方法，写在书配置 `params.glyph_near.groups.<组>.methods` 里：`{方法名: 模型目录}`。
方法只回答「这张字块图在组内各字里更像哪个」，给组内每个字一个分，外加证据；**不定字、不放行**。
校准（分 → p）也由方法自己带的校准表做，但只在收尾 `glyph_analyzer` 里调，3b 产物里存的是原始分。

接口（以后的方法照这个写，第四步那些看图判字的方法迁过来也照这个）：

    m = load_method(name, model_path)         # name 如 "cnn_small"；model_path 是模型目录或单个模型文件
    outs = score(m, patches, book_id, ctx=ctx, cells=cells)
                                              # 即 m.score(patches, book_id[, ctx=…, cells=…])
                                              # patches: 字块图（uint8，白底黑字，任意尺寸），哪种图见 m.patch
                                              # → [{"sims": {字: 分}, "evidence": {...}}, …]，与 patches 一一对应
    p = m.calibrate(sims)                     # {字: 校准后的 p} 或 None（没有校准表）
    m.fingerprint()                           # 模型目录（或文件）的 sha256 短哈希，进参数指纹
    m.model_sha                               # 模型版本，写进 3b 产物 `PageNear.models` 与收尾 `near.methods.*.model`

- `m.patch`（类属性，可缺）：方法吃哪种字块图。`"raw"`（缺省）＝原图灰度按 `bbox_page` 裁块；`"char_patch"`＝第二步
  切字缓存里的字块图（`ctx.image("char_patch", patch_key)`，第四步 seed_admit 各判官读的就是这个）。
  3b 按它给图，方法自己不读图。
- **可选 ctx**（2026-11-28 加）：方法的 `score` 声明了 `ctx`／`cells` 参数（或 `**kwargs`）才传，老方法不认也照用（`score()` 用
  `inspect` 判）。`ctx` 是 `RunContext`（要读本书库、3a 候选的方法用，如以后的 book_knn／near_knn）；`cells` 与 patches
  一一对应，每格 `{id, page, col, slot, sub, patch_key, char, candidates}`（`char`／`candidates` 是 3a 的首位与候选）。
  **方法不许改 ctx 里的东西**，只读。

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

## rr_shape（入人八，第四步 group_flow 的书级刻形判法搬来的样板，2026-11-28）

包的是 `groups.rr_shape.judge`（seed_admit `_rr_shape_pass` 用的同一个函数，同一张图同一个模型逐位同一结论同一分），
吃 `char_patch` 字块图。模型就是第四步那份书级模型文件（数据目录 `config/groups/rr_shape.json`，`schema: rr_shape/1`，
`research/char_groups/rr/qtw_shape_train.py` 导出），书配置直接指它：`methods: {rr_shape: config/groups/rr_shape.json}`；
也可以给目录，目录里放 `model.json`。

- `sims`：几何判成 八 → `{八: 1, 人: 0, 入: 0}`；走逻辑回归 → `{入: σ(s), 人: 1−σ(s), 八: 0}`（s＝`judge` 给的决策值，
  已按 3 位小数取整，同第四步 `evidence.rr_shape.score`）；弃权里没算出 s 的（无墨、组外字护栏、几何不明、NaN）→ `{}`。
  分差不够（`abstain:low_margin`）仍给 sims，弃权记在证据里。
- `evidence`：`{method: "rr_shape", char, why, nn, score, geo}`，后五键与第四步 `evidence.rr_shape` 同键同值（`char` 是现役判法的结论，弃权为 None）。**4d 的读口就是这里**（`seed_admit_shapes._near_from_3b`，开关 `group_flow_near_from_3b`，cv #1999）：按 `NearMethodOut.method` 冒号前是 `rr_shape` 取，证据带 `error` 的格不取；模型对不对比 `methods_sha` 里的 `rr_shape=<指纹>`。
- 校准：模型文件旁边的 `<文件名去 .json>.calib.json`（给目录时是目录里的 `calib.json`），格式
  `{"format": "near-calib/1", "knots": {"入": [[σ(s)…], [p…]]}, "rule": {"八": p}}`：逻辑回归那一路按 knots 映 `入` 的 p、`人`＝1−p；
  几何判 八 的那一路 p 取 `rule.八`。**现在没有校准表**（`calibrate` 返回 None，收尾不出 p）；要标就拿训练脚本按册留出那一遍的
  (s, 放行字) 做保序回归，或人裁样本。

## wu_shape（嗚鳴，第四步 group_flow 的书级刻形判法搬来，2026-11-28）

包的是 `groups.wu_shape.judge`（seed_admit `_wu_shape_pass` 用的同一个函数），吃 `char_patch` 字块图。模型就是第四步那份
书级模型文件（数据目录 `config/groups/wu_shape.json`，`schema: wu_shape/1`），书配置直接指它：
`wu: {ref: wu, trigger: cands, methods: {wu_shape: config/groups/wu_shape.json}}`；也可以给目录，目录里放 `model.json`。

- `sims`：`{鳴: p, 嗚: 1−p}`（p＝`judge` 给的 鳴 概率，已按 4 位小数取整，同第四步 `evidence.wu_shape.p`；1−p 也取 4 位）；
  取不出右半（`abstain:no_ink`）→ `{}`。p 在门槛中间（`abstain:low_p`）仍给 sims，弃权记在证据里。
- `evidence`：`{method: "wu_shape", char, why, p}`，后三键＝`judge()` 返回的整个 dict（第四步 `evidence.wu_shape` 存的就是它，
  无墨弃权没有 `p`）。4d 读时去掉 `method` 就是第四步要存的那份。模型对不对比 `methods_sha` 里的 `wu_shape=<指纹>`
  （`method_fingerprint("wu_shape", group_flow_wu_shape)`）；`model_sha` 与第四步参数指纹 `ws` 段同算法（`wu_shape.fingerprint`）。
- 现役第四步只判**本格字（库首位）是 嗚鳴** 的格（整理本／字组／库前几名有 嗚鳴 都不算）；3b 用 `trigger: cands` 罩住它
  （3a 首位或前 topk 名里有 嗚鳴 就跑），多跑的格 4d 不读。
- 校准：模型文件旁边的 `<文件名去 .json>.calib.json`（给目录时是目录里的 `calib.json`），格式
  `{"format": "near-calib/1", "knots": {"鳴": [[p…], [校准 p…]]}}`，`嗚`＝1−p。**现在没有校准表**（`calibrate` 返回 None，收尾不出 p）。

## hou_shape（候𠋫，第四步 group_flow 的书级刻形判法搬来，2026-11-28）

包的是 `groups.hou_shape.judge`（seed_admit `_hou_shape_pass` 主遍与 `group_flow_hou_shape_late` 晚跑遍用的同一个函数），
吃 `char_patch` 字块图。模型就是第四步那份书级文件（数据目录 `config/groups/hou_shape.json`），书配置直接指它：
`hou: {ref: hou, trigger: cands, methods: {hou_shape: config/groups/hou_shape.json}}`；也可以给目录，目录里放 `model.json`。
两种 schema：

- `hou_shape/2`（小网）：`judge` 给 候 的概率 p（4 位）→ `sims`＝`{候: p, 𠋫: 1−p}`，同 wu_shape。
- `hou_shape/1`（几何量）：`judge` 给 亻 右边第二竖的相对长 v（4 位），`v < lo` 判 候、`v ≥ hi` 判 𠋫、其间弃权。v 不是概率，
  3b 用一个**与现役判定一致的单调映射**出分：`候 = σ(ln9 · (lo + hi − 2v) / (hi − lo))`、`𠋫 = 1 − 候`（各取 4 位）。
  v＝lo 时 候＝0.9、v＝(lo+hi)/2 时 0.5、v＝hi 时 0.1，所以现役判 候 的格 候 ≥ 0.9、判 𠋫 的格 候 ≤ 0.1，弃权的格在 (0.1, 0.9)，
  最高分的字总是现役判的那个字；v 越长越像 𠋫，保序（校准表可直接拿它做保序回归）。`hi − lo < 0.001`（几乎没有中间档）时按判出的字给 1／0（弃权 0.5）。
- 无墨弃权（`abstain:no_ink`）→ `{}`；弃权在中间（`abstain:mid`）仍给 sims。
- `evidence`：`{method: "hou_shape", char, why, v|p}`，后三键＝`judge()` 整个返回值（第四步 `evidence.hou_shape` 存的那份）。
  4d 读时去掉 `method`；`model_sha` 与第四步参数指纹 `hs` 段同算法（`hou_shape.fingerprint`），`methods_sha` 里是 `hou_shape=<指纹>`。
- 现役第四步只碰**已放行**、字是 候／𠋫 的非人裁格，只改字、不改放行；晚跑遍（`group_flow_hou_shape_late`，5c vis_ruling
  放行之后）判法同一个，只是补判主遍时还没放行、没 `evidence.hou_shape` 的格。3b 不知道放行，按 3a 候选触发（`trigger: cands`，
  登记表 hou 组是 侯俟候𠉀𠋫），给的是原样判法结论；哪些格用、主遍还是晚跑遍、改不改字，都留在 4d。
  3b 也会在 侯／俟 格上出分（方法只认 候／𠋫，那些分没意义），4d 不读这些格。
- 校准：`<模型去 .json>.calib.json`（给目录时 `calib.json`），`{"format": "near-calib/1", "knots": {"候": [[分…], [p…]]}}`，
  按 `sims.候` 映、𠋫＝1−p。**现在没有校准表**（`calibrate` 返回 None，收尾不出 p）。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
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
    """模型目录里全部文件（名＋内容）的短哈希；给的是单个模型文件时只算它和同名校准表（`<去 .json>.calib.json`）。"""
    if d.is_file():
        h = hashlib.sha256()
        for f in (d, _sibling_calib(d)):
            if f.is_file():
                h.update(f.name.encode())
                h.update(hashlib.sha256(f.read_bytes()).digest())
        return h.hexdigest()[:16]
    h = hashlib.sha256()
    for f in sorted(d.iterdir()) if d.exists() else []:
        if f.is_file():
            h.update(f.name.encode())
            h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()[:16] if d.exists() else "missing"


def _sibling_calib(f: Path) -> Path:
    return f.with_name(f.name[:-5] + ".calib.json" if f.name.endswith(".json") else f.name + ".calib.json")


def _accepts(fn, name: str) -> bool:
    try:
        ps = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in ps or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in ps.values())


def score(m, patches: list, book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
    """调方法的 `score`：方法认 `ctx`／`cells` 才传（老方法只收 `patches, book_id`，照旧调）。"""
    kw = {}
    if _accepts(m.score, "ctx"):
        kw["ctx"] = ctx
    if _accepts(m.score, "cells"):
        kw["cells"] = cells
    return m.score(patches, book_id, **kw)


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

    patch = "raw"

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

    @property
    def model_sha(self) -> str:
        return self.fingerprint()


class RrShape:
    """入人八 书级刻形判法（`groups.rr_shape`）包成 3b 方法，见模块头「rr_shape」。"""

    patch = "char_patch"
    def __init__(self, path: Path):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        cal = p / "calib.json" if p.is_dir() else _sibling_calib(p)
        from . import rr_shape
        self.model = rr_shape.load(str(self.path))
        self.calib = json.loads(cal.read_text(encoding="utf-8")) if cal.is_file() else None
        if self.calib is not None and self.calib.get("format") != "near-calib/1":
            raise ValueError(f"{cal} format 不是 near-calib/1：{self.calib.get('format')!r}")

    @staticmethod
    def sims_of(v: dict) -> dict[str, float]:
        """`rr_shape.judge` 的结果 → 组内各字的分（只由 judge 的结论与决策值算，不另跑模型）。"""
        if v.get("char") == "八" and "score" not in v:
            return {"八": 1.0, "人": 0.0, "入": 0.0}
        s = v.get("score")
        if s is None:
            return {}
        q = round(1.0 / (1.0 + math.exp(-float(s))), 4)
        return {"入": q, "人": round(1.0 - q, 4), "八": 0.0}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from . import rr_shape
        out = []
        for g in patches:
            v = rr_shape.judge(g, self.model)
            trail = {"method": "rr_shape", **{k: v[k] for k in ("char", "why", "nn", "score", "geo") if k in v}}
            out.append({"sims": self.sims_of(v), "evidence": trail})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        if not self.calib or not sims:
            return None
        if sims.get("八") == 1.0:
            pb = (self.calib.get("rule") or {}).get("八")
            return None if pb is None else {"八": round(float(pb), 4)}
        kn = (self.calib.get("knots") or {}).get("入")
        if not kn or "入" not in sims:
            return None
        xs, ys = kn
        p = float(np.interp(sims["入"], xs, ys))
        return {"入": round(p, 4), "人": round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹里的 `rs` 段同算法（`rr_shape.fingerprint`），4d 拿它对 `group_flow_rr_shape`。"""
        from . import rr_shape
        return rr_shape.fingerprint(str(self.path))


def _load_calib(p: Path) -> dict | None:
    """方法的校准表：给目录时是目录里的 `calib.json`，给文件时是同名 `<去 .json>.calib.json`；没有 → None。"""
    cal = p / "calib.json" if p.is_dir() else _sibling_calib(p)
    d = json.loads(cal.read_text(encoding="utf-8")) if cal.is_file() else None
    if d is not None and d.get("format") != "near-calib/1":
        raise ValueError(f"{cal} format 不是 near-calib/1：{d.get('format')!r}")
    return d


class WuShape:
    """嗚鳴 书级刻形判法（`groups.wu_shape`）包成 3b 方法，见模块头「wu_shape」。"""

    patch = "char_patch"

    def __init__(self, path: Path):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from . import wu_shape
        self.model = wu_shape.load(str(self.path))
        self.chars = tuple(self.model.get("chars", ["嗚", "鳴"]))
        self.calib = _load_calib(p)

    def sims_of(self, v: dict) -> dict[str, float]:
        """`wu_shape.judge` 的结果 → `{鳴: p, 嗚: 1−p}`（p 用 judge 已取整的那个值，不另跑模型）；没有 p → `{}`。"""
        q = v.get("p")
        if q is None:
            return {}
        wu, ming = self.chars
        return {ming: float(q), wu: round(1.0 - float(q), 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from . import wu_shape
        out = []
        for g in patches:
            v = wu_shape.judge(g, self.model)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "wu_shape", **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        wu, ming = self.chars
        kn = (self.calib or {}).get("knots", {}).get(ming)
        if not kn or ming not in sims:
            return None
        xs, ys = kn
        p = float(np.interp(sims[ming], xs, ys))
        return {ming: round(p, 4), wu: round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹里的 `ws` 段同算法（`wu_shape.fingerprint`）。"""
        from . import wu_shape
        return wu_shape.fingerprint(str(self.path))


class HouShape:
    """候𠋫 书级刻形判法（`groups.hou_shape`，schema /1 几何量、/2 小网）包成 3b 方法，见模块头「hou_shape」。"""

    patch = "char_patch"

    def __init__(self, path: Path):
        p = Path(path)
        self.src = p
        self.path = p / "model.json" if p.is_dir() else p
        from . import hou_shape
        self.model = hou_shape.load(str(self.path))
        self.chars = tuple(self.model.get("chars", ["候", "𠋫"]))
        self.calib = _load_calib(p)

    def sims_of(self, v: dict) -> dict[str, float]:
        """`hou_shape.judge` 的结果 → `{候: q, 𠋫: 1−q}`（只用 judge 已取整的 p 或 v，不另跑模型）；都没有 → `{}`。"""
        hou, alt = self.chars
        if v.get("p") is not None:
            q = float(v["p"])
        elif v.get("v") is not None:
            lo, hi = float(self.model["lo"]), float(self.model["hi"])
            if hi - lo >= 1e-3:                 # v 已取 4 位：中间档够宽，取整挪不过 0.5
                z = math.log(9.0) * (lo + hi - 2.0 * float(v["v"])) / (hi - lo)
                q = round(1.0 / (1.0 + math.exp(-min(50.0, max(-50.0, z)))), 4)     # 截到 ±50：窄中间档时 exp 不溢出
            else:                               # 几乎没有中间档：按判出的字给分
                q = {hou: 1.0, alt: 0.0}.get(v.get("char"), 0.5)
        else:
            return {}
        return {hou: q, alt: round(1.0 - q, 4)}

    def score(self, patches: list[np.ndarray], book_id: str, ctx=None, cells: list | None = None) -> list[dict]:
        from . import hou_shape
        out = []
        for g in patches:
            v = hou_shape.judge(g, self.model)
            out.append({"sims": self.sims_of(v), "evidence": {"method": "hou_shape", **v}})
        return out

    def calibrate(self, sims: dict[str, float]) -> dict[str, float] | None:
        hou, alt = self.chars
        kn = (self.calib or {}).get("knots", {}).get(hou)
        if not kn or hou not in sims:
            return None
        xs, ys = kn
        p = float(np.interp(sims[hou], xs, ys))
        return {hou: round(p, 4), alt: round(1.0 - p, 4)}

    def fingerprint(self) -> str:
        return _dir_fingerprint(self.src)

    @property
    def model_sha(self) -> str:
        """模型文件的版本，与第四步参数指纹里的 `hs` 段同算法（`hou_shape.fingerprint`）。"""
        from . import hou_shape
        return hou_shape.fingerprint(str(self.path))


METHODS = {"cnn_small": CnnSmall, "rr_shape": RrShape, "wu_shape": WuShape, "hou_shape": HouShape}

_CACHE: dict[tuple[str, str], object] = {}


def load_method(name: str, model_dir: str):
    """方法名＋模型目录（或单个模型文件）→ 方法对象（按解析后的路径缓存）。"""
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
