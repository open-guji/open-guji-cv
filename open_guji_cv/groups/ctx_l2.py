"""文意路 L2：训练好的模型（sheldon 2026-10-28 定层级：L1 固定搭配 → L2 训练好的模型 → L3 大模型）。

现用一种模型：古汉语预训练模型 SikuRoBERTa（四库语料，HF `SIKU-BERT/sikuroberta`，钉 revision）**不微调**，
目标位换成 [MASK]，取最后一层目标位向量（768 维）＋目标位对 `feat_chars` 各字的填空 log 概率，标准化后过一个
逻辑回归小头（每组一份，几十 KB，`config/groups/l2model/<组>.json`）。小头用 L3 答案表（多家大模型读过的格）训，
按册 10 折留出定门槛（A24 10-27，`research/m7/ctx/l2model_train.py`）：

- 门槛：最高类概率 ≥ `thr` 才给字；类「其他」（组内字都不通）照给，交 `flow.decide_joint` 当「不是本组字」用；
- 组外形近字护栏：模型对 `other.chars`（自 臼 白…）的填空分 − 所判字的分 ≥ `other.d` → 弃权（「斷自陶唐」「窠臼」）；
- `right_only`：右邻字在某集合里只许给某字（己已巳：右邻是 丑卯巳未酉亥 → 只许「己」，干支「己未」）。

小头文件（`schema: ctx_model/1`）：`group`、`ver`、`encoder{name, revision}`、`feat_chars`、`classes`、`mean`、`scale`、
`coef`（类数×维）、`intercept`、`thr`、`other{chars, d}`、`right_only{右邻字集: 字}`。

编码器缺（没装 torch／transformers、权重拉不到）→ 弃权 `abstain:no_encoder`，留痕可查；本模块只在 `run` 时惰性 import 重依赖。
权重：环境变量 `GUJI_CTX_ENCODER_DIR` 指本地目录时用本地，否则按 `encoder.name`＋`revision` 从 HF 拉（走缓存）。
"""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

from .context import WIDTH
from .protocol import GroupVerdict

SCHEMA = "ctx_model/1"
OTHER = "其他"
MISSING = "□"


def load_head(path: str | Path) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA:
        raise ValueError(f"ctx_l2：{path} 不是 {SCHEMA}")
    return d


def head_fingerprint(path: str | Path | None) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else ""


class Encoder:
    """SikuRoBERTa 填空编码：`encode(left, right, chars)` → (目标位向量 list[float], {字: logp})。按窗口缓存。"""

    def __init__(self, name: str, revision: str | None = None, local_dir: str | None = None):
        import os
        import torch
        from transformers import AutoModelForMaskedLM, AutoTokenizer
        src = local_dir or os.environ.get("GUJI_CTX_ENCODER_DIR") or name
        kw = {} if src != name or not revision else {"revision": revision}
        self.tok = AutoTokenizer.from_pretrained(src, **kw)
        self.model = AutoModelForMaskedLM.from_pretrained(src, **kw).eval()
        self.torch = torch
        self._cache: dict = {}

    def encode(self, left: str, right: str, chars: str):
        key = (left, right, chars)
        if key in self._cache:
            return self._cache[key]
        torch, tok = self.torch, self.tok
        a = left[-WIDTH:].replace(MISSING, "[UNK]")
        b = right[:WIDTH].replace(MISSING, "[UNK]")
        pos = len(tok(a, add_special_tokens=False)["input_ids"]) + 1
        enc = tok(a + "[MASK]" + b, return_tensors="pt")
        with torch.no_grad():
            out = self.model(**enc, output_hidden_states=True)
        h = out.hidden_states[-1][0, pos].tolist()
        lp = torch.log_softmax(out.logits[0, pos], -1)
        ids = tok.convert_tokens_to_ids(list(chars))
        res = (h, {c: float(lp[i]) for c, i in zip(chars, ids)})
        if len(self._cache) > 50000:
            self._cache.clear()
        self._cache[key] = res
        return res


@lru_cache(maxsize=4)
def _encoder(name: str, revision: str | None) -> Encoder | None:
    try:
        return Encoder(name, revision)
    except Exception:          # noqa: BLE001 —— 缺 torch／transformers／权重：本方法弃权，不拖垮整步
        return None


def predict(head: dict, hidden: list, logp: dict) -> tuple[str, float]:
    """小头：标准化 → 线性 → softmax（二类时 sklearn 存一行系数，按 sigmoid）。→ (类, 概率)。"""
    x = list(hidden) + [logp[c] for c in head["feat_chars"]]
    z = [(v - m) / s if s else 0.0 for v, m, s in zip(x, head["mean"], head["scale"])]
    cls, W, b = head["classes"], head["coef"], head["intercept"]
    s = [sum(w * v for w, v in zip(row, z)) + bb for row, bb in zip(W, b)]
    if len(cls) == 2 and len(s) == 1:
        p1 = 1.0 / (1.0 + math.exp(-s[0]))
        return (cls[1], p1) if p1 >= 0.5 else (cls[0], 1.0 - p1)
    mx = max(s)
    e = [math.exp(v - mx) for v in s]
    k = max(range(len(e)), key=e.__getitem__)
    return cls[k], e[k] / sum(e)


def judge(head: dict, left: str, right: str, members, encoder=None) -> GroupVerdict:
    """一格 → `GroupVerdict`（via `ctx_l2`）。给字时 conf＝模型概率；「其他」→ char=None、why `abstain:other`、
    `other_conf: high`（与 L3 表的「其他」同一口径，共字组联判认它）。"""
    enc = encoder if encoder is not None else _encoder(head["encoder"]["name"], head["encoder"].get("revision"))
    if enc is None:
        return GroupVerdict(None, why="abstain:no_encoder", via="ctx_l2")
    oth = (head.get("other") or {}).get("chars", "")
    chars = "".join(dict.fromkeys(head["feat_chars"] + oth + "".join(c for c in head["classes"] if len(c) == 1)))
    hidden, lp = enc.encode(left or "", right or "", chars)
    ch, p = predict(head, hidden, lp)
    extra = {"p": round(p, 5), "top": ch, "model": head.get("ver")}
    if p < head["thr"]:
        return GroupVerdict(None, conf=p, why="abstain:low_p", via="ctx_l2", extra=extra)
    if ch == OTHER:
        return GroupVerdict(None, conf=p, why="abstain:other", via="ctx_l2", extra={**extra, "other_conf": "high"})
    if ch not in members:
        return GroupVerdict(None, conf=p, why="abstain:non_member", via="ctx_l2", extra=extra)
    if oth and ch in lp:
        gap = max(lp[c] for c in oth) - lp[ch]
        if gap >= (head.get("other") or {}).get("d", 0.0):
            return GroupVerdict(None, conf=p, why="abstain:other_form", via="ctx_l2", extra={**extra, "gap": round(gap, 2)})
    r1 = (right or "")[:1]
    for chars_set, only in (head.get("right_only") or {}).items():
        if r1 and r1 in chars_set and ch != only:
            return GroupVerdict(None, conf=p, why="abstain:right_only", via="ctx_l2", extra=extra)
    extra.pop("top")                         # 只在弃权时留：给 L3 在线当参考（`methods.CtxOnline`）
    return GroupVerdict(ch, conf=p, why="agree", via="ctx_l2", extra=extra)
