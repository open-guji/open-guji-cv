"""字块图像＋文意 L4：把原图字块连同前后文交给大模型，让它同时按刻形与文意在组员里选（A24 2026-11-01，第 2 轮门辶于千子干）。

文意 L3（`ctx_llm`）只看文字、提示词还写明「字形不可靠」，门族／辶族／于千子干里常答「其他」或低置信，
或与整理本互相冲突；人看这些格靠的是「门里是什么、辶上是什么」＋词组，两样都要。
留出评测（殿本 vol20–99 已放行格随机 360 格，三组各 120）：high 307 格里 303 同放行字，4 个不同的里 3 个是 間／閒 异体、
1 个子／予 看图是大模型对；待审 13 格人看图判过的：high 全对、mid 的错在 間／閒。

用法见 `flow._vis_try`：只在字组流程**没放成**（留人审）或要**降审**的格上问，高置信且有别的证人（整理本、文意 L3、字形 ids）
同字才放；证据写 `trail` 里 solver=vis。答案按（组、字块哈希、前后文）进裁定库缓存。密钥同 `ctx_llm`（GUJI_ANTHROPIC_API_KEY）。
"""
from __future__ import annotations

import base64
import hashlib
import json

from . import ctx_llm
from .context import WIDTH

VER = "vis1"
SYSTEM = """你是古籍校勘助手。给你《欽定四庫全書總目》武英殿刻本里一个字位的**原图字块**（单字截图）和它的前后文，请判断这个位置刻的是候选字中的哪一个。
候选字彼此字形很近但意思不同，必须**同时**用两条证据：①字块的刻形（逐部件看：门里是什么、辶上是什么、竖钩有无、横画数量等）；②前后文的词组、人名书名、语法。
- 刻形清楚且与文意一致 → conf=high；
- 刻形与文意冲突：以刻形为准，但 conf 至多 mid；说明冲突在哪；
- 刻形看不清、文意又不能定 → conf=low；
- 字块切歪、残缺或像是候选以外的字 → char 填「其他」。
前后文取自机器识别，可能有错字。只输出 JSON：{"char":"…","conf":"high|mid|low","why":"≤40字，写出看到的刻形部件和文意依据"}。"""


def png_b64(patch) -> str:
    import cv2
    p = patch
    if getattr(p, "ndim", 2) == 3:
        p = cv2.cvtColor(p, cv2.COLOR_BGR2GRAY)
    h, w = p.shape[:2]
    s = max(1, int(200 / max(h, w)))
    q = cv2.resize(p, (w * s, h * s), interpolation=cv2.INTER_CUBIC)
    q = cv2.copyMakeBorder(q, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return base64.b64encode(cv2.imencode(".png", q)[1]).decode()


def patch_hash(patch) -> str:
    import numpy as np
    return hashlib.sha1(np.ascontiguousarray(patch).tobytes()).hexdigest()[:12]


def judge(group: str, members, patch, left: str, right: str, *, model: str = ctx_llm.DEFAULT_MODEL, cache=None, client=None,
          cell: str | None = None) -> dict | None:
    """→ {char, conf, why, cached}｜None（没密钥、出错、拒答）。char 是组员或「其他」。"""
    left, right = (left or "")[-WIDTH:], (right or "")[:WIDTH]
    ver = f"{VER}:{patch_hash(patch)}"
    e = cache.lookup(group, ver, model, left, right) if cache else None
    if e is not None:
        ctx_llm._bump(hits=1)
        return {"char": e.get("char"), "conf": e.get("conf"), "why": e.get("why"), "cached": True}
    c = client if client is not None else ctx_llm._client()
    if c is None:
        return None
    cands = sorted(set(members))
    txt = f"候选字：{'、'.join(cands)}、其他\n前文：{left}\n后文：{right}\n（目标位在前后文之间）"
    try:
        r = c._c.messages.create(model=model, max_tokens=4000, system=SYSTEM, messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png_b64(patch)}},
            {"type": "text", "text": txt}]}])
    except Exception:          # noqa: BLE001 —— 网络、限流、拒答：弃权，不拖垮整页
        ctx_llm._bump(calls=1, errors=1)
        return None
    u = r.usage
    ctx_llm._bump(calls=1, input_tokens=u.input_tokens, output_tokens=u.output_tokens)
    t = next((b.text for b in r.content if b.type == "text"), "")
    try:
        ans = json.loads(t[t.index("{"):t.rindex("}") + 1])
    except ValueError:
        ctx_llm._bump(errors=1)
        return None
    ch, conf = ans.get("char"), ans.get("conf")
    if conf not in ctx_llm.CONFS or (ch not in cands and ch != ctx_llm.OTHER):
        return None
    out = {"char": ch, "conf": conf, "why": str(ans.get("why") or "")[:60], "cached": False}
    if cache:
        cache.store(group, ver, model, left, right, {**out, "model": model, "tok": {"in": u.input_tokens, "out": u.output_tokens}}, cell)
    return out
