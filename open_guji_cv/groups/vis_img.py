"""第三步看图大模型 `glyph_vis` 的提示词、图渲染与一问（2026-11-28，CV3；接口草案 CV4 审定）。

与第四步 L4（`groups/vis_llm.py`，图＋前后文一问）不同，这里**只看图**：
- 提示词只含字块图与候选字，**不写书名、不给前后文、不给整理本**——答案语义是「刻形像哪个」，不是「这里该是哪个字」；
- 调用走 `ctx_llm.Client.ask`（结构化输出 schema 限定 char ∈ 候选∪{其他}、拒答回落、`max_retries`），不从自由文本抠 JSON；
- 真调模型只在 `GUJI_LLM_ONLINE=1` 且有密钥时（`ctx_llm._client()`）；缺省只读缓存。

## 键

- `img_sha(patch)`：对**读到的原字块**（渲染前，转灰度 uint8）算 `sha256("{h}x{w}|" + 字节)[:24]`，含形状（第四步 vis1 的
  `sha1(字节)[:12]` 不含形状）；
- `prompt_sha(prompt)`：`sha256(系统提示 + 用户模板 + 渲染口径版本)[:16]`；改了放大规则、白边、PNG 编码算换提示词；
- `cands_key(cands)`：候选按码位排序后拼起来（不含「其他」）。

本模块不读写缓存（缓存在 `feedback/vis_glyph.py`），只管「怎么问」。
"""
from __future__ import annotations

import base64
import hashlib

from . import ctx_llm

OTHER = ctx_llm.OTHER
CONFS = ctx_llm.CONFS

#: 渲染口径版本：灰度、按整数倍放大到长边约 200px（INTER_CUBIC）、四周补 20px 白边、PNG。改了任何一项要换这里
RENDER_VER = "r1:gray,int-scale-200,cubic,pad20,png"

SYSTEM_IMG_1 = """你是古籍刻本字形鉴定助手。给你古籍刻本里一个字位的单字截图，和几个候选字。请只按图上的刻形判断它刻的是候选字中的哪一个。
- 候选字彼此字形很近，要逐部件看：门里是什么、辶上是什么、竖钩有无、横画数量、点画位置等；
- 只看刻形，不要猜文意，也不要按哪个字更常见来选；
- 刻形清楚、只像其中一个 → conf=high；像其中一个但有部件看不清 → conf=mid；看不清、拿不准 → conf=low；
- 截图切歪、残缺，或刻的明显是候选以外的字 → char 填「其他」。
只输出 JSON：{"char":"…","conf":"high|mid|low","why":"≤40字，只写看到的刻形部件依据"}。"""

USER_TMPL_1 = "候选字：{cands}、其他"

#: 提示词登记：id → (系统提示, 用户模板)。书配置 `glyph_vis.prompt` 写 id
PROMPTS: dict[str, tuple[str, str]] = {
    "vis-img-1": (SYSTEM_IMG_1, USER_TMPL_1),
}


def client():
    """在线 client（`GUJI_LLM_ONLINE=1` 且有 `GUJI_ANTHROPIC_API_KEY`，同 `ctx_llm._client`）或 None。"""
    return ctx_llm._client()


def bump(**kw) -> None:
    """用量记进 `ctx_llm.USAGE`（键带 `vis_img_` 前缀，不和 L3／L4 混）。"""
    ctx_llm._bump(**kw)


def prompt_sha(prompt: str) -> str:
    sys_, tmpl = PROMPTS[prompt]
    return hashlib.sha256((sys_ + "\x1f" + tmpl + "\x1f" + RENDER_VER).encode("utf-8")).hexdigest()[:16]


def gray(patch):
    """字块 → 二维 uint8 灰度（三通道按 BGR 转）。"""
    import numpy as np
    p = patch
    if getattr(p, "ndim", 2) == 3:
        import cv2
        p = cv2.cvtColor(p, cv2.COLOR_BGR2GRAY)
    if p.dtype != np.uint8:
        p = np.clip(p, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(p)


def img_sha(patch) -> str:
    """原字块（渲染前）的键：含形状，同字节不同 h×w 不撞。"""
    g = gray(patch)
    h, w = g.shape[:2]
    return hashlib.sha256(f"{h}x{w}|".encode("ascii") + g.tobytes()).hexdigest()[:24]


def render_png(patch) -> bytes:
    """送模型的那张图（`RENDER_VER`）：灰度，整数倍放大到长边约 200px，四周补 20px 白边，PNG。"""
    import cv2
    g = gray(patch)
    h, w = g.shape[:2]
    s = max(1, int(200 / max(h, w, 1)))
    q = cv2.resize(g, (w * s, h * s), interpolation=cv2.INTER_CUBIC) if s > 1 else g
    q = cv2.copyMakeBorder(q, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return cv2.imencode(".png", q)[1].tobytes()


def sort_cands(cands) -> list[str]:
    """候选去重、去掉「其他」、按码位排序（同集合同字节）。"""
    return sorted({str(c) for c in cands if c and str(c) != OTHER})


def cands_key(cands) -> str:
    return "".join(sort_cands(cands))


def user_content(patch, cands, prompt: str) -> list[dict]:
    """用户消息：图＋一行候选字。"""
    _sys, tmpl = PROMPTS[prompt]
    data = base64.b64encode(render_png(patch)).decode()
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
            {"type": "text", "text": tmpl.format(cands="、".join(sort_cands(cands)))}]


def ask(client, patch, cands, *, prompt: str, model: str, effort: str):
    """真问一次 → (答案 {char, conf, why}｜None, token {in, out, cache_read}, 错误码｜None)。
    `client` 是 `ctx_llm.Client`（测试传假 client）。答案不合规（字不在候选∪其他、conf 不认）记 `bad_answer`。"""
    sys_, _tmpl = PROMPTS[prompt]
    cs = sort_cands(cands)
    ans, tok, err = client.ask(sys_, user_content(patch, cs, prompt), cs, model, effort)
    t = {k: tok[k] for k in ("in", "out", "cache_read") if tok.get(k)}
    ctx_llm._bump(vis_img_calls=1, vis_img_errors=1 if err else 0, vis_img_input_tokens=tok.get("in"),
                  vis_img_output_tokens=tok.get("out"))
    if err:
        return None, t, err
    ch, conf = (ans or {}).get("char"), (ans or {}).get("conf")
    if conf not in CONFS or (ch not in cs and ch != OTHER):
        ctx_llm._bump(vis_img_errors=1)
        return None, t, "bad_answer"
    return {"char": ch, "conf": conf, "why": str(ans.get("why") or "")[:60]}, t, None
