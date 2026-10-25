"""字组状态 → 网站后台「文本整理」栏（2026-10-25，A41 建的 Neon `progress` schema，口径归 A24）。

    python -m open_guji_cv.eval.group_progress <guji groups status 出的 json> [--book 96mid1ogzk] [--write]

缺省只打印要写的行；`--write` 才调 `progress.put_metric` 写 Neon 正式库（`datastore.connect`，要 `NEON_DATABASE_URL`）。
只是看板数据，不影响产物与文本。写法见 kaiyuanguji-web `docs/text-progress.md` 第二节。

两栏：
- `yiti` 异体字组：同义组（`kind=同义`）＋送审分类里的 V（组外异体对）；
- `xingjin` 形近字：不同义组＋送审分类里的 N（形近护栏）。
每栏写整套（`vol=''`）与各册（`vol`＝册号三位，vol05 → `005`）：送审格、放行率、组判率、人裁核对一致率；
整套另写组数、组外送审，`detail` 放送审最多的组与键；每个字组再写一张卡（key `group.<组>`（库里 key 只许 [a-z0-9_.-]），值＝送审格，
`value_text` 写出现格、放行率、组判率，`detail` 放整组口径与各册送审），按送审从多到少排。
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

SECTIONS = {"yiti": ("同义", "V", "组外异体对"), "xingjin": ("不同义", "N", "形近护栏")}
WHO = "A24"
SORT = {"groups": 5, "review": 10, "review_out": 20, "admit_rate": 30, "pick_rate": 40, "agree_rate": 50}   # 页面列序


def _vol(book: str) -> str:
    m = re.match(r"vol(\d+)$", book)
    return m.group(1).zfill(3) if m else book


def _rate(a: int, b: int):
    return round(a / b, 4) if b else None


def rows(d: dict, book_id: str) -> list[tuple]:
    """→ [(book_id, vol, section, key, label, value, unit, value_text, detail, sort)]；sort 为 None 时按 SORT。"""
    out = []
    rv = d.get("review") or {}
    for sec, (kind, cat, cat_name) in SECTIONS.items():
        gs = {g: v for g, v in d["groups"].items() if v["kind"] == kind}
        per_book: dict = {}
        tot = Counter()
        for g in gs.values():
            for b, c in g["by_book"].items():
                per_book.setdefault(b, Counter()).update(c)
            tot.update(g["total"])
        cat_by_book = Counter()
        for k, per in (rv.get("keys_by_book", {}).get(cat) or {}).items():
            cat_by_book.update(per)

        def put(vol, c, extra_review):
            chk = c.get("checked", 0) - c.get("drift", 0)
            real = c.get("mismatch", 0) - c.get("drift", 0)
            out.extend([
                (book_id, vol, sec, "review", "送审格（组内）", c.get("review", 0), "格", None, None, None),
                (book_id, vol, sec, "review_out", f"送审格（{cat_name}）", extra_review, "格", None, None, None),
                (book_id, vol, sec, "admit_rate", "组内放行率", _rate(c.get("admit", 0), c.get("occ", 0)), "%", None, None, None),
                (book_id, vol, sec, "pick_rate", "组判率", _rate(c.get("pick", 0), c.get("flow", 0)), "%", None, None, None),
                (book_id, vol, sec, "agree_rate", "人裁核对一致率", _rate(chk - real, chk), "%", None, None, None),
            ])

        put("", tot, sum(cat_by_book.values()))
        top_g = sorted(((v["total"].get("review", 0), g) for g, v in gs.items()), reverse=True)[:10]
        top_k = sorted(((n, k) for k, n in (rv.get("keys", {}).get(cat) or {}).items()), reverse=True)[:10]
        out.append((book_id, "", sec, "groups", "字组数", len(gs), "组", None,
                    {"date": d.get("date"), "tag": d.get("tag"),
                     "top_groups": [{"group": g, "name": gs[g]["name"], "review": n} for n, g in top_g if n],
                     "top_keys": [{"key": k, "review": n} for n, k in top_k]}, None))
        for b in d["books"]:
            put(_vol(b), per_book.get(b, Counter()), cat_by_book.get(b, 0))
        ranked = sorted(gs.items(), key=lambda kv: (-kv[1]["total"].get("review", 0), kv[0]))
        for i, (g, v) in enumerate(ranked):
            t = v["total"]
            rates = [("放行率", _rate(t.get("admit", 0), t.get("occ", 0))), ("组判率", _rate(t.get("pick", 0), t.get("flow", 0)))]
            text = "　".join([f"出现 {t.get('occ', 0)}"] + [f"{n} {r:.1%}" for n, r in rates if r is not None])
            out.append((book_id, "", sec, f"group.{g}", f"{v['name']}（{g}）", t.get("review", 0), "格", text,
                        {"date": d.get("date"), "tag": d.get("tag"), "total": dict(t),
                         "review_by_vol": {_vol(b): c.get("review", 0) for b, c in v["by_book"].items() if c.get("review")}},
                        100 + i))
    return out


def write(rs: list[tuple]) -> int:
    from ..datastore.connect import connect
    with connect() as conn:
        for book_id, vol, sec, key, label, value, unit, text, detail, sort in rs:
            conn.execute("SELECT progress.put_metric(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
                         (book_id, vol, sec, key, label, value, unit, WHO, text,
                          json.dumps(detail, ensure_ascii=False) if detail else None,
                          sort if sort is not None else SORT.get(key, 100)))
    return len(rs)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("status_json", type=Path)
    ap.add_argument("--book", default="96mid1ogzk", help="book-index 套书 id（殿本《四庫全書總目》）")
    ap.add_argument("--write", action="store_true", help="真写 Neon 正式库（缺省只打印）")
    a = ap.parse_args(argv)
    rs = rows(json.loads(a.status_json.read_text(encoding="utf-8")), a.book)
    if not a.write:
        for r in rs:
            print("\t".join("" if x is None else (json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else str(x)) for x in r))
        print(f"共 {len(rs)} 行（只打印；加 --write 才写库）")
        return 0
    print("写", write(rs), "行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
