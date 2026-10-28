# -*- coding: utf-8 -*-
"""控制台调 cv 命令行：会改东西、或耗时的动作一律走子进程（设计第五节）。

`doc/design/拆分-控制台独立成包与上网站.md`：控制台只「看、裁、下单」。消费事件、导金标、
迁载体、跑评测这类写工作区（事件以外）或跑得久的动作，不在控制台进程里 import 那段代码，
而是起 `python -m open_guji_cv …`，读它打印的 JSON。跑管线早就是这么做的（`jobs.py`）。

工作区跟 `jobs.py` 同一个规矩：子进程的 `GUJI_WORKSPACE` 只从**本请求**的工作区来
（中间件设的 contextvar），不继承控制台进程的环境变量。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from fastapi import HTTPException

from open_guji_cv.console_api import workspace_root

#: 命令行里出 JSON 之外还会印人话（如「（试算，未写入…）」），stderr 尾巴最多回这么多字给前端
_ERR_TAIL = 2000


def guji_argv(*args: str) -> list[str]:
    """`guji` 命令的 argv（与 `jobs.py` 同一个解释器、同一个入口）。"""
    return [sys.executable, "-m", "open_guji_cv", *args]


def cli_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    env.pop("GUJI_WORKSPACE", None)
    ws = workspace_root()
    if ws is not None:
        env["GUJI_WORKSPACE"] = str(ws)
    return env


def parse_json_output(out: str) -> Any:
    """命令行的 stdout → JSON。先整段解析；不行就从后往前找一行能解析的（`eval run --json`
    先印逐条结果、最后一行才是 JSON）；再不行从第一个 `{`/`[` 起解析一个值（多行 JSON 后面跟人话）。"""
    text = out.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line[:1] in "{[":
            try:
                return json.loads(line)
            except ValueError:
                continue
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if starts:
        try:
            return json.JSONDecoder().raw_decode(text[min(starts):])[0]
        except ValueError:
            pass
    raise ValueError("命令行没有输出 JSON")


def run_guji(*args: str, timeout: float = 600) -> Any:
    """跑一条 `guji` 子命令、取它的 JSON 输出。失败（退出码非 0、超时、没 JSON）→ 500，带 stderr 尾巴。"""
    argv = guji_argv(*args)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=cli_env(), timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise HTTPException(504, f"命令超时（{timeout:.0f} 秒）：{' '.join(args)}") from e
    if proc.returncode != 0:
        raise HTTPException(500, f"命令失败（退出码 {proc.returncode}）：{' '.join(args)}\n"
                                 + (proc.stderr or proc.stdout)[-_ERR_TAIL:])
    try:
        return parse_json_output(proc.stdout)
    except ValueError as e:
        raise HTTPException(500, f"{e}：{' '.join(args)}\n" + proc.stdout[-_ERR_TAIL:]) from e
