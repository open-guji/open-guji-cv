# -*- coding: utf-8 -*-
"""Step9 结果整理 · 9.2' 标点：给 `reflow_text` 切好的自然段加现代标点。

古文断句没有可靠的纯规则解法，所以这一步交给 LLM（千问/智谱，key 与
`clustering/llm_context.py` 共用：环境变量 → overview/.secret/api-keys.cfg）。
脚本这一层负责三件事：**喂得对、收得稳、验得住**。

## 喂：把 9.1 记号变成 LLM 看得懂的纯文本

- 夹注 `<ab>`、单行小注 `:jz[x]{type=单行}` 都以 `<…>` 给模型（小注里面也要标点）；
- 阙文 `[[]]`、`□{guess=X}` 给 `□`；
- 页码标记不给（由脚本按字位置还原）。

## 收：标点只许"插入"，绝不改字

模型返回的是带标点的文本。脚本把它与送出去的文本逐字对齐，**只取标点**，插回
原文的 token 序列（原文字符一个不动，所以 𠮓、㫖 这类异体字、`[[]]`、页码标记
都原样保留）。模型若偷偷改了字（"纠错"），那几个字对不上、被忽略，标点仍按位置
落在邻近字上；改字比例超阈值（默认 2%）则整块作废重问一次，仍不行就该块**不标点**
并写进报告——宁可缺标点，不要错标点。

## 验：见 `scripts/reflow_md.py` 的 --ref（对照整理本/维基文本逐字比、比标点位置）
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

PUNCT = set("，。、；：？！「」『』《》（）…—·,.;:?!\"'“”‘’")
_OPENERS = set("「『《（“‘")

_TOK = re.compile(
    r"(?P<mark>\x00p\d+\x00)"
    r"|<(?P<jz>[^<>]*)>"
    r"|:jz\[(?P<dj>[^\]]*)\](?P<djattr>\{[^}]*\})?"
    r"|(?P<gap>\[\[[^\]]*\]\])"
    r"|(?P<box>□(?:\{[^}]*\})?)"
    r"|(?P<ch>.)", re.S)


def tokenize(text: str, _inner: bool = False) -> list[tuple[str, str]]:
    """段落文本 → [(原文片段, 给 LLM 的字)]。页码标记的"给 LLM 的字"是空串。"""
    out: list[tuple[str, str]] = []
    for m in _TOK.finditer(text):
        if m.group("mark") is not None:
            out.append((m.group(0), ""))
        elif m.group("jz") is not None and not _inner:
            out.append(("<", "<"))
            out += tokenize(m.group("jz"), True)
            out.append((">", ">"))
        elif m.group("dj") is not None and not _inner:
            out.append((":jz[", "<"))
            out += tokenize(m.group("dj"), True)
            out.append(("]" + (m.group("djattr") or ""), ">"))
        elif m.group("gap") is not None or m.group("box") is not None:
            out.append((m.group(0), "□"))
        else:
            out.append((m.group(0), m.group(0)))
    return out


# ── LLM 客户端 ──────────────────────────────────────────────────────────

ENDPOINTS = {
    "qwen": ("DASHSCOPE_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-plus"),
    "glm": ("GLM_API_KEY", "https://open.bigmodel.cn/api/paas/v4/chat/completions", "glm-4-plus"),
}

SYSTEM = ("你是古籍整理专家，负责给没有标点的古籍原文加标点。"
          "只加标点，不增、不删、不改、不调换任何一个字（异体字、生僻字、□ 都原样保留）。")

PROMPT = """请给下面这段{genre}加现代标点。

要求：
1. 用 ，。、；：？！ 以及引文用「」、『』，书名篇名用《》；不要用省略号、破折号、括号。
2. 文中的 < 和 > 是双行小注的起止记号，必须原样保留在原位；小注里面的文字也要按需加标点。
3. □ 表示缺字，原样保留，不要猜补。
4. 一个字都不能改，不要纠错、不要换成简体、不要补字。
5. 只输出加好标点的那段文字，不要任何解释，不要换行。

