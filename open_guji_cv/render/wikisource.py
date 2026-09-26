# -*- coding: utf-8 -*-
"""Step9 结果整理 · 维基文库导出：9.1 逐列 guji-markdown → zh.wikisource `Page:` 页 wikitext。

**只吃 9.1 的 md 文本**（`render/guji_markdown.py` 的输出，`#第N页` 分页、一列一行；
导出时带 `keep_empty_cols`，版心与空列也各占一个空行），不回查产物——md 是可以
手改的中间稿，改完一键转，改动不会被产物覆盖。命令行入口 `scripts/export_wikisource.py`。

## 版式：一列一行，照刻本（用户 2026-09-24 定）

不分段、不加空行、不认卷题（维基文库已有的 `Page:…/3` 并不标准，不照它）。
**唯一的空行是版心**（筒子页第 10 列）与本来就空的列——md 里是空行，这里照出。
页末的空列不出。

整页包在 `<poem>…</poem>` 里：MediaWiki 把单换行并成空格、空行当分段，
`<poem>`（zh.wikisource 已装的 Poem 扩展）把每个换行转成 `<br />`，空行就是
真正的空行，行首空格、模板照常（2026-09-24 用 API parse 实测）。
md 里手写的全角空格 `　` 原样保留（排版用，如撰者行字间距）。

| 版面 | 9.1 md | wikitext |
|---|---|---|
| 一列 | 一行 | 一行 |
| 版心 / 空列 | 空行 | 空行 |
| 挪抬（行首空格） | `.` | 全角空格 `　`，一个 `.` 一个 |
| 抬头 | `^` | 不表示 |
| 雙行夹注（按语、注文） | `<a|b>` / 只剩一半的 `<a>` | `{{*|ab}}`（zh.wikisource 通用注文模板） |
| 單行小字（本书多是人名） | `:jz[覿]{type=单行}` | `{{small|覿}}` |
| 阙文 | `[[]]` / `□` | `□` |
| 原刻残、人给了最像的字 | `□{guess=X}` | `X`（照录；用户：「这些地方应该有字」） |
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PAGE = re.compile(r"^#第(\d+)页\s*$")
_PREFIX = re.compile(r"^(\^*)(\.*)")
# 一个记号单位：雙行夹注 / 指令式夹注 / 阙文 / 原刻残（可带 guess）/ 单字
_TOKEN = re.compile(r"<(?P<jz>[^<>]*)>"
                    r"|:jz\[(?P<dj>[^\]]*)\](?:\{(?P<attrs>[^}]*)\})?"
                    r"|(?P<gap>\[\[[^\]]*\]\])"
                    r"|(?P<box>□(?:\{(?:[^}]*?\bguess=(?P<guess>[^,}\s]+))?[^}]*\})?)"
                    r"|(?P<ch>.)", re.S)


@dataclass
class PageOut:
    page: int
    wikitext: str


def _box(m: re.Match) -> str:
    return m.group("guess") or "□"


def _chars(s: str) -> str:
    """夹注内部：`[[]]` 出 □，`□{guess=X}` 出 X。"""
    return "".join(_box(m) if (m.group("gap") or m.group("box")) else m.group(0)
                   for m in _TOKEN.finditer(s) if not m.group(0).isspace())


def convert_line(src: str) -> str:
    m = _PREFIX.match(src)
    out: list[str] = ["　" * len(m.group(2))]
    for t in _TOKEN.finditer(src, m.end()):
        if t.group("jz") is not None:
            a, _, b = t.group("jz").partition("|")
            out.append("{{*|" + _chars(a) + _chars(b) + "}}")
        elif t.group("dj") is not None:
            tpl = "small" if "type=单行" in (t.group("attrs") or "") else "*"
            out.append("{{" + tpl + "|" + _chars(t.group("dj")) + "}}")
        elif t.group("gap") or t.group("box"):
            out.append(_box(t))
        elif t.group("ch") == "　" or not t.group("ch").isspace():
            out.append(t.group("ch"))
    return "".join(out)


def split_pages(md: str) -> dict[int, list[str]]:
    """`#第N页` 分页；页内空行**保留**（版心/空列），只去页末多余的。"""
    pages: dict[int, list[str]] = {}
    cur: list[str] | None = None
    for raw in md.splitlines():
        m = _PAGE.match(raw)
        if m:
            cur = pages.setdefault(int(m.group(1)), [])
        elif cur is not None:
            cur.append(raw.rstrip())
    for ls in pages.values():
        while ls and not ls[-1]:
            ls.pop()
    return pages


def convert(md: str) -> list[PageOut]:
    return [PageOut(p, "<poem>\n" + "\n".join(convert_line(s) for s in ls) + "\n</poem>")
            for p, ls in sorted(split_pages(md).items())]
