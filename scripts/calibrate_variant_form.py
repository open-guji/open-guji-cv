# -*- coding: utf-8 -*-
"""「义定形未定」定形阈值标定（`clustering/variant_form.py` 的五个常数）。

    PYTHONPATH=. python scripts/calibrate_variant_form.py [--book vol01] [--pages 全册]

## 量什么

`decide_form` 三档：`fixed_lib`（库证据定形）/ `fixed_form`（组内三源检索定形）/
`open`（落人审）。**放行档一旦判错，就是往字形库塞一个错字形，而且会自我复制**
（match_ref 让下一个同形位继承它）——所以精度优先，覆盖其次。

真值只认**人裁**（`load_verdicts`，confirm 事件的 shape）。不能用整理本金标：
整理本对单形组只印一种形，拿它当真值等于问「你是不是等于整理本」，而这一层要答的
恰恰是「刻本刻的是哪个形」——自证。

## 数据从哪来

产物 `seed_admit` 的 `evidence.form`（`decide_form` 把三源分数全记下了），
无需重跑管线。含 `open` 档（人已裁过的，正是「本该放行却没放」的样本）。

## 三条报数纪律

1. **精度连覆盖读**：放行档精度天然虚高（放的本来就是容易的）。
2. **分层**：`fixed_lib` / `fixed_form` 分开——两者证据来源不同（库原型 vs 字体模板+CNN）。
3. **带基线**：至少报「全放行」与「现行阈值」两条，否则看不出调阈值有没有用。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import open_guji_cv.steps  # noqa: E402,F401
from open_guji_cv.clustering import variant_form as vf  # noqa: E402
from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.core.spec import page_key  # noqa: E402
from open_guji_cv.eval.round_check import load_verdicts  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402


def collect(book: str, pages: list[int]) -> list[dict]:
    """产物里所有带 `form` 证据、且有人裁真值的字位。"""
    st = ProductStore()
    truth = load_verdicts(book)
    out = []
    for pg in pages:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        for cc in a.columns:
            for r in cc.chars:
                f = (r.evidence or {}).get("form") or {}
                if not f or f.get("state") == "single":
                    continue
                human = truth.get(r.id)
                if not human:
                    continue                      # 没有独立真值，标定用不上
                lib = f.get("lib") or []
                c1, v1 = (lib[0] if lib else (None, 0.0))
                v2 = lib[1][1] if len(lib) > 1 else 0.0
                out.append({
                    "id": r.id, "human": human, "state": f.get("state"),
                    "decided": f.get("char"), "forms": f.get("forms") or [],
                    "lib_top": c1, "v1": float(v1), "gap_lib": float(v1) - float(v2),
                    "human_n": (f.get("human") or {}).get(c1, 0),
                    "agree": f.get("agree"), "emb_gap": f.get("emb_gap"),
                    "fused_top": (f.get("fused") or [None])[0],
                })
    return out


def _exact_rule(r: dict, cov: float, hn: int) -> str | None:
    """完美匹配档：cov ≥ 阈 且 该形人确认过 ≥ hn 次 → 定 lib_top。"""
    if r["lib_top"] and r["v1"] >= cov and r["human_n"] >= hn:
        return r["lib_top"]
    return None


def _margin_rule(r: dict, cov: float, margin: float) -> str | None:
    if r["lib_top"] and r["v1"] >= cov and r["gap_lib"] >= margin and r["human_n"] > 0:
        return r["lib_top"]
    return None


def _image_rule(r: dict, gap: float, hn: int) -> str | None:
    if r["agree"] and r["fused_top"] and (r["emb_gap"] or 0) >= gap \
            and r["human_n"] >= hn:
        return r["fused_top"]
    return None


def score(rows: list[dict], rule) -> tuple[int, int, int, list[str]]:
    """→ (放行数, 放行且对, 总数, 错例 id)。"""
    ok = n = 0
    bad = []
    for r in rows:
        got = rule(r)
        if got is None:
            continue
        n += 1
        if got == r["human"]:
            ok += 1
        else:
            bad.append(f"{r['id']} 判「{got}」人裁「{r['human']}」")
    return n, ok, len(rows), bad


def _line(label: str, n: int, ok: int, tot: int, bad: list[str]) -> str:
    prec = f"{ok}/{n} = {ok / n:.1%}" if n else "—"
    cov = f"{n}/{tot} = {n / tot:.0%}" if tot else "—"
    s = f"  {label:34s} 放行 {cov:14s} 精度 {prec:16s}"
    if bad:
        s += "  ✗ " + "；".join(bad[:2])
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--pages", default="")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    bk = load_book(a.book)
    pages = bk.resolve_pages(a.pages) if a.pages else bk.all_pages()
    rows = collect(a.book, pages)
    if not rows:
        print("没有可标定的样本：需要产物里带 form 证据、且该字位有人裁真值。")
        print("先去组视图抽审（判据 E 的绿点框），再跑本脚本。")
        return 1

    print(f"样本 {len(rows)} 条（{a.book}，{len(pages)} 页）")
    print("  当前状态分布:", dict(Counter(r["state"] for r in rows)))
    print("  组内形数分布:", dict(Counter(len(r["forms"]) for r in rows)))
    print()

    print("== 基线 ==")
    n, ok, tot, bad = score(rows, lambda r: r["lib_top"])
    print(_line("全放行（库 top1，不设任何闸）", n, ok, tot, bad))
    n, ok, tot, bad = score(rows, lambda r: r["fused_top"] if r["fused_top"] else None)
    print(_line("全放行（三源融合 top1）", n, ok, tot, bad))
    print()

    print(f"== 完美匹配档（现行 cov ≥ {vf.FORM_LIB_EXACT} 且人裁 ≥ {vf.FORM_EXACT_HUMAN_MIN}）==")
    for cov in (0.9999, 0.999, 0.998, 0.995):
        for hn in (1, 2, 3, 5):
            n, ok, tot, bad = score(rows, lambda r, c=cov, h=hn: _exact_rule(r, c, h))
            mark = "  ← 现行" if (cov == vf.FORM_LIB_EXACT and hn == vf.FORM_EXACT_HUMAN_MIN) else ""
            print(_line(f"cov≥{cov} 人裁≥{hn}", n, ok, tot, bad) + mark)
    print()

    print(f"== 拉开差距档（现行 cov ≥ {vf.FORM_LIB_COV} 且 margin ≥ {vf.FORM_LIB_MARGIN}）==")
    for cov in (0.95, 0.97, 0.99):
        for m in (0.003, 0.005, 0.01, 0.02):
            n, ok, tot, bad = score(rows, lambda r, c=cov, mm=m: _margin_rule(r, c, mm))
            mark = "  ← 现行" if (cov == vf.FORM_LIB_COV and m == vf.FORM_LIB_MARGIN) else ""
            print(_line(f"cov≥{cov} margin≥{m:g}", n, ok, tot, bad) + mark)
    print()

    print(f"== 图像档（现行 三源一致 且 emb_gap ≥ {vf.FORM_EMB_GAP} 且人裁 ≥ {vf.FORM_EXACT_HUMAN_MIN}）==")
    for gap in (0.01, 0.02, 0.03, 0.05):
        for hn in (1, 2):
            n, ok, tot, bad = score(rows, lambda r, g=gap, h=hn: _image_rule(r, g, h))
            mark = "  ← 现行" if (gap == vf.FORM_EMB_GAP and hn == vf.FORM_EXACT_HUMAN_MIN) else ""
            print(_line(f"emb_gap≥{gap} 人裁≥{hn}", n, ok, tot, bad) + mark)
    print()

    # 现役整体（两档合并，与生产一致）
    def live(r):
        return (_exact_rule(r, vf.FORM_LIB_EXACT, vf.FORM_EXACT_HUMAN_MIN)
                or _margin_rule(r, vf.FORM_LIB_COV, vf.FORM_LIB_MARGIN)
                or _image_rule(r, vf.FORM_EMB_GAP, vf.FORM_EXACT_HUMAN_MIN))
    n, ok, tot, bad = score(rows, live)
    print("== 现役三档合并 ==")
    print(_line("生产配置", n, ok, tot, bad))
    print("\n读法：精度必须连覆盖一起看；放行档判错 = 往字形库塞错字形且会自我复制，"
          "所以**精度优先**。样本少于 50 条时曲线不稳，别据此改阈值。")

    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n样本明细 → {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
