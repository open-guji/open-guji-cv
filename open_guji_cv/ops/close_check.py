"""`guji close-check <册>`：一册书交付前的逐项体检（overview#413 C2；标准见 doc/runbook/整理一册书.md 第五节）。

只读：不改产物、不清缓存、不写事件。每项给出 pass / fail / manual / skip 与依据数字，
全部 pass（manual 由人另行确认）才算机器这一侧过关。

能机器判的项：
  1 产物新鲜（status；册配置登记了冻结基线 `freeze:` 时改比快照产物 sha，见 ops/freeze.py）＋ 缓存不错位（cache verify，只读）
  2 待审清零（待审卡片按类计数；`--tier rough` 粗校档只报数、不计，终校档 `final`（缺省）才计）
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


def _fresh_or_frozen(eng, pages, ws: Path) -> dict:
    """册配置登记了冻结基线（`freeze:`）就比快照，否则照旧比现行指纹（GUJI-601）。"""
    from .freeze import fresh_frozen, is_frozen
    if not is_frozen(eng.book):
        return _fresh(eng, pages)
    from ..core.workspace import feedback_root
    return fresh_frozen(eng, pages, ws, feedback_root=feedback_root())


def _cache(eng, pages) -> dict:
    from .cache_verify import verify_book
    res = verify_book(eng, pages, fix=False, log=lambda *_: None)
    n = res.get("bad_columns", 0)
    return _item("1b", "缓存不错位", PASS if not n else FAIL,
                 f"错位 {n} 列" + ("（`guji cache verify --fix`）" if n else ""), res.get("bad_pages") or None)


def _glyph_store_missing(ws: Path) -> str | None:
    """工作区没有字形库（glyph_store 目录与 glyph.db 都没有）→ 返回缺什么；齐了返回 None。"""
    from ..core.workspace import data_root
    out = Path(ws) / "output"
    gs = (data_root(Path(ws)) or Path(ws)) / "output" / "glyph_store"
    if (out / "glyph.db").is_file():
        return None
    # 空目录不算有库：要有字形账本或人裁事件文件才算
    if gs.is_dir() and ((gs / "glyphs.jsonl").is_file() or (gs / "feedback" / "events").is_dir()
                        or (gs / "events").is_dir()):
        return None
    return f"{out} 下没有 glyph.db，glyph_store 也缺或是空目录"


def _queue(book: str, store, ws: Path | None = None, tier: str = "final") -> dict:
    from ..review.cards import cards
    # 没有字形库的工作区上，待审卡片出不来，会报「待审 0 ✓」——假绿（GUJI-364 评论 12573，vol01 实有 290 格待审）。
    # 缺库就当体检出错，不当通过。
    miss = _glyph_store_missing(ws) if ws is not None else None
    if miss:
        raise RuntimeError(f"工作区缺字形库，待审数不可信：{miss}（须在带 store 的 H 道工作区跑）")
    res = cards(book, "all", limit=1, only="review", store=store, gate_cut=False,
                skip_decided=True, cls="*", doubt="*")
    cc = res.get("class_counts") or {}
    n = sum(cc.values())
    # 看图判错送回人审的格（overview#428）也在待审里，单列出来：清它要人在控制台裁，不是重跑
    nv = (res.get("doubt_counts") or {}).get("vision_flag", 0)
    detail = f"待审 {n} 格" + (f"（其中看图判错 {nv} 格，doubt=vision_flag）" if nv else "")
    if tier == "rough":     # 粗校档（整理设计 R5，Maren 10-17 定）：待审留给精校，只报数不计
        return _item("2", "待审清零", PASS, detail + "（粗校档不计，终校档才计）", cc or None)
    return _item("2", "待审清零", PASS if not n else FAIL, detail, cc or None)


def _closure(book: str, pages, store, ws: Path | None = None) -> dict:
    from ..review.verdict_view import closure_gaps, closure_mismatches
    miss = _glyph_store_missing(ws) if ws is not None else None
    if miss:
        raise RuntimeError(f"工作区缺字形库，收尾闸不可信：{miss}（须在带 store 的 H 道工作区跑）")
    gaps = closure_gaps(book, pages, store)
    mism = closure_mismatches(book, pages, store)
    return _item("2b", "收尾闸", PASS if not gaps else FAIL,
                 f"已定字却没出字 {len(gaps)} 格；人裁字≠放行字 {len(mism)} 格（报告项，需人扫一眼）",
                 {"gaps": [g["id"] for g in gaps], "mismatches": [m["id"] for m in mism]})


def _store_committed(ws: Path) -> dict:
    from ..core.workspace import central_marker
    if central_marker(Path(ws)):
        # 迁到中心库后（GUJI-608）：看数据目录有没有没推的改动（不连网，对上次拉／推的基准）
        try:
            from .central_glyph import glyph_hooks
            from ..datastore.workcopy import local_changes
            dirty = local_changes(Path(ws), glyph_hooks(Path(ws)))
        except BaseException as e:  # noqa: BLE001  （含 SystemExit：还没拉过）
            return _item("8", "字形库与人裁已推进中心库", ERROR, f"{type(e).__name__}: {e}")
        return _item("8", "字形库与人裁已推进中心库", PASS if not dirty else FAIL,
                     "数据目录与中心库一致" if not dirty else f"{len(dirty)} 个文件没推（`guji db push -w <工作区>`）",
                     dirty[:50] or None)
    rel = ["feedback", "output/glyph_store", "config", "review"]
    try:
        out = subprocess.run(["git", "-C", str(ws), "status", "--porcelain", "--", *rel],
                             capture_output=True, text=True, timeout=120).stdout
    except Exception as e:  # noqa: BLE001
        return _item("8", "字形库与人裁已提交", ERROR, f"{type(e).__name__}: {e}")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return _item("8", "字形库与人裁已提交", PASS if not lines else FAIL,
                 "工作区 git 干净" if not lines else
                 f"{len(lines)} 个未提交改动（`guji store commit -w <工作区> --push`）",
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
        notes: Path | None = None, reports: Path | None = None, tier: str = "final") -> dict:
    book = eng.book.id
    items: list[dict] = []
    checks = [
        ("1a", "产物新鲜", lambda: [_fresh_or_frozen(eng, pages, ws)]),
        ("1b", "缓存不错位", lambda: [_cache(eng, pages)]),
        ("2", "待审清零", lambda: [_queue(book, eng.store, ws, tier)]),
        ("2b", "收尾闸", lambda: [_closure(book, pages, eng.store, ws)]),
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
    return {"book": book, "workspace": str(ws), "pages": len(pages), "tier": tier,
            "machine_ok": all(it["status"] == PASS for it in machine),
            "counts": {s: sum(1 for it in items if it["status"] == s) for s in (PASS, FAIL, ERROR, MANUAL, SKIP)},
            "items": items}


ICON = {PASS: "✓", FAIL: "✗", ERROR: "!", MANUAL: "·", SKIP: "-"}


def print_report(res: dict) -> None:
    print(f"{res['book']} 交付体检（{'粗校档' if res.get('tier') == 'rough' else '终校档'}）· {res['pages']} 页 · {res['workspace']}")
    for it in res["items"]:
        print(f"  {ICON[it['status']]} {it['no']:>3} {it['name']}" + (f"：{it['detail']}" if it["detail"] else ""))
    c = res["counts"]
    verdict = "机器项全部通过" if res["machine_ok"] else "机器项未通过"
    print(f"  —— {verdict}（通过 {c['pass']}，未过 {c['fail']}，出错 {c['error']}；"
          f"待人确认 {c['manual']}，未查 {c['skip']}）")
