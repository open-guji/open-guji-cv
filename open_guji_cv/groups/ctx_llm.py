"""文意路 L3 在线：管线里直接问大模型（sheldon 2026-10-28：「管线里不能调 Claude，这个要修复……同时注意统计 token 用量」）。

只问 L1 规则、L3 答案表、L2 模型都给不出字的格（`methods.CtxOnline`），一格一问：
- 系统提示＝该组的 `config/groups/<组>/prompt.md`（书名等占位符先填，`prompt_template`），打 `cache_control`，同组各格复用；
- 用户消息＝一行「id、前文【?】后文」（与离线批跑同一取法，`ctx_l3.render_cell`），结构化输出 `{char, conf, why}`；
- 答案**按窗口内容缓存**，不按格 id：格 id 改键、重跑都不重问，同一上下文跨册共用。缓存缺省是裁定库
  （`feedback.rulings`：模型的裁定事件，kind `ctx_ruling`，来源 llm，和人裁同一个事件库、同步到中心库），
  也可以给本地 jsonl（`AnswerCache`，脚本用）；出错、拒答不进缓存；
- 只收 conf=high、组内字；「其他」→ `abstain:other`（high 时 `other_conf: high`，共字组联判认它）。

密钥只从环境变量 `GUJI_ANTHROPIC_API_KEY` 读（不进仓、不进配置）；没有密钥 → 先查缓存，缓存没有就弃权 `abstain:no_api_key`，
与没开本层一样留人审。用量：每格的 token 记进证据（`tok`），本进程累计在 `USAGE`（`usage_summary()`），seed_admit 写进页结果。
本模块只在用到时惰性 import `anthropic`。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path

from .context import WIDTH
from .protocol import GroupVerdict

ENV_KEY = "GUJI_ANTHROPIC_API_KEY"
ENV_BASE = "GUJI_ANTHROPIC_BASE_URL"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "low"
OTHER = "其他"
CONFS = ("high", "mid", "low")
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

#: 本进程累计用量：calls 真问了几次、hits 缓存命中、errors 出错／拒答；token 四项按 API 的 usage 累加
USAGE: dict = {}
_LOCK = threading.Lock()


def _bump(**kw) -> None:
    with _LOCK:
        for k, v in kw.items():
            USAGE[k] = USAGE.get(k, 0) + (v or 0)


def usage_summary(reset: bool = False) -> dict:
    with _LOCK:
        out = dict(USAGE)
        if reset:
            USAGE.clear()
    return out


def cache_key(group: str, prompt_ver: str, model: str, left: str, right: str) -> str:
    s = "\x1f".join((group, prompt_ver, model, left[-WIDTH:], right[:WIDTH]))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]


class AnswerCache:
    """追加写的 jsonl：每行 `{k, char, conf, why, model, tok}`；后写的覆盖先写的。多进程同时追加：一行一次 write。"""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self._d: dict | None = None

    def _load(self) -> dict:
        if self._d is None:
            self._d = {}
            if self.path and self.path.exists():
                for line in self.path.read_text(encoding="utf-8").splitlines():
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue                      # 并发写坏的半行：跳过，下次重问
                    if isinstance(e, dict) and e.get("k"):
                        self._d[e["k"]] = e
        return self._d

    def get(self, k: str) -> dict | None:
        return self._load().get(k)

    # judge 用的统一接口（裁定库 `feedback.rulings.RulingCache` 同款）：问过的窗口直接取，没问过 None
    def lookup(self, group, prompt_ver, model, left, right):
        return self.get(cache_key(group, prompt_ver, model, left, right))

    def store(self, group, prompt_ver, model, left, right, e: dict, cell=None) -> None:
        self.put(cache_key(group, prompt_ver, model, left, right), e)

    def put(self, k: str, e: dict) -> None:
        e = {"k": k, **e}
        self._load()[k] = e
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _schema(members) -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["char", "conf", "why"],
            "properties": {"char": {"type": "string", "enum": sorted(members) + [OTHER]},
                           "conf": {"type": "string", "enum": list(CONFS)},
                           "why": {"type": "string"}}}


class Client:
    """`anthropic` 的薄包装：`ask(system, user, members, model, effort)` → (答案 dict｜None, usage dict, 错误码｜None)。"""

    def __init__(self, api_key: str, base_url: str | None = None):
        import anthropic
        # 显式给 base_url：本机若设了 ANTHROPIC_BASE_URL（别的工具用的）不跟着走
        self._a = anthropic
        self._c = anthropic.Anthropic(api_key=api_key, base_url=base_url or "https://api.anthropic.com", max_retries=4)

    def ask(self, system: str, user: str, members, model: str, effort: str):
        a = self._a
        try:
            r = self._c.beta.messages.create(
                model=model, max_tokens=4000, betas=[_FALLBACK_BETA], fallbacks="default",
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": _schema(members)}})
        except (a.BadRequestError, a.AuthenticationError, a.PermissionDeniedError, a.NotFoundError) as e:
            return None, {}, f"api_{getattr(e, 'status_code', 'err')}"
        except (a.RateLimitError, a.APIStatusError, a.APIConnectionError) as e:
            return None, {}, f"api_{getattr(e, 'status_code', 'conn')}"
        u = r.usage
        tok = {"in": u.input_tokens, "out": u.output_tokens,
               "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
               "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0, "model": r.model}
        if r.stop_reason == "refusal":
            return None, tok, "refusal"
        if r.stop_reason == "max_tokens":
            return None, tok, "max_tokens"
        text = next((b.text for b in r.content if b.type == "text"), "")
        try:
            ans = json.loads(text)
        except json.JSONDecodeError:
            return None, tok, "bad_json"
        return ans, tok, None


_CLIENT: dict = {}
_IMPORT_WARNED: set = set()
_log = logging.getLogger(__name__)


def _client():
    key = os.environ.get(ENV_KEY, "")
    if not key:
        return None
    if key not in _CLIENT:
        _CLIENT.clear()
        try:
            _CLIENT[key] = Client(key, os.environ.get(ENV_BASE) or None)
        except ImportError:        # 机器给了密钥却没装 anthropic：按没密钥处理（先查缓存，没有就弃权），不让整页失败
            # 2026-10-31：原来静默。worker 的 /opt/guji-venv 没装 llm 可选依赖，1.7 万格全记成 abstain:no_api_key，
            # 看起来像「没密钥」，其实是没装包。这里大声报一次。
            if key not in _IMPORT_WARNED:
                _IMPORT_WARNED.add(key)
                _log.warning("GUJI_ANTHROPIC_API_KEY 已设，但 anthropic 包装不上（venv 缺 llm 依赖：uv pip install 'anthropic>=2.3'）；"
                             "裁定库没命中的格都按 abstain:no_api_key 弃权")
            return None
    return _CLIENT[key]


def user_message(left: str, right: str) -> str:
    from .ctx_l3 import render_cell
    return ("**本条输入**（id、制表符、前文【?】后文）：\n" + render_cell("q1", left, right)
            + "\n\n本条单独问：不要数组，只输出一个 JSON 对象 {\"char\", \"conf\", \"why\"}。")


def judge(group: str, system: str, prompt_ver: str, left: str, right: str, members, *, model: str = DEFAULT_MODEL,
          effort: str = DEFAULT_EFFORT, cache=None, client=None, cell: str | None = None) -> GroupVerdict:
    """一格 → `GroupVerdict`（via `ctx_llm`）。extra：`llm_model`、`llm_conf`（大模型自报）、`cached`、`tok`（这一格真问时的用量）。"""
    left, right = (left or "")[-WIDTH:], (right or "")[:WIDTH]
    e = cache.lookup(group, prompt_ver, model, left, right) if cache else None
    extra: dict = {"llm_model": model}
    if e is not None:
        _bump(hits=1)
        extra["cached"] = True
    else:
        c = client if client is not None else _client()
        if c is None:
            return GroupVerdict(None, why="abstain:no_api_key", via="ctx_llm", extra=extra)
        ans, tok, err = c.ask(system, user_message(left, right), members, model, effort)
        _bump(calls=1, errors=1 if err else 0, input_tokens=tok.get("in"), output_tokens=tok.get("out"),
              cache_read_tokens=tok.get("cache_read"), cache_write_tokens=tok.get("cache_write"))
        extra["tok"] = {k2: tok[k2] for k2 in ("in", "out", "cache_read") if tok.get(k2)}
        if err:
            return GroupVerdict(None, why=f"abstain:llm_{err}", via="ctx_llm", extra=extra)
        e = {"char": ans.get("char"), "conf": ans.get("conf"), "why": str(ans.get("why") or "")[:60],
             "model": tok.get("model") or model, "tok": extra["tok"]}
        if cache:
            cache.store(group, prompt_ver, model, left, right, e, cell)
    ch, conf = e.get("char"), e.get("conf")
    extra["llm_conf"] = conf
    if ch == OTHER:
        return GroupVerdict(None, why="abstain:other", via="ctx_llm",
                            extra={**extra, "other_conf": "high" if conf == "high" else "low"})
    if ch not in members:
        return GroupVerdict(None, why="abstain:non_member", via="ctx_llm", extra=extra)
    if conf != "high":
        return GroupVerdict(None, why="abstain:low_conf", via="ctx_llm", extra={**extra, "top": ch})
    return GroupVerdict(ch, conf=1.0, why="agree", via="ctx_llm", extra=extra)


def cache_usage(paths) -> dict:
    """缓存文件里记的真问用量（每条答案只在第一次问时记一次）→ {格数, in, out, cache_read, 按模型的格数}。"""
    tot: dict = {"answers": 0, "in": 0, "out": 0, "cache_read": 0, "models": {}}
    for p in paths:
        for e in AnswerCache(p)._load().values():
            tot["answers"] += 1
            for k in ("in", "out", "cache_read"):
                tot[k] += (e.get("tok") or {}).get(k, 0)
            m = e.get("model") or "?"
            tot["models"][m] = tot["models"].get(m, 0) + 1
    return tot


if __name__ == "__main__":       # python -m open_guji_cv.groups.ctx_llm <缓存.jsonl …>：报 L3 在线用量
    import sys
    print(json.dumps(cache_usage(sys.argv[1:]), ensure_ascii=False, indent=1))