{hint}原文：
{text}"""


def _find_key(env_name: str) -> str | None:
    from ..clustering.llm_context import find_api_key
    key, _ = find_api_key(env_name)
    return key


@dataclass
class PunctClient:
    provider: str = "qwen"
    model: str | None = None
    cache_dir: Path | None = None
    timeout: int = 30
    retries: int = 3

    def __post_init__(self) -> None:
        env, self.url, default_model = ENDPOINTS[self.provider]
        self.model = self.model or default_model
        key = _find_key(env)
        if not key:
            raise RuntimeError(f"没找到 {env}（环境变量或 overview/.secret/api-keys.cfg）")
        self._key = key
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def ask(self, user: str) -> str:
        ck = hashlib.sha256(f"{self.model}\n{SYSTEM}\n{user}".encode()).hexdigest()[:32]
        cf = self.cache_dir / f"{ck}.json" if self.cache_dir else None
        if cf and cf.exists():
            return json.loads(cf.read_text(encoding="utf-8"))["out"]
        body = json.dumps({"model": self.model, "temperature": 0,
                           "messages": [{"role": "system", "content": SYSTEM},
                                        {"role": "user", "content": user}]}).encode()
        last: Exception | None = None
        for i in range(self.retries):
            req = urllib.request.Request(self.url, data=body, headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {self._key}"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    out = json.loads(r.read())["choices"][0]["message"]["content"]
                if cf:
                    cf.write_text(json.dumps({"model": self.model, "out": out}, ensure_ascii=False), encoding="utf-8")
                return out
            except Exception as e:
                last = e
                time.sleep(1 * (i + 1))
        raise RuntimeError(f"LLM 调用失败：{last}")


# ── 对齐：只取标点，插回原文 ────────────────────────────────────────────

def clean_output(o: str) -> str:
    o = re.sub(r"^```[a-z]*\n?|\n?```$", "", o.strip())
    return re.sub(r"\s+", "", o)


def align_punct(plain: str, out: str) -> tuple[dict[int, str], int]:
    """`{plain 下标: 插在该字之前的标点}`（下标 == len(plain) 表示末尾）与"对不上的字数"。"""
    stripped: list[str] = []
    punct_before: dict[int, str] = {}        # stripped 下标 → 标点
    for c in out:
        if c in PUNCT and c not in "<>":
            punct_before[len(stripped)] = punct_before.get(len(stripped), "") + c
        else:
            stripped.append(c)
    s = "".join(stripped)
    if s == plain:
        return punct_before, 0
    sm = difflib.SequenceMatcher(None, plain, s, autojunk=False)
    qmap: dict[int, int] = {}
    bad = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                qmap[j1 + k] = i1 + k
        else:
            bad += max(i2 - i1, j2 - j1)
    res: dict[int, str] = {}
    keys = sorted(qmap)
    for q, p in punct_before.items():
        nxt = next((k for k in keys if k >= q), None)
        t = qmap[nxt] if nxt is not None else len(plain)
        res[t] = res.get(t, "") + p
    return res, bad


def inject(tokens: list[tuple[str, str]], ins: dict[int, str]) -> str:
    """把 `ins`（plain 下标 → 标点）插进 token 序列。页码标记夹在中间时，
    收尾标点放标记前、起首引号/书名号放标记后。"""
    out: list[str] = []
    pi = 0                                    # 已走过的 plain 字数
    pending_marks: list[str] = []
    def emit_punct(p: str) -> None:
        closers = "".join(c for c in p if c not in _OPENERS)
        openers = "".join(c for c in p if c in _OPENERS)
        out.append(closers)
        out.extend(pending_marks)
        pending_marks.clear()
        out.append(openers)
    for orig, plain in tokens:
        if plain == "":
            pending_marks.append(orig)
            continue
        if pi in ins:
            emit_punct(ins[pi])
        out.extend(pending_marks)
        pending_marks.clear()
        out.append(orig)
        pi += 1
    if pi in ins:
        emit_punct(ins[pi])
    out.extend(pending_marks)
    return "".join(out)


# ── 段落 → 标点段落 ─────────────────────────────────────────────────────

@dataclass
class PunctResult:
    text: str
    ok: bool = True
    changed_chars: int = 0
    notes: list[str] = field(default_factory=list)


def _chunks(tokens: list[tuple[str, str]], limit: int) -> list[tuple[int, int]]:
    """token 区间 [(a, b)]，每块 plain 字数 ≲ limit，只在小注外面切。"""
    spans, a, n, depth = [], 0, 0, 0
    for i, (_, p) in enumerate(tokens):
        if p == "<":
            depth += 1
        elif p == ">":
            depth = max(0, depth - 1)
        if p:
            n += 1
        if n >= limit and depth == 0 and p != "<":
            spans.append((a, i + 1))
            a, n = i + 1, 0
    if a < len(tokens):
        spans.append((a, len(tokens)))
    return spans


def punctuate(text: str, client: PunctClient, genre: str = "古籍文字", hint: str = "",
              limit: int = 300, max_bad_ratio: float = 0.02) -> PunctResult:
    tokens = tokenize(text)
    res = PunctResult("")
    pieces: list[str] = []
    for a, b in _chunks(tokens, limit):
        sub = tokens[a:b]
        plain = "".join(p for _, p in sub)
        if not plain:
            pieces.append("".join(o for o, _ in sub))
            continue
        user = PROMPT.format(genre=genre, hint=(f"背景：{hint}\n\n" if hint else ""), text=plain)
        best: tuple[dict[int, str], int] | None = None
        for attempt in range(2):
            out = clean_output(client.ask(user if attempt == 0 else user + "\n（上次改动了原文的字，这次请逐字照抄，只加标点。）"))
            ins, bad = align_punct(plain, out)
            if best is None or bad < best[1]:
                best = (ins, bad)
            if bad <= max_bad_ratio * len(plain):
                break
        ins, bad = best  # type: ignore[misc]
        res.changed_chars += bad
        if bad > max_bad_ratio * len(plain):
            res.ok = False
            res.notes.append(f"LLM 改字 {bad}/{len(plain)}，本块不标点：「{plain[:10]}…」")
            pieces.append("".join(o for o, _ in sub))
        else:
            pieces.append(inject(sub, ins))
    res.text = "".join(pieces)
    return res


def punctuate_all(texts: list[str], client: PunctClient, workers: int = 4, **kw) -> list[PunctResult]:
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda t: punctuate(t, client, **kw), texts))
