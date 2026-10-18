# -*- coding: utf-8 -*-
"""重落前后 seed_admit 产物对账 + 红线格检查（S26 同步检查）。只读。

    python relanding_diff.py <重落前products根> <重落后products根> <册...> [--redlines redlines.txt]
        [--max-new-per-channel 30] [--max-new-per-page 5] [--json out.json]

新口径（用户 10-17）：红线格/个别格错只报数不停线；仅「系统性错放（一类格成片）」才退出码 3 提示停线：
  · 某册某通道「待审→放行」新放行格 ≥ --max-new-per-channel；或
  · 某页「待审→放行」新放行格 ≥ --max-new-per-page。
红线格从待审变放行：单独列出（报数，不单独停线），退出码仍 0；但会打印 ⚠。
退出码：0 无系统性迹象；3 触发系统性阈值（停线报 Mila）；2 输入有误。
同时报：页 json 逐页 sha256 不同页数、放行→待审（降级）按通道、待审→放行（新放行）按通道。
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load(root: Path, book: str) -> dict[str, dict]:
    d = root / book / "seed_admit"
    if not d.is_dir():
        sys.exit(f"没有 {d}")
    cells = {}
    for p in sorted(d.glob("p*.json")):
        s = json.loads(p.read_text(encoding="utf-8"))["seed_admit"]
        for col in s.get("columns", []):
            for r in col.get("chars") or []:
                cells[r["id"]] = {"admit": bool(r.get("admit")), "channel": r.get("channel"), "char": r.get("char"),
                                  "doubts": r.get("doubts") or [], "page": s["page"]}
    return cells


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("books", nargs="+")
    ap.add_argument("--redlines", default=str(Path(__file__).with_name("redlines.txt")))
    ap.add_argument("--max-new-per-channel", type=int, default=30)
    ap.add_argument("--max-new-per-page", type=int, default=5)
    ap.add_argument("--json")
    ap.add_argument("--list", help="差异格明细 TSV：册/id/页/前后 admit/前后字/前后通道")
    a = ap.parse_args()
    red = [l.strip() for l in open(a.redlines, encoding="utf-8") if l.strip() and not l.startswith("#")]
    stop, out, rows = False, {}, []
    for book in a.books:
        b, n = load(Path(a.before), book), load(Path(a.after), book)
        pages_b = {p.name: p.read_bytes() for p in (Path(a.before) / book / "seed_admit").glob("p*.json")}
        pages_a = {p.name: p.read_bytes() for p in (Path(a.after) / book / "seed_admit").glob("p*.json")}
        page_diff = sum(1 for k in pages_a if pages_b.get(k) != pages_a[k])
        missing = [i for i in b if i not in n]
        added = [i for i in n if i not in b]
        up, down = Counter(), Counter()
        up_page = defaultdict(int)
        char_changed = 0
        for i, x in b.items():
            y = n.get(i)
            if not y:
                continue
            if x["admit"] and y["admit"] and x["char"] != y["char"]:
                char_changed += 1
            if not x["admit"] and y["admit"]:
                up[y["channel"]] += 1
                up_page[y["page"]] += 1
            elif x["admit"] and not y["admit"]:
                down[x["channel"]] += 1
        for i, x in b.items():
            y = n.get(i)
            if y and (x["admit"], x["char"], x["channel"]) != (y["admit"], y["char"], y["channel"]):
                rows.append((book, i, y["page"], x["admit"], y["admit"], x["char"], y["char"], x["channel"], y["channel"]))
        flags = [f"通道 {c} 新放行 {k} ≥ {a.max_new_per_channel}" for c, k in up.items() if k >= a.max_new_per_channel]
        flags += [f"p{p} 新放行 {k} ≥ {a.max_new_per_page}" for p, k in up_page.items() if k >= a.max_new_per_page]
        reds = []
        for r in red:
            if not r.startswith(book + ":"):
                continue
            x, y = b.get(r), n.get(r)
            reds.append({"id": r, "before": None if x is None else x["admit"], "after": None if y is None else y["admit"],
                         "channel": None if y is None else y["channel"]})
        warn = [r for r in reds if r["before"] is False and r["after"]]
        print(f"== {book}：页 json 不同 {page_diff}/{len(pages_a)}；格 前{len(b)}→后{len(n)}（缺 {len(missing)}、新增 {len(added)}）；放行字被改 {char_changed}")
        print(f"   待审→放行 {sum(up.values())}：{dict(up)}；放行→待审 {sum(down.values())}：{dict(down)}")
        for r in reds:
            print(f"   红线 {r['id']}: 前 admit={r['before']} 后 admit={r['after']} 通道={r['channel']}" + ("  ⚠ 待审→放行" if r in warn else ""))
        for f in flags:
            print(f"   ‼ 系统性迹象：{f}")
        stop |= bool(flags)
        out[book] = {"pages_diff": page_diff, "up": dict(up), "down": dict(down), "char_changed": char_changed,
                     "missing": missing[:50], "added": added[:50], "redlines": reds, "flags": flags}
    if a.list:
        with open(a.list, "w", encoding="utf-8") as f:
            f.write("book\tid\tpage\tadmit_前\tadmit_后\tchar_前\tchar_后\tchannel_前\tchannel_后\n")
            for r in rows:
                f.write("\t".join(str(v) for v in r) + "\n")
        print(f"差异格明细 {len(rows)} 行 → {a.list}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("结论：" + ("触发系统性阈值，停线报 Mila（退出码3）" if stop else "无系统性迹象（只报数）"))
    return 3 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
