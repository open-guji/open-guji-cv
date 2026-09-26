# -*- coding: utf-8 -*-
"""把 `export_wikisource.py` 出的逐页 wikitext 上传到 zh.wikisource `Page:` 页。

    python scripts/upload_wikisource.py bxgb --pages 3,4 --level 3 [--dir DIR] [--dry-run]

登录用机器人密码（Special:BotPasswords），读 `~/.wikisource-bot`（两行 `WS_USER=` / `WS_PASS=`，
权限 600，不进任何仓）。页名映射复用 `export_wikisource.BOOKS`。已存在的页直接覆盖（历史里留旧版）。
页眉页脚留空；`--level` 是 ProofreadPage 校对等级（1 未校对 / 3 已校对 / 4 已核对），默认 3（用户 2026-09-26 定：一律标已校对）。
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from export_wikisource import BOOKS  # noqa: E402

API = "https://zh.wikisource.org/w/api.php"
UA = "guji-upload/0.1 (open-guji; sheldonli.dev@gmail.com)"
SUMMARY = "開源古籍：刻本圖像逐字識別 + 人工審定（open-guji-cv）"


class Wiki:
    def __init__(self) -> None:
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, post: bool = False, **params) -> dict:
        params["format"] = "json"
        data = urllib.parse.urlencode(params).encode()
        req = (urllib.request.Request(API, data=data) if post
               else urllib.request.Request(API + "?" + data.decode()))
        req.add_header("User-Agent", UA)
        return json.load(self.op.open(req, timeout=60))

    def login(self, user: str, pw: str) -> str:
        tok = self.call(action="query", meta="tokens", type="login")["query"]["tokens"]["logintoken"]
        r = self.call(post=True, action="login", lgname=user, lgpassword=pw, lgtoken=tok)["login"]
        if r.get("result") != "Success":
            raise SystemExit(f"登录失败：{r}")
        return r["lgusername"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book", choices=sorted(BOOKS))
    ap.add_argument("--pages", required=True, help="扫描页号，如 3,4 或 3-56")
    ap.add_argument("--level", type=int, default=3, choices=(1, 2, 3, 4))  # 用户 2026-09-26 定：维基文库一律标已校对
    ap.add_argument("--dir", default=None, help="pNNN.wiki 所在目录；缺省工作区 reports/<book>/wikisource")
    ap.add_argument("--workspace", "-w", default=None)
    ap.add_argument("--sleep", type=float, default=5.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    pages: list[int] = []
    for part in a.pages.split(","):
        lo, _, hi = part.partition("-")
        pages += range(int(lo), int(hi or lo) + 1)
    if a.dir:
        d = Path(a.dir)
    else:
        if not a.workspace:
            ap.error("要 --dir 或 -w 工作区")
        d = Path(a.workspace) / "reports" / a.book / "wikisource"

    cfg = dict(l.strip().split("=", 1) for l in
               (Path.home() / ".wikisource-bot").read_text(encoding="utf-8").splitlines() if "=" in l)
    w = Wiki()
    user = w.login(cfg["WS_USER"], cfg["WS_PASS"])
    csrf = w.call(action="query", meta="tokens")["query"]["tokens"]["csrftoken"]

    for i, p in enumerate(pages):
        title = BOOKS[a.book]["wiki_page"](p)
        body = (d / f"p{p:03d}.wiki").read_text(encoding="utf-8").rstrip("\n")
        text = (f'<noinclude><pagequality level="{a.level}" user="{user}" /></noinclude>'
                f"{body}<noinclude></noinclude>")
        if a.dry_run:
            print(f"[dry] {title}（{len(body)} 字符）")
            continue
        r = w.call(post=True, action="edit", title=title, text=text, summary=SUMMARY,
                   contentformat="text/x-wiki", token=csrf)
        e = r.get("edit", {})
        print(f"{title}: {e.get('result')} {'新建' if 'new' in e else ''} rev={e.get('newrevid')}"
              if e else f"{title}: 失败 {r.get('error')}")
        if i + 1 < len(pages):
            time.sleep(a.sleep)


if __name__ == "__main__":
    main()
