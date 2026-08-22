"""行列识别评测：列型分类 + 每列字数，按页型分层。

为什么必须分层
--------------
正文页占语料约 80%，职名/上谕页才是增益来源。混在一起求平均，两边的
信号互相掩盖——原来那个「chars_per_line 准确率 10%」之所以什么也说明
不了，正是因为它把「同一本书里 21 字的正文列」和「字数天生就不固定的
职名列」按同一把尺子算了对错。

为什么不用总准确率作主指标
--------------------------
`elastic` 是少数类（实测约占 15%~18%）。全判 `rigid` 就能拿到 ~85% 的
准确率却毫无用处，所以主指标取 **elastic 的 F1**，准确率只作参考。
"""

from __future__ import annotations

from collections import defaultdict

from .layout_spec import SCORED_LAYOUTS, PageLayout


def _f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return round(p, 4), round(r, 4), round(f, 4)


def compare_page(gold: PageLayout, pred: PageLayout) -> dict:
    """逐列比对一页。列按 index 对齐；金标里没有的预测列计入 n_cols 误差。"""
    g_by = {c.index: c for c in gold.columns}
    p_by = {c.index: c for c in pred.columns}
    shared = sorted(set(g_by) & set(p_by), reverse=True)

    tp = fp = fn = tn = 0
    n_chars_exact = 0
    n_chars_abs_err = 0
    n_chars_scored = 0
    n_skipped = 0
    per_col = []
    for i in shared:
        g, p = g_by[i], p_by[i]
        if g.layout not in SCORED_LAYOUTS:
            n_skipped += 1          # 空列/存疑列不进分类与字数指标
            continue
        ge, pe = g.layout == "elastic", p.layout == "elastic"
        if ge and pe:
            tp += 1
        elif pe and not ge:
            fp += 1
        elif ge and not pe:
            fn += 1
        else:
            tn += 1
        if g.n_chars is not None and p.n_chars is not None:
            n_chars_scored += 1
            err = abs(g.n_chars - p.n_chars)
            n_chars_abs_err += err
            if err == 0:
                n_chars_exact += 1
        per_col.append({"index": i, "gold": g.layout, "pred": p.layout,
                        "gold_n_chars": g.n_chars, "pred_n_chars": p.n_chars})
    return {
        "book": gold.book, "page": gold.page,
        "page_class": gold.page_class or gold.derived_page_class(),
        "n_cols_gold": len(gold.columns), "n_cols_pred": len(pred.columns),
        "n_cols_exact": len(gold.columns) == len(pred.columns),
        "n_shared": len(shared),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "n_chars_exact": n_chars_exact,
        "n_chars_abs_err": n_chars_abs_err,
        "n_chars_scored": n_chars_scored,
        "n_skipped": n_skipped,
        "per_col": per_col,
    }


def _aggregate(rows: list[dict]) -> dict:
    if not rows:
        return {"n_pages": 0, "n_cols": 0}
    tp = sum(r["tp"] for r in rows)
    fp = sum(r["fp"] for r in rows)
    fn = sum(r["fn"] for r in rows)
    tn = sum(r["tn"] for r in rows)
    n = tp + fp + fn + tn
    p, r_, f = _f1(tp, fp, fn)
    n_chars_exact = sum(r["n_chars_exact"] for r in rows)
    n_cs = sum(r.get("n_chars_scored", 0) for r in rows)
    return {
        "n_pages": len(rows),
        "n_cols": n,
        "n_skipped": sum(r.get("n_skipped", 0) for r in rows),
        "n_cols_exact_pages": sum(1 for r in rows if r["n_cols_exact"]),
        "layout_acc": round((tp + tn) / n, 4) if n else 0.0,
        "elastic_precision": p,
        "elastic_recall": r_,
        "elastic_f1": f,
        "elastic_gold": tp + fn,
        "elastic_pred": tp + fp,
        "n_chars_scored": n_cs,
        "n_chars_exact_rate": round(n_chars_exact / n_cs, 4) if n_cs else None,
        "n_chars_mae": round(sum(r["n_chars_abs_err"] for r in rows) / n_cs, 3)
                       if n_cs else None,
    }


def evaluate(pairs: list[tuple[PageLayout, PageLayout]]) -> dict:
    """pairs = [(gold, pred)]，返回总体 + 按页型分层的报告。"""
    rows = [compare_page(g, p) for g, p in pairs]
    by_class: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_class[r["page_class"]].append(r)
    return {
        "overall": _aggregate(rows),
        "by_page_class": {k: _aggregate(v) for k, v in sorted(by_class.items())},
        "pages": rows,
    }


def format_report(report: dict) -> str:
    def line(name: str, a: dict) -> str:
        return (f"{name:<12} 页{a['n_pages']:>4} 列{a['n_cols']:>5}  "
                f"列型准确率 {a['layout_acc']:>6.1%}  "
                f"elastic P/R/F1 {a['elastic_precision']:>5.2f}/"
                f"{a['elastic_recall']:>5.2f}/{a['elastic_f1']:>5.2f}  "
                + (f"字数全对 {a['n_chars_exact_rate']:>6.1%}  "
                   f"字数MAE {a['n_chars_mae']:>5.2f}"
                   if a.get('n_chars_exact_rate') is not None else "字数未标"))

    out = ["【总体】", line("all", report["overall"]), "",
           "【按页型分层】"]
    for k, a in report["by_page_class"].items():
        out.append(line(k, a))
    o = report["overall"]
    out += ["",
            f"金标 elastic 列 {o['elastic_gold']}，预测 {o['elastic_pred']}；"
            f"列数完全正确的页 {o['n_cols_exact_pages']}/{o['n_pages']}"]
    return "\n".join(out)
