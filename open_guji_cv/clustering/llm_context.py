"""Step6 上下文裁决：外部大模型评审员（**独立模块，未接生产**）。

## 这是什么，不是什么

用户 2026-09-10 的想法：n-gram、静态语言模型之外，引入外部大模型
（智谱 GLM / 阿里千问）做上下文裁决候选之间的选字。本模块是**调用层**——
读候选、拼 prompt、调 API、解析回答——不改 `context_decide.py`，也不接
生产管线。要不要接、怎么接，等评测数字出来后由下一道决定
（任务书 §五「不要碰」）。

## 两条铁律（同 `context_step.py`，抄一遍免得忘）

1. **字形层不可改写**：模型的回答必须落在候选集合内，不在就当没答，
   不引入候选外的字。
2. **门槛化**：本模块只出「模型选了什么、有没有解析成功」，门槛/是否
   采信由调用方（评测脚本／将来的策略类）决定，这里不定政策。

## key 从哪来

`GLM_API_KEY`（智谱）/ `DASHSCOPE_API_KEY`（千问）环境变量，**绝不写进
代码或档**。没有 key 时 `LLMContextJudge(provider)` 直接抛
`NoAPIKeyError`——调用方必须显式跳过并说明，不许静默退化成「就用
ngram」（那样上线后 key 失效谁也不知道，任务书 §二明确禁止）。

## 两版 prompt

- `prompt_direct`：只给上下文，不给候选，直接问「哪个字」——最贴近用户
  原句，但答案可能跑出候选外，需要 `parse_answer` 事后核对候选归属。
- `prompt_with_candidates`：把候选集合列出来，让模型只在里面选——预期
  准确率更高（管线上游已经把候选缩到几个字），且天然满足铁律 1。

两版都支持要不要模型给理由（`with_reason`），理由只进日志，不参与判分。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# ── 端点 ────────────────────────────────────────────────────────────
# 协调者 2026-09-10 已实测两家云端都通（GLM 400/千问 401，缺参数/缺 key
# 但连得上），两家都是 OpenAI 兼容格式。见任务书 §二。

ENDPOINTS: dict[str, dict] = {
    "glm": {
        "env": "GLM_API_KEY",
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-plus",   # 协调者 2026-09-10 实测同题正确；glm-4-flash 便宜但答错过，见方案文档
    },
    "qwen": {
        "env": "DASHSCOPE_API_KEY",
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-plus",
    },
}


class NoAPIKeyError(RuntimeError):
    """两处都没找到对应 key。调用方必须显式捕获并跳过、说明原因——

    不许捕获后悄悄改用 ngram 兜底：那样上线后 key 失效/欠费，
    产物看起来仍然正常，只是又不知不觉地退回了旧策略。
    """


# ── key 查找：环境变量 → overview 仓 .secret/api-keys.cfg ─────────────
# 用户 2026-09-10 把两个 key 放进了 overview/.secret/api-keys.cfg（私有仓，
# 已在 main）。**不写死绝对路径**——用本文件的实际位置反推工作区根，
# 兼容 D:\workspace、WSL、云端三种布局（子会话须知 §一）。

def _api_keys_cfg_path() -> Path:
    override = os.environ.get("GUJI_API_KEYS_CFG")
    if override:
        return Path(override)
    repo_root = Path(__file__).resolve().parents[2]     # open-guji-cv 仓根
    return repo_root.parent / "overview" / ".secret" / "api-keys.cfg"


def _parse_cfg(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def find_api_key(env_name: str) -> tuple[str | None, str]:
    """(key 或 None, 来源说明)。来源只给「哪里」，绝不带 key 本身。"""
    v = os.environ.get(env_name)
    if v:
        return v, "环境变量"
    cfg_path = _api_keys_cfg_path()
    cfg = _parse_cfg(cfg_path)
    if env_name in cfg:
        return cfg[env_name], str(cfg_path)
    return None, f"环境变量 与 {cfg_path} 都没有"


def redact_key(key: str) -> str:
    """打日志前脱敏：只印前 6 位 + 长度（任务书 §二明确要求）。"""
    if not key:
        return "(empty)"
    return f"{key[:6]}...(len={len(key)})"


# ── 回答解析 ────────────────────────────────────────────────────────

_CJK_CHARS = r"㐀-鿿豈-﫿"
_CJK_RE = re.compile(f"[{_CJK_CHARS}]")
_QUOTE_CHARS = '「」『』"\'“”‘’'
_QUOTED_CJK_RE = re.compile(
    f"[{re.escape(_QUOTE_CHARS)}]([{_CJK_CHARS}])[{re.escape(_QUOTE_CHARS)}]")


def parse_answer(text: str, candidates: list[str] | None = None
                 ) -> tuple[str | None, bool]:
    """模型原始输出 → (选中的字, 是否解析成功)。

    尝试顺序：JSON 里的 ``char`` 字段 → 整段就是单字 → 引号包着的单字
    （模型话痨但把答案标了出来，比如「这里应该是"根"字」）→
    （给了候选时）候选字里唯一命中的那个 → 退化为文本里第一个 CJK 字。

    **引号提取排在候选匹配、通用 CJK 兜底之前**：话痨句子的开头常是
    「根据上下文」「这个字应该是」这类固定搭配，本身就含 CJK 字，通用
    首字兜底会把这些噪声当成答案（实测踩过：mock 联调 boilerplate
    「根据上下文」的「根」字被当成了答案，凑巧当次金标也是「根」才
    侥幸判对，换个金标就会侥幸判错——对不对纯属运气，必须堵死）。
    候选歧义（文本里不止一个候选字，像是在复述选项而非作答）判解析
    失败，不瞎猜。
    """
    text = (text or "").strip()
    if not text:
        return None, False
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "char" in obj:
            c = str(obj["char"]).strip()
            if len(c) == 1:
                return c, True
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    if len(text) == 1:
        return text, True
    m = _QUOTED_CJK_RE.search(text)
    if m:
        return m.group(1), True
    if candidates:
        hits = [c for c in candidates if c in text]
        if len(hits) == 1:
            return hits[0], True
        return None, False
    m = _CJK_RE.search(text)
    if m:
        return m.group(0), True
    return None, False


# ── prompt ──────────────────────────────────────────────────────────

def prompt_direct(item: dict, book_title: str) -> str:
    """只给上下文，不给候选——最贴近用户原句。"""
    return (
        f"这是《{book_title}》里的一段古籍原文，竖排，从上到下阅读。\n"
        f"上文：{item['context_before']}\n"
        f"下文：{item['context_after']}\n"
        "中间有一个字看不清（用△表示），只根据上下文文意判断，"
        "这个字最可能是哪个字？只回答这一个汉字本身，不要解释、"
        "不要标点、不要输出其他任何内容。"
    )


def prompt_with_candidates(item: dict, book_title: str,
                           with_reason: bool = False) -> str:
    """给出候选集合，让模型只在里面选——预期更准，且天然满足字形层铁律。"""
    opts = "、".join(item["candidates_chars"])
    if with_reason:
        tail = ('请输出 JSON，形如 {"char": "字", "reason": "一句话理由"}，'
                '不要输出其他内容。')
    else:
        tail = '只输出 JSON，形如 {"char": "字"}，不要输出其他任何内容。'
    return (
        f"这是《{book_title}》里的一段古籍原文，竖排，从上到下阅读。因刻本"
        "模糊或识别不准，下面这个字位给出了几个可能的候选字形，需要你只凭"
        "上下文文意判断哪一个最合理（不是比较字形，字形已经不可靠）。\n"
        f"上文：{item['context_before']}\n"
        f"下文：{item['context_after']}\n"
        f"候选（只能从这些字里选一个，不能选候选之外的字）：{opts}\n"
        f"{tail}"
    )


# ── 调用层 ──────────────────────────────────────────────────────────

@dataclass
class LLMAnswer:
    item_id: str
    provider: str
    model: str
    raw_text: str
    parsed_char: str | None
    parse_ok: bool
    latency_s: float
    cached: bool = False
    error: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMContextJudge:
    """真调用层：读环境变量 key，POST 到 OpenAI 兼容端点，带缓存/超时/重试。

    没 key 直接在构造时抛 `NoAPIKeyError`（见类头），逼调用方显式处理。
    """

    def __init__(self, provider: str, *, model: str | None = None,
                 cache_path: str | Path | None = None,
                 timeout: float = 20.0, max_retries: int = 2,
                 rate_limit_s: float = 0.0):
        if provider not in ENDPOINTS:
            raise KeyError(f"未知 provider: {provider!r}（可用: {sorted(ENDPOINTS)}）")
        cfg = ENDPOINTS[provider]
        key, source = find_api_key(cfg["env"])
        if not key:
            raise NoAPIKeyError(
                f"没找到 {cfg['env']}（{source}），跳过 provider={provider}。"
                "调用方必须显式说明跳过原因，不许静默退回 ngram。")
        self.provider = provider
        self.model = model or cfg["model"]
        self.key_source = source            # 只记「哪里」，不记 key 本身
        self._url = cfg["url"]
        self._api_key = key
        self._timeout = timeout
        self._max_retries = max_retries
        self._rate_limit_s = rate_limit_s   # 每次真请求后的固定延迟，别把整批打爆
        self.cache_path = Path(cache_path) if cache_path else None
        self._cache: dict[str, dict] = {}
        if self.cache_path and self.cache_path.exists():
            self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))

    def _cache_key(self, prompt: str) -> str:
        return hashlib.sha256(
            f"{self.provider}|{self.model}|{prompt}".encode("utf-8")).hexdigest()

    def _save_cache(self) -> None:
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=1),
                encoding="utf-8")

    def ask(self, item_id: str, prompt: str) -> LLMAnswer:
        """同一道题（同 provider/model/prompt 文本）只问一次，缓存命中不发请求。"""
        ck = self._cache_key(prompt)
        if ck in self._cache:
            c = self._cache[ck]
            return LLMAnswer(item_id=item_id, provider=self.provider,
                             model=self.model, raw_text=c["raw_text"],
                             parsed_char=c["parsed_char"], parse_ok=c["parse_ok"],
                             latency_s=0.0, cached=True,
                             prompt_tokens=c.get("prompt_tokens", 0),
                             completion_tokens=c.get("completion_tokens", 0))
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 200,   # candidates 版要 JSON+理由时留够余量
        }).encode("utf-8")
        req = urllib.request.Request(
            self._url, data=body, method="POST",
            headers={"Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}"})
        last_err: Exception | None = None
        t0 = time.time()
        for attempt in range(self._max_retries + 1):
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                latency = time.time() - t0
                text = data["choices"][0]["message"]["content"].strip()
                usage = data.get("usage") or {}
                ptoks = int(usage.get("prompt_tokens") or 0)
                ctoks = int(usage.get("completion_tokens") or 0)
                parsed, ok = parse_answer(text)
                self._cache[ck] = {"raw_text": text, "parsed_char": parsed,
                                   "parse_ok": ok, "prompt_tokens": ptoks,
                                   "completion_tokens": ctoks}
                self._save_cache()
                if self._rate_limit_s:
                    time.sleep(self._rate_limit_s)
                return LLMAnswer(item_id=item_id, provider=self.provider,
                                 model=self.model, raw_text=text,
                                 parsed_char=parsed, parse_ok=ok,
                                 latency_s=latency, prompt_tokens=ptoks,
                                 completion_tokens=ctoks)
            except (urllib.error.URLError, urllib.error.HTTPError,
                   TimeoutError, ValueError, KeyError) as e:
                last_err = e
                if attempt < self._max_retries:
                    time.sleep(1.5 * (attempt + 1))
        return LLMAnswer(item_id=item_id, provider=self.provider,
                         model=self.model, raw_text="", parsed_char=None,
                         parse_ok=False, latency_s=time.time() - t0,
                         error=str(last_err))


class MockJudge:
    """离线联调用：不发请求，用一个固定函数模拟回答，跑通全链路的解析/打分。

    真调用请用 `LLMContextJudge`。这个类只用于没有 key 时验证
    prompt→调用→解析→打分 这条链路是通的（任务书完成判据 #2）。
    """

    provider = "mock"

    def __init__(self, responder: Callable[[str, str], str] | None = None,
                model: str = "mock-echo"):
        self.model = model
        self._responder = responder or (lambda item_id, prompt: "")
        self.calls: list[str] = []

    def ask(self, item_id: str, prompt: str) -> LLMAnswer:
        self.calls.append(item_id)
        text = self._responder(item_id, prompt)
        parsed, ok = parse_answer(text)
        return LLMAnswer(item_id=item_id, provider=self.provider,
                         model=self.model, raw_text=text, parsed_char=parsed,
                         parse_ok=ok, latency_s=0.0)


def available_providers() -> list[str]:
    """有环境变量 key 的 provider 名字列表（不发请求，只查 key 在不在）。"""
    return [name for name, cfg in ENDPOINTS.items() if os.environ.get(cfg["env"])]
