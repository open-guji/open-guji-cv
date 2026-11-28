"""1a 页面预检（异常页）最小 benchmark（CV1，2026-11-28，四大步验收 L2／S11）。

    python -m open_guji_cv.eval.survey_bench --gold <page-survey items.jsonl> [--out report.json]

**只跑 `page_survey` 的尺寸判据**（`steps.page_survey.survey_book`，与管线同一份代码）。上游输入冻结在金标里：
每条是一页的 `input: {width, height}`（原图像素尺寸，不需要图），按册聚成尺寸表后量一遍，比 `expected.odd`
与 `expected.kind`。造一个只含文件头的小 PNG 目录喂给 `survey_book`，不动判据代码、不碰指纹。

条目（统一信封，`page-survey/items.jsonl`）：
`{"id": "sj05:1", "anchor": {"book": "sj05", "page": 1}, "input": {"width": 2576, "height": 2668},
  "expected": {"odd": true, "kind": "双叶横拼(1×2)"}, "label_origin": "human|rule", "status": "active"}`

主指标：异常页召回、精确率、形态（kind）对率。护栏（必须为 0）：**金标正常页被判异常**（`false_alarm`，
闸会拦掉一页好页）。`label_origin: rule` 的条目是「按现行判据快照的预期」，只能当回归（翻转清单），不是人核金标；
报告里 human／rule 分开报，只有 human 的数才算准确率。
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import defaultdict
from pathlib import Path

from .layout_bench import series_of


class _FrozenBook:
    """`survey_book` 只用到 `raw_dir`、`raw_pattern`、`all_pages()`。"""

    def __init__(self, raw_dir: Path, pages: list[int]):
        self.raw_dir, self.raw_pattern, self._pages = raw_dir, "{page}.png", pages

    def all_pages(self) -> list[int]:
        return list(self._pages)


def _write_headers(root: Path, sizes: dict[int, tuple[int, int]]) -> None:
    """每页写一张 w×h 的全白 1 位 PNG（压缩后几百字节）；`page_survey` 只读文件头。"""
    from PIL import Image
    root.mkdir(parents=True, exist_ok=True)
    for pg, (w, h) in sizes.items():
        Image.new("1", (w, h), 1).save(root / f"{pg}.png")


def run(items: list[dict]) -> dict:
    from ..steps.page_survey import survey_book
    by_book: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        if it.get("status", "active") == "active":
            by_book[it["anchor"]["book"]].append(it)
    rows, flips, skipped = [], [], []
    with tempfile.TemporaryDirectory(prefix="survey_bench_") as td:
        for book, its in sorted(by_book.items()):
            sizes = {int(i["anchor"]["page"]): (int(i["input"]["width"]), int(i["input"]["height"])) for i in its}
            root = Path(td) / book
            _write_headers(root, sizes)
            res = {s.page: s for s in survey_book(_FrozenBook(root, sorted(sizes)))}
            if not res:
                skipped.append(book)            # 页数 < 3，判据不启用
                continue
            for i in its:
                pg = int(i["anchor"]["page"])
                s = res[pg]
                e = i["expected"]
                rows.append({"key": f"{book}:{pg}", "book": book, "series": series_of(book),
                             "origin": i.get("label_origin", "human"),
                             "gold_odd": bool(e["odd"]), "pred_odd": s.odd,
                             "gold_kind": e.get("kind"), "pred_kind": s.kind})
                if bool(e["odd"]) != s.odd or (e["odd"] and e.get("kind") != s.kind):
                    flips.append(rows[-1]["key"])
    return {"rows": rows, "flips": flips, "skipped_books": skipped, "summary": summarize(rows)}


def summarize(rows: list[dict]) -> dict:
    out: dict = {}
    for origin in ("human", "rule"):
        for ser in [None] + sorted({r["series"] for r in rows if r["series"]}):
            rs = [r for r in rows if r["origin"] == origin and (ser is None or r["series"] == ser)]
            if not rs:
                continue
            tp = sum(r["gold_odd"] and r["pred_odd"] for r in rs)
            fn = sum(r["gold_odd"] and not r["pred_odd"] for r in rs)
            fp = sum((not r["gold_odd"]) and r["pred_odd"] for r in rs)
            kind_ok = sum(r["gold_odd"] and r["pred_odd"] and r["gold_kind"] == r["pred_kind"] for r in rs)
            out[f"{origin}/{ser or '全部'}"] = {
                "pages": len(rs), "gold_odd": tp + fn, "recall": tp / (tp + fn) if tp + fn else None,
                "precision": tp / (tp + fp) if tp + fp else None,
                "kind_acc": kind_ok / tp if tp else None, "false_alarm": fp}
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    items = [json.loads(l) for l in Path(a.gold).read_text(encoding="utf-8").splitlines() if l.strip()]
    rep = run(items)
    txt = json.dumps(rep, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(json.dumps({"summary": rep["summary"], "flips": rep["flips"], "skipped_books": rep["skipped_books"]},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
