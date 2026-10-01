# -*- coding: utf-8 -*-
"""Step8 复核报告：把某一类人裁结论逐处列出（带图、字对、前后各 10 字上下文），出 md + html（+ pdf）。

缺省出「我方对 · 其他」这一类（`who=ours, cat=other`，即 平台本对、且不属于 异体/通假/避讳 的分歧）：

    PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/report_collate_group.py vol03 \
        -w <书目录> --out <书目录>/reports/vol03/step8_ours_other [--pdf]

每处一条（**不聚类**，同字对也分开，因为上下文不同）：
1. 原图字符切片；
2. `A → B`：A 是校对本的字，B 是平台本（我方）的字；
3. 上下文：前 10 字 + 【B】 + 后 10 字，取自**平台本**当前文本（含人裁，阙文记 □，不含标点与版面记号）。

状态读法与控制台 Step8 页一致（`console/routers/step8._items`：最新对勘报告 + 本书复核事件）。
"""
from __future__ import annotations

import argparse
import html
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def text_stream(store, book: str, pages: list[int]) -> list[tuple[str, str]]:
    """全书按阅读顺序的 (字位 id, 字)；阙文记 □，blank/被排除的格不进。"""
    from open_guji_cv.report.slots import page_slots
    out: list[tuple[str, str]] = []
    for pg in pages:
        try:
            slots = page_slots(store, book, pg, [])
        except Exception:                                 # noqa: BLE001 —— 没产物的页跳过
            continue
        for s in slots:
            if not s.is_text:
                continue
            out.append((s.id, s.char or "□"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book")
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--out", required=True, help="输出目录（里面放 report.md / report.html / img/）")
    ap.add_argument("--who", default="ours", choices=("ours", "theirs", "neither"))
    ap.add_argument("--cat", default="other", help="who=ours 时的小类：variant/jiajie/taboo/other；空 = 不筛")
    ap.add_argument("--context", type=int, default=10, help="前后各取几个字")
    ap.add_argument("--pdf", action="store_true", help="用 Chrome/Edge 无头把 html 打成 pdf")
    a = ap.parse_args()
    os.environ["GUJI_WORKSPACE"] = str(Path(a.workspace).resolve())

    import cv2

    import open_guji_cv.steps  # noqa: F401
    from open_guji_cv.cli_v2 import _engine
    from open_guji_cv.console.routers import step8
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.pipeline import default_pipeline_id

    book = a.book
    doc = step8._load(book)
    if not doc:
        sys.exit(f"没有 {book} 的对勘报告（先 guji collate {book}）")
    items = [it for it in step8._items(book, doc)
             if it["who"] == a.who and (not a.cat or it["cat"] == a.cat)]
    items.sort(key=lambda it: (it.get("page") or 0, it.get("col") or 0, it.get("slot") or 0,
                               it.get("sub") or ""))

    eng = _engine(book, default_pipeline_id(load_book(book)), quiet=True)
    pages = sorted({int(p.stem[1:5]) for p in (eng.store.root / book / "seed_admit").glob("p*.json")}) \
        if hasattr(eng.store, "root") else list(range(1, 400))
    stream = text_stream(eng.store, book, pages)
    pos = {sid: i for i, (sid, _c) in enumerate(stream)}

    out = Path(a.out)
    img_dir = out / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, it in enumerate(items, 1):
        sid = it["id"]
        A, B = it["pair"][1], it["pair"][0]               # A = 校对本，B = 平台本
        i = pos.get(sid)
        if i is not None:
            before = "".join(c for _s, c in stream[max(0, i - a.context):i])
            after = "".join(c for _s, c in stream[i + 1:i + 1 + a.context])
            ctx = f"{before}【{B}】{after}"
        else:                                             # 文本流里找不到（页没产物）：退回报告里存的快照
            ctx = it.get("hyp_ctx") or f"【{B}】"
        img = ""
        try:
            _b, pg, col, slot = sid.split(":")
            sub = ""
            if slot and slot[-1] in "ab":
                slot, sub = slot[:-1], slot[-1]
            key = f"p{int(pg):04d}c{int(col):02d}s{int(slot)}{sub}"
            src = eng.ctx.materialize("char_patch", key)
            name = sid.replace(":", "_") + ".png"
            im = cv2.imdecode(__import__("numpy").fromfile(str(src), __import__("numpy").uint8), cv2.IMREAD_GRAYSCALE)
            if im is not None:
                cv2.imencode(".png", im)[1].tofile(str(img_dir / name))
                img = f"img/{name}"
        except Exception:                                 # noqa: BLE001 —— 图出不来不拖垮整份报告
            img = ""
        rows.append({"n": n, "id": sid, "page": it.get("page"), "col": it.get("col"),
                     "slot": it.get("slot"), "sub": it.get("sub") or "", "A": A, "B": B,
                     "ctx": ctx, "img": img, "basis": it.get("basis") or ""})

    label = {"ours": "我方对", "theirs": "校对本对", "neither": "都不对"}[a.who]
    cat_label = {"variant": "异体字", "jiajie": "通假字", "taboo": "避讳字", "other": "其他", "": ""}.get(a.cat, a.cat)
    title = f"{book} 对勘复核 · {label}" + (f" · {cat_label}" if cat_label else "")
    built = doc.get("_file", "")

    # ── markdown ──
    md = [f"# {title}", "",
          f"- 共 **{len(rows)}** 处（逐处列出，不聚类）；对勘报告：`{built}`",
          "- 每处：原图切片；`A → B`（A＝校对本的字，B＝平台本的字）；上下文＝前 "
          f"{a.context} 字 + 【B】 + 后 {a.context} 字（取自平台本当前文本，阙文记 □）", ""]
    for r in rows:
        loc = f"p{r['page']} 第{r['col']}列第{r['slot']}字{r['sub']}"
        md += [f"### {r['n']}. {loc}　{r['A']} → {r['B']}", ""]
        if r["img"]:
            md += [f'<img src="{r["img"]}" height="90">', ""]
        md += [f"{r['A']} → {r['B']}　（校对本 → 平台本）", "", f"{r['ctx']}", ""]
    (out / "report.md").write_text("\n".join(md), encoding="utf-8")

    # ── html（打 pdf 用；样式简单，宋体/黑体回退）──
    css = ("body{font-family:'Noto Serif CJK SC','Songti SC','SimSun','Microsoft YaHei',serif;margin:24px;color:#222}"
           "h1{font-size:22px;border-bottom:2px solid #333;padding-bottom:6px}"
           ".meta{color:#555;font-size:13px;line-height:1.7}"
           ".it{display:flex;gap:16px;align-items:center;border-bottom:1px solid #ddd;padding:8px 0;"
           "page-break-inside:avoid}"
           ".it img{height:84px;border:1px solid #bbb;background:#fff;flex:none}"
           ".noimg{width:64px;height:84px;background:#eee;flex:none}"
           ".n{width:34px;color:#888;font-size:13px;flex:none}"
           ".body{flex:1}.loc{color:#666;font-size:12px}"
           ".pair{font-size:22px;margin:2px 0}.pair b{color:#a33}"
           ".ctx{font-size:18px;letter-spacing:1px}.ctx b{color:#a33;background:#fff2cc}")
    h = [f"<!doctype html><html lang='zh'><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
         f"<style>{css}</style></head><body><h1>{html.escape(title)}</h1>",
         f"<div class='meta'>共 <b>{len(rows)}</b> 处（逐处列出，不聚类）· 对勘报告 {html.escape(built)}<br>"
         f"每处：原图切片；A → B（A＝校对本的字，B＝平台本的字）；上下文＝前 {a.context} 字 + 【B】 + 后 {a.context} 字"
         "（平台本当前文本，阙文记 □）</div>"]
    for r in rows:
        ctx = html.escape(r["ctx"]).replace("【", "<b>【").replace("】", "】</b>")
        imgtag = f"<img src='{r['img']}'>" if r["img"] else "<div class='noimg'></div>"
        h.append(f"<div class='it'><div class='n'>{r['n']}</div>{imgtag}<div class='body'>"
                 f"<div class='loc'>p{r['page']} 第{r['col']}列第{r['slot']}字{r['sub']} · {r['id']}</div>"
                 f"<div class='pair'>{html.escape(r['A'])} → <b>{html.escape(r['B'])}</b>"
                 f"<span class='loc'>　校对本 → 平台本</span></div>"
                 f"<div class='ctx'>{ctx}</div></div></div>")
    h.append("</body></html>")
    (out / "report.html").write_text("\n".join(h), encoding="utf-8")

    print(f"{title}：{len(rows)} 处 → {out / 'report.md'}")
    if a.pdf:
        chrome = next((c for c in CHROME_CANDIDATES if Path(c).exists()), None) or shutil.which("chrome")
        if not chrome:
            sys.exit("没找到 Chrome/Edge，无法出 pdf")
        pdf = out / "report.pdf"
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", (out / "report.html").resolve().as_uri()],
                       check=True, capture_output=True, timeout=180)
        print(f"pdf → {pdf}（{pdf.stat().st_size // 1024} KB）")


if __name__ == "__main__":
    main()
