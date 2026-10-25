"""字组状态 → 网站后台「文本整理 · 形近字」栏（2026-10-25，A41 建的 Neon `progress` schema，口径归 A24）。

    python -m open_guji_cv.eval.group_progress <guji groups status 出的 json> [--book 96mid1ogzk] [--prev 上一份 json] [--write]

缺省只打印要写的行；`--write` 才写 Neon 正式库（`datastore.connect`，要 `NEON_DATABASE_URL`）。
只是看板数据，不影响产物与文本。写法见 kaiyuanguji-web `docs/text-progress.md` 第二节。

sheldon 10-25 定：异体（同义）与形近（不同义）字组是混合处理的，并成一栏 `xingjin`（原 `yiti` 栏写库时删掉）；
主体是一张每组一行的总表。全部写整套（`vol=''`）：
- 卡片：字组数、组内送审格、组内送审率、放行率、组判率、人裁核对准确率、组外送审（异体对 V、形近护栏 N）；
- 表（`detail.table`，网站画成可排序的整表）：
  `table.groups` 各字组总表（行点开是该组各册明细），`table.vols` 各册送审分类，`table.pairs` 组外送审的字对。
口径同 `group_status`：送审率＝送审／出现，放行率＝放行／出现，组判率＝组判／入流，
核对准确率＝（人裁核对 − 不一致）／人裁核对，两者都先扣掉疑格号漂移的。
每次写之前先删掉 A24 在这两栏的旧数，免得改名、删组后留下孤卡。
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

SECTION = "xingjin"
OLD_SECTIONS = ("xingjin", "yiti")
TITLE = "形近字"
DESCRIPTION = "形近与异体字组（同义、不同义混合处理）：各组出现、送审、送审率、核对准确率"
WHO = "A24"
CATS = {"G": "字组内", "V": "组外异体对", "N": "形近护栏", "O": "其他"}

GROUP_COLS = [
    {"key": "group", "label": "组"}, {"key": "name", "label": "字"}, {"key": "kind", "label": "类型", "hint": "同义＝异体，不同义＝形近"},
    {"key": "occ", "label": "出现", "unit": "格"}, {"key": "review", "label": "送审", "unit": "格"},
    {"key": "review_rate", "label": "送审率", "unit": "%", "hint": "送审／出现"},
    {"key": "delta", "label": "送审增减", "hint": "比上一份报告"},
    {"key": "admit_rate", "label": "放行率", "unit": "%", "hint": "放行／出现"},
    {"key": "pick_rate", "label": "组判率", "unit": "%", "hint": "组判／入流：字组流程自己判出的比例"},
    {"key": "checked", "label": "人裁核对", "unit": "格", "hint": "有人裁结论、能核对放行字的格（扣掉疑格号漂移）"},
    {"key": "wrong", "label": "不一致", "unit": "格", "hint": "放行字与人裁不同（扣掉疑格号漂移）"},
    {"key": "agree_rate", "label": "核对准确率", "unit": "%", "hint": "（人裁核对 − 不一致）／人裁核对"},
    {"key": "labels", "label": "人工数据", "hint": "刻形／文意标注条数"},
    {"key": "methods", "label": "方法"},
]
VOL_COLS = [
    {"key": "vol", "label": "册"}, {"key": "occ", "label": "出现", "unit": "格"}, {"key": "review", "label": "送审", "unit": "格"},
    {"key": "review_rate", "label": "送审率", "unit": "%"}, {"key": "admit_rate", "label": "放行率", "unit": "%"},
    {"key": "pick_rate", "label": "组判率", "unit": "%"}, {"key": "checked", "label": "人裁核对", "unit": "格"},
    {"key": "wrong", "label": "不一致", "unit": "格"}, {"key": "agree_rate", "label": "核对准确率", "unit": "%"},
]


def _vol(book: str) -> str:
    m = re.match(r"vol(\d+)$", book)
    return m.group(1).zfill(3) if m else book


def _rate(a: int, b: int):
    return round(a / b, 4) if b else None


def _stats(c: dict) -> dict:
    chk = c.get("checked", 0) - c.get("drift", 0)
    wrong = c.get("mismatch", 0) - c.get("drift", 0)
    return {"occ": c.get("occ", 0), "review": c.get("review", 0),
            "review_rate": _rate(c.get("review", 0), c.get("occ", 0)),
            "admit_rate": _rate(c.get("admit", 0), c.get("occ", 0)),
            "pick_rate": _rate(c.get("pick", 0), c.get("flow", 0)),
            "checked": chk, "wrong": wrong, "agree_rate": _rate(chk - wrong, chk)}


def _put(key, label, value, unit, text=None, detail=None, sort=100) -> tuple:
    return ("", SECTION, key, label, value, unit, text, detail, sort)


def rows(d: dict, book_id: str, prev: dict | None = None) -> list[tuple]:
    """→ [(book_id, vol, section, key, label, value, unit, value_text, detail, sort)]。"""
    gs = d["groups"]
    pg = (prev or {}).get("groups", {})
    tot = Counter()
    for g in gs.values():
        tot.update(g["total"])
    s = _stats(tot)
    rv = d.get("review") or {}
    cat_tot = {c: sum((rv.get("keys", {}).get(c) or {}).values()) for c in CATS}
    kinds = Counter(g["kind"] for g in gs.values())
    src = f"{d.get('date') or ''} {d.get('tag') or ''}".strip()

    out = [
        _put("groups", "字组数", len(gs), "组", f"同义 {kinds.get('同义', 0)} · 不同义 {kinds.get('不同义', 0)}", sort=1),
        _put("review", "组内送审", s["review"], "格", sort=2),
        _put("review_rate", "组内送审率", s["review_rate"], "%", sort=3),
        _put("admit_rate", "组内放行率", s["admit_rate"], "%", sort=4),
        _put("pick_rate", "组判率", s["pick_rate"], "%", sort=5),
        _put("agree_rate", "人裁核对准确率", s["agree_rate"], "%", f"{s['checked'] - s['wrong']}/{s['checked']}", sort=6),
        _put("review_v", "组外异体对送审", cat_tot["V"], "格", sort=7),
        _put("review_n", "形近护栏送审", cat_tot["N"], "格", sort=8),
    ]

    grows = []
    for g, v in sorted(gs.items(), key=lambda kv: (-kv[1]["total"].get("review", 0), kv[0])):
        st = _stats(v["total"])
        lab = v.get("labels") or {}
        delta = None
        if g in pg:
            delta = st["review"] - pg[g]["total"].get("review", 0)
        sub = [{"vol": b, **_stats(c)} for b, c in sorted(v["by_book"].items()) if c.get("occ")]
        grows.append({"group": g, "name": v["name"], "kind": v["kind"], **st,
                      "delta": (f"{delta:+d}" if delta else "0") if delta is not None else None,
                      "labels": f"{lab.get('shape', 0)}／{lab.get('reading', 0)}", "methods": v.get("methods"),
                      "_sub": {"columns": VOL_COLS, "rows": sub}})
    out.append(_put("table.groups", "各字组总表", len(gs), "组", src,
                    {"table": {"columns": GROUP_COLS if prev else [c for c in GROUP_COLS if c["key"] != "delta"], "rows": grows,
                               "note": "点表头排序，点一行看该组各册明细。口径见 open-guji-cv `eval/group_status.py`；"
                                       "报告原文在 open-guji-dataset `char-groups/status/`。"}}, sort=20))

    vrows = []
    for b, c in sorted((rv.get("books") or {}).items()):
        vrows.append({"vol": b, "cells": c.get("cells", 0), "review": c.get("review", 0),
                      "review_rate": _rate(c.get("review", 0), c.get("cells", 0)),
                      **{k: c.get(k, 0) for k in CATS}})
    if vrows:
        cols = [{"key": "vol", "label": "册"}, {"key": "cells", "label": "全册格", "unit": "格"},
                {"key": "review", "label": "送审", "unit": "格"}, {"key": "review_rate", "label": "送审率", "unit": "%"}]
        cols += [{"key": k, "label": n, "unit": "格"} for k, n in CATS.items()]
        out.append(_put("table.vols", "各册送审分类", len(vrows), "册", src,
                        {"table": {"columns": cols, "rows": vrows,
                                   "note": "全册送审按原因分：字组内（G）、组外异体对（V）、形近护栏（N）、其他（O，缺字、切分等，不归本栏）。"}},
                        sort=30))

    prows = []
    for cat in ("V", "N"):
        per = (rv.get("keys_by_book") or {}).get(cat) or {}
        for k, n in (rv.get("keys", {}).get(cat) or {}).items():
            prows.append({"cat": CATS[cat], "key": k, "review": n, "vols": "、".join(sorted(per.get(k, {})))})
    if prows:
        prows.sort(key=lambda r: (-r["review"], r["cat"], r["key"]))
        out.append(_put("table.pairs", "组外送审字对", len(prows), "对", src,
                        {"table": {"columns": [{"key": "cat", "label": "类别"}, {"key": "key", "label": "字"},
                                               {"key": "review", "label": "送审", "unit": "格"}, {"key": "vols", "label": "册"}],
                                   "rows": prows,
                                   "note": "还没进字组的异体对与形近护栏拦下的格，按送审从多到少；多的可以考虑建组。"}},
                        sort=40))
    return [(book_id, *r) for r in out]


def write(rs: list[tuple]) -> int:
    from ..datastore.connect import connect
    with connect() as conn:
        conn.execute("DELETE FROM progress.metric WHERE writer = %s AND section = ANY(%s)", (WHO, list(OLD_SECTIONS)))
        conn.execute("DELETE FROM progress.section WHERE section = 'yiti' AND owner = %s", (WHO,))
        conn.execute("UPDATE progress.section SET title = %s, description = %s WHERE section = %s", (TITLE, DESCRIPTION, SECTION))
        for book_id, vol, sec, key, label, value, unit, text, detail, sort in rs:
            conn.execute("SELECT progress.put_metric(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
                         (book_id, vol, sec, key, label, value, unit, WHO, text,
                          json.dumps(detail, ensure_ascii=False) if detail else None, sort))
    return len(rs)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("status_json", type=Path)
    ap.add_argument("--book", default="96mid1ogzk", help="book-index 套书 id（殿本《四庫全書總目》）")
    ap.add_argument("--prev", type=Path, help="上一份 guji groups status 的 json，总表写送审增减")
    ap.add_argument("--write", action="store_true", help="真写 Neon 正式库（缺省只打印）")
    a = ap.parse_args(argv)
    prev = json.loads(a.prev.read_text(encoding="utf-8")) if a.prev else None
    rs = rows(json.loads(a.status_json.read_text(encoding="utf-8")), a.book, prev)
    if not a.write:
        for r in rs:
            print("\t".join("" if x is None else (json.dumps(x, ensure_ascii=False)[:200] if isinstance(x, dict) else str(x)) for x in r))
        print(f"共 {len(rs)} 行（只打印；加 --write 才写库）")
        return 0
    print("写", write(rs), "行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
