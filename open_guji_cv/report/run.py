# -*- coding: utf-8 -*-
"""9.3 整册跑批与汇总：`collate_book()` → JSON 报告。

设计见 `overview` 仓 `Step9-结果整理/04-与整理本对比校验.md` §三·5。
**JSON 是正本**，HTML 与控制台 tab 都从它渲染——两处各自重算必然漂移。

落点 `<workspace>/reports/<book>/collation_<YYYYMMDD-HHMM>.json`
（`core.workspace.reports_root`）。2026-09-13 起运行时数据全归 workspace，
原型写 `REPO/output/` 已违规。

## 报数纪律：按 channel 分层，不给单一总一致率

约 85% 的字是「与整理本一致」才放行的（vol01 dual 15,903 ＋ match_ref 1,748
/ 20,778）。拿同一份整理本再比一遍，这 85% 恒等——**是回声不是校验**。
所以 `summarize()` 出的是 `kind × channel` 的交叉表，
并把「人裁位上的差异」单列——那一栏才是真正要人看的。
"""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from ..core.book import load_book
from ..core.workspace import reports_root
from ..products.store import ProductStore
from .collate import Diff, collate_page
from .witness import Witness, load_witnesses


def collate_book(book: str, pages: list[int], witnesses: list[Witness],
                 store: ProductStore | None = None, progress=None) -> dict:
    """整册比对 → 可直接落盘的报告 dict。

    `progress`：`f(done, total, page)`，控制台/CLI 用来报进度；跑整册几十秒。
    """
    store = store or ProductStore()
    t0 = time.time()
    stale: list[str] = []
    pages_out: list[dict] = []
    all_diffs: list[Diff] = []
    all_cols: list[dict] = []
    unanchored: dict[str, list[int]] = {w.label: [] for w in witnesses}

    for n, page in enumerate(pages, 1):
        per = collate_page(store, book, page, witnesses, stale)
        rec: dict = {"page": page, "witnesses": {}}
        for label, res in per.items():
            if not res.anchored:
                unanchored[label].append(page)
            rec["witnesses"][label] = {
                "anchored": res.anchored, "note": res.note,
                "n_slots": res.n_slots, "n_text": res.n_text,
                "n_excluded": res.n_excluded, "n_unreadable": res.n_unreadable,
                "n_equal": res.n_equal,
                "counts": dict(Counter(d.kind for d in res.diffs)),
                "cols": dict(Counter(c.kind for c in res.cols)),
            }
            all_diffs.extend(res.diffs)
            all_cols.extend(asdict(c) for c in res.cols)
        pages_out.append(rec)
        if progress:
            progress(n, len(pages), page)

    return {
        "book": book,
        "built_at": time.strftime("%Y-%m-%d %H:%M"),
        "elapsed_s": round(time.time() - t0, 1),
        "pages": pages,
        "witnesses": [{"name": w.name, "label": w.label, "quality": w.quality,
                       "line_is_column": w.line_is_column,
                       "n_chars": len(w.text)} for w in witnesses],
        "unanchored": unanchored,
        "stale": sorted(set(stale)),
        "summary": summarize(all_diffs, all_cols, pages_out, witnesses),
        "page_stats": pages_out,
        "diffs": [asdict(d) for d in all_diffs],
        "cols": [c for c in all_cols if c["kind"] != "col.ok"],
    }


def summarize(diffs: list[Diff], cols: list[dict], pages_out: list[dict],
              witnesses: list[Witness]) -> dict:
    """册级汇总。**按 channel 分层**（见模块头），并单列人裁位上的差异。"""
    by_witness: dict[str, dict] = {}
    for w in witnesses:
        wd = [d for d in diffs if d.witness == w.label]
        kind_channel: dict[str, Counter] = {}
        for d in wd:
            kind_channel.setdefault(d.kind, Counter())[d.channel or "未放行"] += 1
        variant_pairs = Counter((d.char, d.ref) for d in wd if d.kind.startswith("variant"))
        n_equal = sum(p["witnesses"].get(w.label, {}).get("n_equal", 0) for p in pages_out)
        by_witness[w.label] = {
            "quality": w.quality,
            "n_equal": n_equal,
            "counts": dict(Counter(d.kind for d in wd)),
            "by_kind_channel": {k: dict(v) for k, v in kind_channel.items()},
            "variant_pairs": [[a, b, n] for (a, b), n in variant_pairs.most_common(40)],
            # 人裁过仍与整理本不同——要回答「整理本错还是人裁错」，09-06 vol01 有 7 处
            "human_disagree": [asdict(d) for d in wd
                               if d.human and d.kind.startswith(("sub.", "unreadable"))],
            "cols": dict(Counter(c["kind"] for c in cols if c["witness"] == w.label)),
        }
    return {"by_witness": by_witness, "n_diffs": len(diffs)}


def write_report(doc: dict, out: str | Path | None = None) -> Path:
    """落盘 → 返回路径。默认 `<workspace>/reports/<book>/collation_<stamp>.json`。"""
    if out is None:
        stamp = time.strftime("%Y%m%d-%H%M")
        out = reports_root() / doc["book"] / f"collation_{stamp}.json"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def body_pages(book: str, store: ProductStore | None = None) -> list[int]:
    """有 Step7 产物的页。**不再依赖 page-type 金标**（原型用
    `open-guji-dataset/page-type/items.jsonl` 筛正文页，那是测试集，
    09-13 起运行时不读 dataset，见 `core/workspace.py`）——锚不上的非正文页
    会自己落进 `unanchored`，不必先筛。"""
    store = store or ProductStore()
    bk = load_book(book)
    return [p for p in bk.resolve_pages("all") if store.exists(book, "seed_admit", f"p{p:04d}")]
