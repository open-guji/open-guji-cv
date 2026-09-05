# -*- coding: utf-8 -*-
"""一轮审阅的体检命令：四个判据 + 下一批页码 + 回归三件套。

用法（三选一，见 `.claude/doc/review_loop_sop.md`）：

    # 这批跑得怎么样、要不要修算法
    python scripts/round_check.py --pages 44,45,46,48,49,50,51,52,53,54,55,56

    # 下一批审哪几页
    python scripts/round_check.py --next

    # 改完算法有没有退
    python scripts/round_check.py --regression

设计意图是**让判断不需要人参与**：每个指标都印出绿/黄/红和对应动作，
而不是印一堆数让人自己想。阈值来自 SOP §2，改阈值要同步改那份文档。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

DATASET = Path("../open-guji-dataset")
GREEN, YELLOW, RED = "✓ 绿", "~ 黄", "✗ 红"


def _light(v, green, yellow) -> str:
    """v 越小越好：≤green 绿，≤yellow 黄，否则红。"""
    if v is None:
        return "— 无数据"
    return GREEN if v <= green else (YELLOW if v <= yellow else RED)


def load_verdicts(book: str) -> dict[str, str]:
    """用户 confirm 事件 → {字位: 字形}，后裁覆盖先裁。"""
    out: dict[str, str] = {}
    d = DATASET / "feedback" / "events"
    for p in sorted(d.glob(f"{book}-*.jsonl")) if d.exists() else []:
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            pl = e.get("payload") or {}
            if e.get("actor") == "user" and e.get("kind") == "confirm" \
                    and pl.get("v") == "confirm" and pl.get("shape"):
                out[e["target"]["key"]] = pl["shape"]
    return out


def cmd_next(book: str, n: int) -> int:
    """下一批页码：正文页里没跑过 seed_admit 的，顺序取 n 个。

    ⚠️ 不能按页号顺推——vol01 的 p89-113 是职名页、p61/159-182 是目录页，
    用正文的 21 格先验跑必然全灭（见 books/vol01.yaml 里 p119 的教训）。
    """
    from open_guji_cv.products import kinds as _k  # noqa: F401
    from open_guji_cv.core.step import page_key
    from open_guji_cv.products.store import ProductStore

    rows = [json.loads(l) for l in
            (DATASET / "page-type" / "items.jsonl").read_text(encoding="utf-8").splitlines()]
    body = sorted(int(r["anchor"]["page"]) for r in rows
                  if str(r.get("anchor", {}).get("book")) == book
                  and (r.get("expected") or {}).get("page_type") == "body")
    st = ProductStore()
    todo = [p for p in body
            if st.read(book, "seed_admit", page_key(p), "seed_admit") is None]
    print(f"{book} 正文页 {len(body)}，已处理 {len(body) - len(todo)}，剩 {len(todo)}")
    if not todo:
        print("正文页跑完了。")
        return 0
    batch = todo[:n]
    print(f"\n下一批（{len(batch)} 页）：")
    print("  " + ",".join(str(p) for p in batch))
    print(f"\n跑：python -m open_guji_cv pipeline keben_body_v2 {book} --pages "
          + ",".join(str(p) for p in batch))
    print("审：控制台 → 审查 → 页码填上面那串 → 载入")
    return 0


def cmd_regression(book: str) -> int:
    """回归三件套：单测 / 四把尺子 / 双真值准确率。"""
    ok = True
    print("=== ① 单测 ===")
    # 逐文件跑：本机 pytest 收尾会崩（I/O operation on closed file），退出码不可信
    passed = failed = 0
    bad_files = []
    for f in sorted(Path("tests").glob("test_*.py")):
        r = subprocess.run([sys.executable, "-m", "pytest", str(f), "-v",
                            "-p", "no:cacheprovider", "--capture=no"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        out = r.stdout or ""
        p = out.count(" PASSED")
        fl = out.count(" FAILED") + out.count(" ERROR")
        passed += p
        failed += fl
        if fl:
            bad_files.append(f"{f.name}({fl})")
    print(f"  PASSED={passed} FAILED={failed} {GREEN if not failed else RED}")
    if bad_files:
        print("  问题文件:", " ".join(bad_files))
        ok = False

    print("\n=== ② 四把尺子（dev_set）===")
    from open_guji_cv.core.book import load_book
    from open_guji_cv.eval.rulers import measure
    bk = load_book(book)
    limits = {"R1": (None, None), "R2": (0.2, 0.5), "R3": (0, 0), "R4": (0.1, 0.3)}
    for r in measure(book, bk.resolve_pages("dev_set"))["rulers"]:
        v = r["value"]
        key = r["key"]
        if key == "R1":
            mark = GREEN if r["num"] == r["den"] else RED
        elif key in limits:
            g, y = limits[key]
            mark = _light(v, g, y)
        else:
            mark = "—"
        print(f"  {key:4s} {r['title'][:26]:28s} {str(v):>7}{r['unit']} {mark}")
        if mark == RED:
            ok = False

    print("\n=== ③ 双真值准确率（dev_set）===")
    acc = _accuracy(book, bk.resolve_pages("dev_set"))
    for k, (o, n) in acc.items():
        if not n:
            continue
        rate = o / n
        mark = GREEN if rate == 1.0 else (YELLOW if rate >= 0.999 else RED)
        print(f"  {k}: {o}/{n} = {rate:.2%} {mark}")
        if mark == RED:
            ok = False
    print("\n" + ("全部通过，可以继续。" if ok else "⚠ 有红灯，别提交，先查上面标红那项。"))
    return 0 if ok else 1


def _same_char(a: str | None, b: str | None) -> bool:
    """互为异体就当同一个字。"""
    if not a or not b:
        return False
    try:
        from open_guji_cv.variants import are_variants
        return bool(are_variants(a, b))
    except Exception:
        return False


def _accuracy(book: str, pages: list[int]) -> dict:
    from open_guji_cv.products import kinds as _k  # noqa: F401
    from open_guji_cv.core.step import page_key
    from open_guji_cv.gold.v2_align import align_book
    from open_guji_cv.products.store import ProductStore

    st = ProductStore()
    gold = {c.id: c for g in align_book(book, pages, st) if g.anchored for c in g.chars}
    truth = load_verdicts(book)
    okg = ng = okt = nt = 0
    for pg in pages:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        for cc in a.columns:
            for r in cc.chars:
                if not r.admit or not r.char:
                    continue
                g = gold.get(r.id)
                if g:
                    ng += 1
                    # 异体对不算错：刻本刻「卽」而整理本作「即」，字形层照录
                    # 是对的——金标比的是 shape，而整理本给的是通行字。
                    okg += (r.char == g.shape or r.char == g.reading
                            or _same_char(r.char, g.shape))
                t = truth.get(r.id)
                if t:
                    nt += 1
                    okt += (r.char == t)
    return {"对整理本金标": (okg, ng), "对你的裁决": (okt, nt)}


def cmd_check(book: str, pages: list[int]) -> int:
    """四个判据 + 动作建议。"""
    from open_guji_cv.products import kinds as _k  # noqa: F401
    from open_guji_cv.core.step import page_key
    from open_guji_cv.gold.store import GoldStore
    from open_guji_cv.products.store import ProductStore

    st = ProductStore()
    print(f"=== 本轮 {len(pages)} 页 ===")

    # A 自动放行错误率
    acc = _accuracy(book, pages)
    worst = 0.0
    for k, (o, n) in acc.items():
        if n:
            err = 1 - o / n
            worst = max(worst, err)
            print(f"A 自动放行 {k}: {o}/{n} = {o/n:.2%}")
    mark_a = _light(worst * 100, 0.0, 0.1)
    print(f"  → {mark_a}" + ("" if mark_a == GREEN else "  ⚠ 先看图确认是管线错还是金标错/你被坏图块误导"))

    # B 人审率
    tot = auto = 0
    per = Counter()
    for pg in pages:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        for cc in a.columns:
            for r in cc.chars:
                tot += 1
                if r.admit:
                    auto += 1
                else:
                    per[pg] += 1
    rate = (tot - auto) / tot * 100 if tot else None
    print(f"\nB 人审率: {tot-auto}/{tot} = {rate:.2f}%  → {_light(rate, 1.5, 3.0)}")
    if per:
        print("  按页:", " ".join(f"p{p}:{per[p]}" for p in pages if per[p]))

    # C 缺陷聚集（全量累计，不只本轮——聚集要攒才看得出来）
    gs = GoldStore(DATASET)
    ev = [i for i in gs.list("char-segmentation/instances")
          if i.source_events and i.expected.get("quality") in ("truncated", "contaminated")]
    slot = Counter(i.anchor.slot for i in ev)
    page_of = {}
    for i in ev:
        page_of.setdefault(i.anchor.slot, set()).add(i.anchor.page)
    print(f"\nC 缺陷聚集（累计 {len(ev)} 条未痊愈）:")
    worst_slot = None
    for sl, n in slot.most_common(5):
        npg = len(page_of.get(sl, ()))
        flag = " ← 扎堆" if n >= 6 and npg >= 3 else ""
        print(f"  格位 {sl}: {n} 条，横跨 {npg} 页{flag}")
        if n >= 6 and npg >= 3 and worst_slot is None:
            worst_slot = sl
    if worst_slot is not None:
        print(f"  → {RED}  格位 {worst_slot} 系统性问题，**停下修算法**")
    elif slot and slot.most_common(1)[0][1] >= 3:
        print(f"  → {YELLOW}  先记着，继续跑，攒够再查")
    else:
        print(f"  → {GREEN}")

    # D 生僻字 top-10（有集才跑）
    rc = DATASET / "rare-char" / "items.jsonl"
    print("\nD 生僻字 top-10 命中: ", end="")
    if not rc.exists():
        print("— 还没有 rare-char 集")
    else:
        print("（跑 scripts/eval_rare_char.py 看，约 20 秒）")

    print("\n下一批: python scripts/round_check.py --next")
    return 0


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
    pages = [int(x) for x in a.pages.replace(" ", "").split(",") if x]
    return cmd_check(a.book, pages)


if __name__ == "__main__":
    raise SystemExit(main())
