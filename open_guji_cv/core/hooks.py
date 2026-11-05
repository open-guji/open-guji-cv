"""`guji` 命令行在几个固定时点调的钩子，由 guji-manager 登记实现（拆分 P4，2026-11-04）。

pipeline 不 import manager。原先夹在 `cli_v2` 里的 manager 行为（开跑前取钉版的库、模型、语料，
整册跑完自动存包，status 里的收尾闸报告等）改成：pipeline 在下面几个点调钩子，manager 经入口点组
`guji.hooks` 登记（入口点指向一个 `register(hooks)` 函数，`hooks` 就是本模块）。

时点：

- `startup(command)`：解析完参数、执行命令前（如注册去 R2 取派生缓存的取件器、耗时记录）。
- `prepare(book, steps, jobs)`：`guji pipeline` 起跑前、建引擎之后（钉版字形库、模型、语料、生僻字索引就位）。
- `finished(args, eng, steps, ok)`：`guji pipeline` 跑完；`ok` = 没有失败页（自动存包、提醒没存包的产物）。
- `status(book, pages, store)`：`guji status` 追加报告项，返回 `[(键, 值, 印法)]`，
  值写进 `--json` 的结果，`印法(值)` 在人读输出的末尾印。

没装 manager 时这些点什么也不做，只有一处例外：册钉了字形库、模型或语料而没人登记 `prepare`，
`guji pipeline` 拒跑（退出码 2），免得用本机现有的文件跑出和钉版不一样的产物；加 `--no-prep` 放行。
本模块不在任何 Step 的 `code_deps` 里。
"""
from __future__ import annotations

import sys
from typing import Callable

GROUP = "guji.hooks"
POINTS = ("startup", "prepare", "finished", "status")
_HOOKS: dict[str, list[Callable]] = {p: [] for p in POINTS}
_LOADED = False


def add(point: str, fn: Callable) -> None:
    """登记一个钩子；同一个函数登记两次只算一次。"""
    if point not in _HOOKS:
        raise ValueError(f"没有这个时点：{point}（可选 {', '.join(POINTS)}）")
    if fn not in _HOOKS[point]:
        _HOOKS[point].append(fn)


def has(point: str) -> bool:
    load()
    return bool(_HOOKS[point])


def call(point: str, *args, **kw) -> list:
    """按登记顺序调这个时点的全部钩子，返回各自的返回值。钩子自己的异常照常抛出。"""
    load()
    return [fn(*args, **kw) for fn in _HOOKS[point]]


def load() -> None:
    """读入口点组 `guji.hooks`（只读一次）。插件加载失败只提示，不影响 `guji` 本身。"""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    from importlib.metadata import entry_points
    try:
        eps = entry_points(group=GROUP)
    except Exception:  # noqa: BLE001
        return
    for ep in eps:
        try:
            ep.load()(sys.modules[__name__])
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ 钩子插件 {ep.name} 加载失败（{type(e).__name__}: {e}），略过", file=sys.stderr)


def reset() -> None:
    """测试用：清空登记，下次 `load()` 重新读入口点。"""
    global _LOADED
    for v in _HOOKS.values():
        v.clear()
    _LOADED = False


def pinned_inputs(book) -> list[str]:
    """册钉了哪些要 manager 先备好的输入（字形库快照、模型总号、语料）。"""
    out = []
    if getattr(book, "glyph_pin", None):
        out.append(f"字形库 g{book.glyph_pin}")
    if getattr(book, "model", None):
        out.append(f"模型 m{book.model}")
    if getattr(book, "corpus", None) and not getattr(book, "corpus_dev", False):
        out.append(f"语料 {book.corpus}")
    return out
