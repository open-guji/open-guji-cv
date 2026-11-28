# -*- coding: utf-8 -*-
"""形近字对的按书分类器（5a.3，2026-11-18 Sheldon 定）：本书刻例上按对训的逻辑回归，吃相似度 CNN 的嵌入。

为什么按书、按对：统一嵌入本来分得开大多数形近对，分不开是因为拿去比的刻例不对——库里同字异形的刻例按放行字标、
没跟刻形，少见一形的刻例又太少。全唐文 001–045 册 81 对 34,596 格按册留出：只比现库刻例 93.0%，每形 1 个本书刻例
96.4%，4 例 98.2%，全部本书刻例上的逻辑回归 99.4%；把现库刻例并进来反而拉低。所以跨书共用的是嵌入模型，分类器按书建。
量法与数字见 ai-team `domain/CV/字形领域/形近字组字形判别基准-2026-11-18/`。

## 书级文件（数据目录 `config/groups/pair_clf.json`，随中心库走）

    {"version": 3, "snapshot": "…", "sim_model": "<嵌入模型 sha 前 12 位>",
     "pairs": {"淸清": {"a": "淸", "b": "清", "tier": 3, "w": [128 个数], "bias": 0.1, "p_min": 0.98,
                        "n": [843, 235], "held": {"n": 1078, "err": 1, "give": 1050, "give_err": 0}}, …},
     "context": ["己已", "已巳", "己巳", "千干", "天夭"]}

每对一个档（`tier`），随本书刻例积累由 `build` 重算，能升也能降：

- 0 借：本书某一形 0 例。没有分类器，只在文件里占位（`w` 为空）；借来的刻例只影响候选顺序，那是 5a.1 的事。
- 1 起步：两形都有但有一形不到 `MIN_PER_FORM` 例。分类器用各形刻例嵌入的均值之差搭一个（最近类心），只出证据。
- 2 可用：两形都够。逻辑回归，出证据；`p ≥ p_min` 时证据里带 `char`，供后面的步骤当一路证据。
- 3 终判：按册留出给字 ≥ `FINAL_MIN_GIVE` 格且零错。书配置开了 `final` 时在 5a 里直接定字。
- "context" 归文意：`context` 名单里的对（人定的，如己已巳刻本混用），以及两形都 ≥ `CONTEXT_MIN_PER_FORM` 例、按册留出
  强判准确率仍 < `CONTEXT_ACC`、又够不上终判的对（机器定的：刻例够了还分不开，就不再试字形）。只记证据
  `tier: context`，不给字。刻例再多以后重建，分得开了会自己回到档 2、3。

## 门槛怎么定的（全唐文 001–045 册，2026-11-18）

逻辑回归的概率量级跟正则强度走，`P_MIN` 是配着 `LR_C` 定的，两个要一起改。给字门槛取「不低于 `P_MIN`、且比按册留出里
把握最高的那个错再高 `P_MARGIN`」。门槛是在留出结果上挑的，所以另做了一层嵌套验证：门槛只用两折的留出结果定，到第三折
上数错。`LR_C=8、P_MIN=0.98、P_MARGIN=1.0` 时 66 对够终判，嵌套给字 21,535 格错 2 格（都在 三二）；不留余量错 14 格，
`P_MIN=0.9` 错 10 格。量法脚本在 ai-team 基准目录 `code/clf_explore2.py`。

## 不自我复制

`build` 的刻例只该来自独立证据定下的格（人裁、文意与整理本两路一致、聚类后人定名的类）。由本分类器定字的格
（`via="pair:…"`）不要回灌——那是拿自己的输出当标签。这条由生成刻例清单的一方保证，`build` 只认给它的清单。
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
from pathlib import Path

import numpy as np

MIN_PER_FORM = 4            # 少于此数的一形只搭最近类心（档 1）
FINAL_MIN_GIVE = 30         # 终判：按册留出给字至少这么多格
P_MIN = 0.98                # 给字门槛的下限；`build` 会按留出结果往上调
P_MARGIN = 1.0              # 门槛比留出里把握最高的错再高这么多（对数几率）
LR_C = 8.0                  # 逻辑回归正则强度的倒数；概率的量级跟它走，P_MIN 是配着它定的
CONTEXT_MIN_PER_FORM = 30   # 两形都有这么多例还分不开 → 归文意
CONTEXT_ACC = 0.985         # 「分不开」＝按册留出强判准确率低于此
REL_PATH = "config/groups/pair_clf.json"


def pair_key(a: str, b: str) -> str:
    """字对的键：两字按码位序拼起来，与方向无关。"""
    return "".join(sorted((a, b)))


# ---------- 读与判 ----------

@functools.lru_cache(maxsize=8)
def _load(path: str, mtime: float) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    pairs, by_char = {}, {}
    for key, p in sorted((d.get("pairs") or {}).items()):
        a, b = p["a"], p["b"]
        k = pair_key(a, b)
        w = np.asarray(p.get("w") or [], dtype=np.float32)
        pairs[k] = {**p, "key": k, "w": w if w.size else None}
        by_char.setdefault(a, []).append(k)
        by_char.setdefault(b, []).append(k)
    ctx = frozenset(pair_key(s[0], s[1:]) for s in (d.get("context") or ()) if len(s) >= 2)
    return {"version": d.get("version"), "snapshot": d.get("snapshot"), "sim_model": d.get("sim_model"),
            "pairs": pairs, "by_char": by_char, "context": ctx}


def load(path: str | Path) -> dict:
    p = Path(path)
    return _load(str(p), p.stat().st_mtime)


def check_sim_model(model: dict, sim_path: str) -> None:
    """分类器的权重是在某个相似度 CNN 的嵌入上训的，换了 `sim_model` 不重训，点乘出来的就是乱分（会按乱分改字）。
    文件里记的 `sim_model`（权重 sha256 前缀，至少 12 位；或模型目录名，如旧文件的 `glyph_sim_qtw`）对不上当前
    `glyph_match.sim_model` 就拒跑。没记的也拒跑：无从核对。重训：`scripts/build_pair_clf.py --sim-model <sha 前 12 位>`。"""
    from ..clustering.sim_cnn import model_sha256, resolve_model
    rec = str(model.get("sim_model") or "").strip()
    p = resolve_model(sim_path)
    sha = model_sha256(sim_path)
    if rec and ((len(rec) >= 12 and sha.startswith(rec.lower())) or rec in (p.parent.name, str(sim_path))):
        return
    raise ValueError(
        f"glyph_match.stages.pair：分类器文件记的嵌入模型是 {rec or '（没记）'}，当前 sim_model 是 {sim_path}（sha {sha[:12]}），"
        f"对不上。换了 sim_model 要在新嵌入上重训 pair_clf（build_pair_clf.py --sim-model {sha[:12]}），"
        f"或先从书配置去掉 glyph_match.stages.pair。")


def fingerprint(path: str | Path | None) -> str:
    """进参数指纹的值：文件内容哈希；没有文件返回 `none`。"""
    if not path or not Path(path).exists():
        return "none"
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def pairs_for(model: dict, top: str) -> list[str]:
    """这一格要问的字对：文件里含首位字的全部对；归文意的对也算（要记证据）。"""
    return list(model["by_char"].get(top, ())) + sorted(k for k in model["context"] if top in k and k not in model["pairs"])


def judge(model: dict, key: str, emb: np.ndarray) -> dict:
    """一对字判一格 → 证据 dict：`pair`、`tier`，有分类器时带 `p`（判成乙的概率）与 `lean`（偏向的字），
    过了给字门槛（档 ≥2 且把握 ≥ `p_min`）再带 `char`。"""
    if key in model["context"]:
        return {"pair": key, "tier": "context"}
    p = model["pairs"][key]
    ev: dict = {"pair": key, "tier": p["tier"]}
    if p["w"] is None or p["tier"] in (0, "context"):
        return ev
    z = float(p["w"] @ np.asarray(emb, dtype=np.float32)) + float(p.get("bias", 0.0))
    pb = 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, z))))
    ev["p"] = round(pb, 4)
    ev["lean"] = p["b"] if pb >= 0.5 else p["a"]
    if p["tier"] in (2, 3) and max(pb, 1.0 - pb) >= float(p.get("p_min", P_MIN)):
        ev["char"] = ev["lean"]
    return ev


def decide(model: dict, top: str, emb: np.ndarray, final: bool) -> tuple[list, str | None, str | None]:
    """一格过所有含首位字的对 → (各对证据, 定的字或 None, 定字的对)。
    定字条件：`final` 开着；没有一对归文意；有分类器的对（档 ≥1）全都给了字且一致；其中至少一对是档 3。
    档 0 的对（本书有一形还没有刻例）不拦：那一形在本书罕见，等有了刻例重建后自然进来。"""
    rows = [judge(model, k, emb) for k in pairs_for(model, top)]
    if not final or not rows or any(r["tier"] == "context" for r in rows):
        return rows, None, None
    asked = [r for r in rows if r["tier"] != 0]
    chars = {r.get("char") for r in asked}
    finals = [r["pair"] for r in asked if r["tier"] == 3]
    if len(chars) == 1 and None not in chars and finals:
        return rows, next(iter(chars)), finals[0]
    return rows, None, None


# ---------- 训练与验收 ----------

def _fit_lr(X: np.ndarray, y: np.ndarray, c: float = LR_C, iters: int = 300) -> tuple[np.ndarray, float]:
    """带 L2 的逻辑回归（两类按反比加权），牛顿法；不依赖 sklearn，运行时只要一个点积。X 是 L2 归一的嵌入。"""
    n, d = X.shape
    sw = np.where(y, n / (2.0 * max(y.sum(), 1)), n / (2.0 * max((~y).sum(), 1)))
    Xb = np.hstack([X, np.ones((n, 1))]).astype(np.float64)
    w = np.zeros(d + 1)
    reg = np.full(d + 1, 1.0 / c)
    reg[-1] = 1e-6
    yf = y.astype(np.float64)
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(Xb @ w, -40, 40)))
        g = Xb.T @ (sw * (p - yf)) + reg * w
        h = (Xb * (sw * p * (1 - p))[:, None]).T @ Xb + np.diag(reg)
        step = np.linalg.solve(h, g)
        w -= step
        if float(np.abs(step).max()) < 1e-7:
            break
    return w[:-1].astype(np.float32), float(w[-1])


def _fit_centroid(X: np.ndarray, y: np.ndarray, scale: float = 20.0) -> tuple[np.ndarray, float]:
    """刻例太少时：两形类心之差当方向，中点当零点。`scale` 只为把分数拉到像概率的量级，档 1 不给字。"""
    ma, mb = X[~y].mean(0), X[y].mean(0)
    w = (mb - ma) * scale
    return w.astype(np.float32), float(-(w @ (ma + mb)) / 2.0)


def _prob(w: np.ndarray, bias: float, X: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(X @ w + bias, -40, 40)))


def _held_out(X: np.ndarray, y: np.ndarray, fold: np.ndarray) -> np.ndarray | None:
    """按折（册）留出的概率；任何一折的训练部分有一形不到 `MIN_PER_FORM` 例就不算（返回 None）。"""
    out = np.full(len(y), np.nan)
    for f in np.unique(fold):
        tr = fold != f
        if min(int(y[tr].sum()), int((~y[tr]).sum())) < MIN_PER_FORM:
            return None
        w, b = _fit_lr(X[tr], y[tr])
        out[~tr] = _prob(w, b, X[~tr])
    return out


def _pick_p_min(p: np.ndarray, y: np.ndarray) -> tuple[float, int, int]:
    """留出概率上找给字门槛：不低于 `P_MIN`，且比留出里把握最高的那个错再高 `P_MARGIN`（对数几率上）。
    返回 (门槛, 给字数, 门槛之上的错数)。余量是为了门槛在没见过的册上还站得住，见模块头「门槛怎么定的」。"""
    conf = np.clip(np.maximum(p, 1 - p), 1e-9, 1 - 1e-9)
    ok = (p >= 0.5) == y
    lg = np.log(conf / (1 - conf))
    thr = math.log(P_MIN / (1 - P_MIN))
    if (~ok).any():
        thr = max(thr, float(lg[~ok].max()) + P_MARGIN)
    give = lg >= thr
    return 1.0 / (1.0 + math.exp(-thr)), int(give.sum()), int((give & ~ok).sum())


def build_pair(a: str, b: str, X: np.ndarray, y: np.ndarray, fold: np.ndarray) -> dict:
    """一对字建分类器并定档。`y` True＝乙（b）；`fold` 是每个刻例的折号（按册分，同册同折）。"""
    na, nb = int((~y).sum()), int(y.sum())
    rec: dict = {"a": a, "b": b, "n": [na, nb]}
    if min(na, nb) == 0:
        return {**rec, "tier": 0, "w": []}
    if min(na, nb) < MIN_PER_FORM:
        w, bias = _fit_centroid(X, y)
        return {**rec, "tier": 1, "w": [round(float(v), 5) for v in w], "bias": round(bias, 5)}
    w, bias = _fit_lr(X, y)
    rec.update(tier=2, w=[round(float(v), 5) for v in w], bias=round(bias, 5), p_min=P_MIN)
    p = _held_out(X, y, fold) if len(np.unique(fold)) >= 2 else None
    if p is None:
        return rec
    ok = (p >= 0.5) == y
    thr, give, give_err = _pick_p_min(p, y)
    rec["p_min"] = min(round(thr, 6), 0.999999)
    rec["held"] = {"n": int(len(y)), "err": int((~ok).sum()), "give": give, "give_err": give_err}
    if give >= FINAL_MIN_GIVE and give_err == 0:
        rec["tier"] = 3
    elif min(na, nb) >= CONTEXT_MIN_PER_FORM and float(ok.mean()) < CONTEXT_ACC:
        rec["tier"] = "context"                # 刻例够了、强判还不准、又挑不出一段零错的把握区间：不再试字形
    return rec


def build(exemplars: dict, emb: dict, fold_of, context=(), version: int = 1, snapshot: str = "", sim_model: str = "") -> dict:
    """整本书建一份。`exemplars`：{字对串（甲乙两字）: {格 id: 该格刻的字}}；`emb`：{格 id: 嵌入}；`fold_of(格 id)` → 折号。
    没有嵌入的格跳过；`context` 是人定归文意的对，不训。"""
    ctx = {pair_key(s[0], s[1:]) for s in context}
    pairs = {}
    for pk, cells in sorted(exemplars.items()):
        a, b = pk[0], pk[1:]
        if pair_key(a, b) in ctx:
            continue
        ids = [i for i, ch in cells.items() if i in emb and ch in (a, b)]
        if not ids:
            pairs[pair_key(a, b)] = {"a": a, "b": b, "n": [0, 0], "tier": 0, "w": []}
            continue
        X = np.stack([np.asarray(emb[i], dtype=np.float64) for i in ids])
        y = np.array([cells[i] == b for i in ids])
        fold = np.array([fold_of(i) for i in ids])
        pairs[pair_key(a, b)] = build_pair(a, b, X, y, fold)
    return {"version": version, "snapshot": snapshot, "sim_model": sim_model, "pairs": pairs,
            "context": sorted(ctx)}


def tier_counts(model_json: dict) -> dict:
    out: dict = {}
    for p in model_json["pairs"].values():
        out[str(p["tier"])] = out.get(str(p["tier"]), 0) + 1
    return out
