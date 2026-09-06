# -*- coding: utf-8 -*-
"""一轮审阅的体检（命令行外壳）。判据与阈值在 `open_guji_cv/eval/round_check.py`。

控制台「审查」页顶部有同一套（`/api/round`），两边共用那个模块——
阈值只写一处，免得过一阵子对不上。

用法（见 `.claude/doc/review_loop_sop.md`）：
    python scripts/round_check.py --pages 44,45,46,...   这批要不要停下修算法
    python scripts/round_check.py --next                 下一批审哪几页
    python scripts/round_check.py --regression           改完有没有退
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from open_guji_cv.eval import round_check as rc

MARK = {"green": "✓ 绿", "yellow": "~ 黄", "red": "✗ 红", "none": "— 无数据"}


def cmd_next(book: str, n: int) -> int:
    d = rc.next_batch(book, n)
    if d.get("error"):
        print(d["error"])
        return 1
    print(f"{book} 正文页 {d['body_total']}，已处理 {d['done']}，剩 {d['todo']}")
    if not d["batch"]:
        print("正文页跑完了。")
        return 0
    ids = ",".join(str(p) for p in d["batch"])
    print(f"\n下一批（{len(d['batch'])} 页）：\n  {ids}")
    print(f"\n跑：python -m open_guji_cv pipeline keben_body_v2 {book} --pages {ids}")
    print("审：控制台 → 审查 → 页码填上面那串 → 载入")
    return 0


def cmd_check(book: str, pages: list[int]) -> int:
    d = rc.check(book, pages)
    print(f"=== 本轮 {len(pages)} 页 ===")
    a = d["A"]
    for key, label in (("gold", "对整理本金标"), ("human", "对你的裁决")):
        o, n = a[key]
        if n:
            print(f"A 自动放行 {label}: {o}/{n} = {o / n:.2%}")
    print(f"  → {MARK[a['light']]}"
          + ("" if a["light"] == "green"
             else "  ⚠ 先看图确认是管线错、金标错、还是你被坏图块误导"))
    for e in a["errors"][:5]:
        print(f"     {e['id']} 判「{e['pred']}」金标「{e['gold']}」({e['channel']})")

    b = d["B"]
    print(f"\nB 人审率: {b['review']}/{b['total']} = {b['rate']:.2%}"
          f"  → {MARK[b['light']]}"
          + (f"（另有 {b['excluded']} 格在排除名单里，不进分母）" if b.get("excluded") else ""))
    if b["by_page"]:
        print("  按页:", " ".join(f"p{r['page']}:{r['n']}" for r in b["by_page"]))

    c = d["C"]
    print(f"\nC 缺陷聚集（累计 {c['total']} 条未痊愈）:")
    for r in c["rows"][:5]:
        flag = " ← 扎堆" if (c["worst"] and r["slot"] == c["worst"]["slot"]) else ""
        print(f"  格位 {r['slot']}: {r['n']} 条，横跨 {r['pages']} 页{flag}")
    print(f"  → {MARK[c['light']]}"
          + (f"  格位 {c['worst']['slot']} 系统性问题，**停下修算法**" if c["worst"]
             else ("  先记着，继续跑，攒够再查" if c["light"] == "yellow" else "")))

    t = d["C2"]
    print("\nC2 字距（挤排页 = 切分物理受限）:")
    for r in t["rows"]:
        print(f"  p{r['page']}: 字间隙中位 {r['median_gap']:.0f}px，"
              f"{r['near_ratio']:.0%} 不足 5px ← 挤排")
    print(f"  → {MARK[t['light']]}"
          + ("  这几页字物理相连，切分做不到完美；人审会偏多，"
             "标缺陷即可，**不算算法退步**" if t["rows"] else "  字距正常"))

    dd = d.get("D") or {}
    if dd.get("rate") is not None:
        print(f"\nD 生僻字 top-10（字体模板+CNN 融合，rare-char {dd['n']} 条）: "
              f"{dd['hit']}/{dd['n']} = {dd['rate']:.1%}  → {MARK[dd['light']]}"
              + (f"  ⚠ {dd['note']}" if dd.get("note") else ""))
    else:
        print(f"\nD 生僻字 top-10: — {dd.get('note', '')}")

    e = d.get("E") or {}
    if e:
        fa = e.get("form_auto") or [0, 0]
        head = (f"\nE 字形保真率（异体位自动放行 {e['variant_admits']} 条，"
                f"义定形未定待审 {e['form_open']} 条）: ")
        if e.get("audited"):
            print(head + f"人裁核过 {e['hit']}/{e['audited']} = {e['rate']:.1%}"
                  f"（Wilson 下界 {e['wilson_low']:.3f}；其中 variant_form 定形 {fa[0]}/{fa[1]}）"
                  f"  → {MARK[e['light']]}" + (f"  ⚠ {e['note']}" if e.get("note") else ""))
        else:
            print(head + f"— 还没有人裁核过的异体位  → {MARK[e['light']]}")
        for x in e.get("errors", [])[:5]:
            print(f"     {x['id']} 存「{x['pred']}」人裁「{x['human']}」(reading {x['reading']}, {x['state']})")

    print("\n下一批: python scripts/round_check.py --next")
    return 0


def cmd_regression(book: str) -> int:
    """回归三件套：单测 / 四把尺子 / 双真值准确率。"""
    ok = True
    print("=== ① 单测 ===")
    passed = failed = 0
    bad_files = []
    for f in sorted(Path("tests").glob("test_*.py")):
        r = subprocess.run([sys.executable, "-m", "pytest", str(f), "-v",
                            "-p", "no:cacheprovider", "--capture=no"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        # 本机 pytest 收尾会崩（I/O operation on closed file），统计可能落在
        # stderr——只读 stdout 会把整段吞掉，看起来像没跑。两个流都算。
        out = (r.stdout or "") + (r.stderr or "")
        p = out.count(" PASSED")
        fl = out.count(" FAILED") + out.count(" ERROR")
        passed += p
        failed += fl
        if fl:
            bad_files.append(f"{f.name}({fl})")
    print(f"  PASSED={passed} FAILED={failed} "
          f"{MARK['green'] if not failed else MARK['red']}")
    if bad_files:
        print("  问题文件:", " ".join(bad_files))
        ok = False

    print("\n=== ② 四把尺子（dev_set）===")
    from open_guji_cv.core.book import load_book
    from open_guji_cv.eval.rulers import measure
    bk = load_book(book)
    limits = {"R2": (0.2, 0.5), "R2s": (3.0, 5.0), "R2x": (0.3, 1.0), "R3": (0, 0), "R4": (0.1, 0.3)}
    for r in measure(book, bk.resolve_pages("dev_set"))["rulers"]:
        k = r["key"]
        if k == "R1":
            mark = MARK["green"] if r["num"] == r["den"] else MARK["red"]
        elif k in limits:
            mark = MARK[rc._light(r["value"], *limits[k])]
        else:
            mark = "—"
        print(f"  {k:4s} {r['title'][:26]:28s} {str(r['value']):>7}{r['unit']} {mark}")
        if mark == MARK["red"]:
            ok = False

    print("\n=== ③ 双真值准确率（dev_set）===")
    acc = rc.accuracy(book, bk.resolve_pages("dev_set"))
    for key, label in (("gold", "对整理本金标"), ("human", "对你的裁决")):
        o, n = acc[key]
        if not n:
            continue
        rate = o / n
        mark = MARK["green"] if rate == 1.0 else (
            MARK["yellow"] if rate >= 0.999 else MARK["red"])
        print(f"  {label}: {o}/{n} = {rate:.2%} {mark}")
        if mark == MARK["red"]:
            ok = False
    print("\n" + ("全部通过，可以继续。" if ok else "⚠ 有红灯，别提交，先查标红那项。"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--pages", default="")
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--regression", action="store_true")
    ap.add_argument("-n", type=int, default=12, help="下一批取几页")
    a = ap.parse_args()
    if a.next:
        return cmd_next(a.book, a.n)
    if a.regression:
        return cmd_regression(a.book)
    if not a.pages:
        ap.error("给 --pages，或用 --next / --regression")
    return cmd_check(a.book, [int(x) for x in a.pages.replace(" ", "").split(",") if x])


if __name__ == "__main__":
    raise SystemExit(main())
