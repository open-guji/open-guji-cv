"""`guji close-check <册>`：一册书交付前的逐项体检（overview#413 C2；标准见 doc/runbook/整理一册书.md 第五节）。

只读：不改产物、不清缓存、不写事件。每项给出 pass / fail / manual / skip 与依据数字，
全部 pass（manual 由人另行确认）才算机器这一侧过关。

能机器判的项：
  1 产物新鲜（status）＋ 缓存不错位（cache verify，只读）
  2 待审清零（待审卡片按类计数）
  2b 收尾闸 closure_gaps = 0（有定字裁决却没出字）
  8 字形库真源已提交（工作区 git 里 feedback/、output/glyph_store/ 没有未提交改动）
  10/11 lines.md 与 pages.json 自洽（给了 --export-dir 才查）
  12 Step9 产物在（reports/<册>/<册>.md 与对勘 html）
  7/13 避諱表、收尾记录在（给了 --notes 才查）
其余（3 4 5 6 9 14）只列为 manual，由人或会话按 runbook 逐项确认。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

PASS, FAIL, MANUAL, SKIP, ERROR = "pass", "fail", "manual", "skip", "error"


def _item(no: str, name: str, status: str, detail: str = "", data=None) -> dict:
    return {"no": no, "name": name, "status": status, "detail": detail, "data": data}


def _fresh(eng, pages) -> dict:
    st = eng.status(pages=pages)
    bad = {sid: {k: d["counts"][k] for k in ("stale", "missing", "failed", "blocked") if d["counts"][k]}
           for sid, d in st["steps"].items()}
    bad = {k: v for k, v in bad.items() if v}
    return _item("1a", "产物新鲜", PASS if not bad else FAIL,
                 "全部新鲜" if not bad else f"{len(bad)} 步有过期/缺失/失败", bad or None)


def _cache(eng, pages) -> dict:
    from .cache_verify import verify_book
    res = verify_book(eng, pages, fix=False, log=lambda *_: None)
    n = res.get("bad_columns", 0)
    return _item("1b", "缓存不错位", PASS if not n else FAIL,
                 f"错位 {n} 列" + ("（`guji cache verify --fix`）" if n else ""), res.get("bad_pages") or None)


def _queue(book: str, store) -> dict:
    from ..review.cards import cards
    res = cards(book, "all", limit=1, only="review", store=store, gate_cut=False,
                skip_decided=True, cls="*")
    cc = res.get("class_counts") or {}
    n = sum(cc.values())
    return _item("2", "待审清零", PASS if not n else FAIL, f"待审 {n} 格", cc or None)


def _closure(book: str, pages, store) -> dict:
    from ..review.verdict_view import closure_gaps, closure_mismatches
    gaps = closure_gaps(book, pages, store)
    mism = closure_mismatches(book, pages, store)
    return _item("2b", "收尾闸", PASS if not gaps else FAIL,
                 f"已定字却没出字 {len(gaps)} 格；人裁字≠放行字 {len(mism)} 格（报告项，需人扫一眼）",
                 {"gaps": [g["id"] for g in gaps], "mismatches": [m["id"] for m in mism]})


def _store_committed(ws: Path) -> dict:
    rel = ["feedback", "output/glyph_store", "config", "review"]
    try:
        out = subprocess.run(["git", "-C", str(ws), "status", "--porcelain", "--", *rel],
                             capture_output=True, text=True, timeout=120).stdout
    except Exception as e:  # noqa: BLE001
        return _item("8", "字形库与人裁已提交", ERROR, f"{type(e).__name__}: {e}")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return _item("8", "字形库与人裁已提交", PASS if not lines else FAIL,
                 "工作区 git 干净" if not lines else
                 f"{len(lines)} 个未提交改动（先 `guji-cv glyph-db export`，查 numstat 无成片删除后提交）",
                 lines[:50] or None)


def _export(export_dir: Path, chapter: str | None) -> list[dict]:
    from ..formats.guji_format import _plain_chars
    ld = sorted(export_dir.glob("*.lines.md"))
    if chapter:
        ld = [p for p in ld if p.name.startswith(chapter + ".")]
    if len(ld) != 1:
        return [_item("10", "lines.md", FAIL, f"{export_dir} 下找到 {len(ld)} 个 lines.md，应为 1 个")]
    lines = ld[0]
    stem = lines.name[: -len(".lines.md")]
    pj = export_dir / f"{stem}.pages.json"
    chars = _plain_chars(lines.read_text(encoding="utf-8"))
    items = [_item("10", "lines.md", PASS, f"{lines.name}：{len(chars)} 字元（导出器口径，含阙文占位）",
                   {"chars": len(chars), "lacuna": sum(1 for c in chars if c in ("〓", "□"))})]
    if not pj.exists():
        items.append(_item("11", "pages.json", FAIL, f"缺 {pj.name}"))
        return items
    pages = json.loads(pj.read_text(encoding="utf-8"))
    offs = {c["o"] for p in pages["pages"] for c in p["cells"] if isinstance(c.get("o"), int)}
    missing = [i for i in range(len(chars)) if i not in offs]
    extra = sorted(o for o in offs if o >= len(chars))
    ok = not missing and not extra
    items.append(_item("11", "pages.json 与 lines.md 逐字对上", PASS if ok else FAIL,
                       f"{len(pages['pages'])} 页；无框的字 {len(missing)}，多出的框 {len(extra)}"
                       "；抽检框位要另外目测（check_pages_json_boxes.py）",
                       {"missing": missing[:50], "extra": extra[:50]} if not ok else None))
    return items


def _step9(reports: Path, book: str) -> dict:
    rep = reports / book
    md = rep / f"{book}.md"
    html = sorted(rep.glob("collation_*.html"))
    ok = md.exists() and bool(html)
    return _item("12", "Step9 产物", PASS if ok else FAIL,
                 f"{'有' if md.exists() else '缺'} {md.name}；对勘 html {len(html)} 份")


def _notes(notes: Path) -> list[dict]:
    out = []
    av = sorted(notes.glob("避諱改字表*.md"))
    out.append(_item("7", "避諱改字表", PASS if av else FAIL, av[-1].name if av else f"{notes} 下没有"))
    rec = notes / "收尾记录.md"
    out.append(_item("13", "收尾记录", PASS if rec.exists() else FAIL, rec.name if rec.exists() else "缺"))
    return out


MANUAL_ITEMS = [
    ("3", "队列外改判清零：最新放行错穷举里每格都有人裁或写明原因"),
    ("4", "切分问题有着落：修好的已重算复审，没修好的标存疑并列出"),
    ("5", "己/已/巳 全族按文意定，不拿证人当真值"),
    ("6", "对勘存疑逐条有人裁或说明"),
    ("9", "人裁入测试集，dry-run updated = 0"),
    ("14", "改过页面的册已记进 Commons 修图记录"),
]


def run(eng, ws: Path, pages, export_dir: Path | None = None, chapter: str | None = None,
        notes: Path | None = None, reports: Path | None = None) -> dict:
    book = eng.book.id
    items: list[dict] = []
    checks = [
        ("1a", "产物新鲜", lambda: [_fresh(eng, pages)]),
        ("1b", "缓存不错位", lambda: [_cache(eng, pages)]),
        ("2", "待审清零", lambda: [_queue(book, eng.store)]),
        ("2b", "收尾闸", lambda: [_closure(book, pages, eng.store)]),
        ("8", "字形库与人裁已提交", lambda: [_store_committed(ws)]),
        ("10", "lines.md／pages.json", lambda: _export(export_dir, chapter) if export_dir else
         [_item("10", "lines.md", SKIP, "没给 --export-dir"), _item("11", "pages.json", SKIP, "没给 --export-dir")]),
        ("12", "Step9 产物", lambda: [_step9(reports or ws / "reports", book)]),
        ("7", "避諱表／收尾记录", lambda: _notes(notes) if notes else
         [_item("7", "避諱改字表", SKIP, "没给 --notes"), _item("13", "收尾记录", SKIP, "没给 --notes")]),
    ]
    for no, name, fn in checks:
        try:
            items.extend(fn())
        except Exception as e:  # noqa: BLE001 —— 一项算不出来不拖垮整张体检表
            items.append(_item(no, name, ERROR, f"{type(e).__name__}: {e}"))
    items.extend(_item(no, txt, MANUAL) for no, txt in MANUAL_ITEMS)
    order = {s: i for i, s in enumerate(["1a", "1b", "2", "2b", "3", "4", "5", "6", "7", "8", "9",
                                         "10", "11", "12", "13", "14"])}
    items.sort(key=lambda it: order.get(it["no"], 99))
    machine = [it for it in items if it["status"] not in (MANUAL, SKIP)]
    return {"book": book, "workspace": str(ws), "pages": len(pages),
            "machine_ok": all(it["status"] == PASS for it in machine),
            "counts": {s: sum(1 for it in items if it["status"] == s) for s in (PASS, FAIL, ERROR, MANUAL, SKIP)},
            "items": items}


ICON = {PASS: "✓", FAIL: "✗", ERROR: "!", MANUAL: "·", SKIP: "-"}


def print_report(res: dict) -> None:
    print(f"{res['book']} 交付体检 · {res['pages']} 页 · {res['workspace']}")
    for it in res["items"]:
        print(f"  {ICON[it['status']]} {it['no']:>3} {it['name']}" + (f"：{it['detail']}" if it["detail"] else ""))
    c = res["counts"]
    verdict = "机器项全部通过" if res["machine_ok"] else "机器项未通过"
    print(f"  —— {verdict}（通过 {c['pass']}，未过 {c['fail']}，出错 {c['error']}；"
          f"待人确认 {c['manual']}，未查 {c['skip']}）")
