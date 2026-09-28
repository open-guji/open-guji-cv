# -*- coding: utf-8 -*-
"""前端「浏览器直接发」的请求必须带工作区（2026-09-28，C 道急修）。

`<img src>`、`EventSource` 发不出自定义请求头，工作区只能走查询串 `?ws=`
（`api/client.ts::withWorkspace`，服务端 `console/middleware.py` 的 QUERY 后路）。
漏了就按默认工作区找图——多工作区服务器上全部 404（全唐文按字种批审实测：
`GroupReviewPanel`/`ShapeReviewPanel` 的 `<img src={t.patch}>`，值守临时在 Caddy 上按
Referer 补 `?ws=` 救急，overview#109）。`api()` 走 fetch 自带头，不受此限。

这里扫前端源码，把几种已知的漏法拦下；包一层 `withWorkspace(...)`、走 `*Url()` 构造器
或 `BinaryToggleImage`（内部已包）都算合规。先拼 URL、下一行才包的，在拼的那行行尾写
`// ws-ok: <为什么>` 豁免。
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "open_guji_cv/console/frontend/src"

RULES = [
    # <img src={t.patch}> / src={c.patch}：卡片里的 patch 字段是不带 ws 的裸 URL
    (re.compile(r"<img\b[^>]*\bsrc=\{\s*[\w.?]+\.patch\s*\}"), "img 直接用 .patch（要 withWorkspace(x.patch) 或 BinaryToggleImage）"),
    # src={`/api/...`} / src="/api/..."
    (re.compile(r"\bsrc=\{\s*`/api/"), "src 直接写 `/api/…` 模板串"),
    (re.compile(r"\bsrc=\"/api/"), "src 直接写 \"/api/…\""),
    # EventSource 也带不了头
    (re.compile(r"new EventSource\(\s*[`'\"]/api/"), "EventSource 直接写 /api/…"),
]
# 拼图片地址（/api/cache/… /api/glyphlib/patch/… 等 .png）却没过 withWorkspace 的那一行
PNG_URL = re.compile(r"[`'\"]/api/[^`'\"]*\.png")


def _files():
    return [p for p in SRC.rglob("*") if p.suffix in (".ts", ".tsx")]


def test_src_dir_exists():
    assert SRC.is_dir() and _files(), SRC


def test_no_workspace_less_browser_urls():
    bad = []
    for p in _files():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            st = line.lstrip()
            if st.startswith(("*", "/*", "//")) or "ws-ok:" in line:   # 注释行；`// ws-ok: 理由` 明确豁免
                continue
            s = line.split("//", 1)[0]
            for rx, why in RULES:
                if rx.search(s):
                    bad.append(f"{p.relative_to(SRC)}:{i}: {why}\n    {line.strip()}")
            if PNG_URL.search(s) and "withWorkspace" not in s and "api<" not in s and "api(" not in s:
                bad.append(f"{p.relative_to(SRC)}:{i}: .png 图片地址没过 withWorkspace\n    {line.strip()}")
    assert not bad, "浏览器直发的请求漏了工作区（多工作区下 404）：\n" + "\n".join(bad)


def test_guard_catches_the_original_bug():
    """守卫本身要能拦住这次的原样写法（防止规则写宽了什么都不拦）。"""
    assert RULES[0][0].search('<img src={t.patch} alt={t.id} />')
    assert not RULES[0][0].search('<img src={withWorkspace(t.patch)} alt={t.id} />')
    assert RULES[3][0].search("new EventSource(`/api/runs/${id}/log`)")
    assert PNG_URL.search("? `/api/cache/${b}/char_patch/x.png`")
