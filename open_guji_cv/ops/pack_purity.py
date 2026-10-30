"""产物纯净性：存包时记一笔，标 main 时拦（A32 精校步骤前移 A2/A3，2026-10-30 sheldon 定）。

为什么：册 007 的 r5、r6 都是混合产物——切分步是 0.5.12 的代码跑的、下游是 0.5.17，从中途步续跑时
沿用了 main 包的切分（`domain/CV/经验.md`）。close-check 1a 按「在跑它的那个版本下新鲜就行」
（用户 10-19 定）判，这种包照样算新鲜；读者在上面投了票，换回纯净产物时票要重落、单子多出两轮。
停在 v0.1 等网站读者的册，单子一挂就是几周，这类事要在**标 main（随后自动重出线上单）之前**拦住。

两样：

- **代码一致**（A2）：用存包时装的 cv（就是跑这份产物的 cv）按严格口径（`code_ok=False`）看每步每页，
  过期原因是「代码或版本变了」的页 = 这一步的产物不是这份代码跑的 = 混合。参数、人裁、共享输入变了不算
  （那是正常的过期，不是混版本），沿 DAG 传下来的「上游过期」也不重复计。
- **图源一致**（A3）：产物 `_source.json` 记的页表 rev 要等于册 yaml 的 `source_rev`；
  `_raw_index.json` 里每页原图的 sha 要等于该版页表里的 sha（页表按版本只增不改，见 `datastore/sources.py`）。
  册 yaml 没钉 `source_rev` 的只记「未钉」，不算不纯（新书冷启动时还没有页表版本可钉）。

结果写进产物包 manifest 的 `purity`；`pack promote` 见 `pure: false` 先照标，在 main 指针里记 `impure` 并提醒。
**暂不拦**（2026-10-30 实测）：册 007 近期两份全册重放包（A24，cv 0.5.32.dev14）切分步（border_detect…cell_shrink）
和 5-b rare_candidates 都是旧代码跑的产物、只重跑了定字层，严格口径下 134 页全「不纯」。这是现行「只重跑该重跑的」做法，
拦不拦、怎么分层（切分层钉住、定字层跟新）等用户定（A32 方案 A1）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

#: 严格口径下「这一步自己的代码和产物对不上」的过期原因前缀（`Engine.stale_reason`）
CODE_REASONS = ("代码或版本变了", "代码或册配置变了")


def code_mixed(status: dict) -> dict[str, int]:
    """严格口径的 `Engine.status()` 结果 → {步: 代码对不上的页数}，没有就空。"""
    out: dict[str, int] = {}
    for sid, d in (status.get("steps") or {}).items():
        n = sum(1 for p in (d.get("pages") or {}).values()
                if p.get("status") == "stale" and not p.get("upstream_stale")
                and str(p.get("reason") or "").startswith(CODE_REASONS))
        if n:
            out[sid] = n
    return out


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def source_check(book_dir: Path, yaml_rev: int | None, table: dict | None = None,
                 raw_name=None) -> dict:
    """图源一致。`book_dir` 是 `<products>/<册>`；`table` 是册 yaml 钉的那版页表（取不到给 None，只比 rev）；
    `raw_name(page) -> 文件名` 把页表的页号对到 `_raw_index.json` 的键（缺省 `<页>.png`，同 BookSpec.raw_pattern 缺省）。

    → {status: ok|unpinned|unknown|mismatch, yaml_rev, products_rev, bad_pages: [...]}"""
    mark = _read_json(Path(book_dir) / "_source.json") or {}
    prod_rev = mark.get("rev")
    out = {"yaml_rev": yaml_rev, "products_rev": prod_rev, "bad_pages": []}
    if yaml_rev is None:
        return {**out, "status": "unpinned"}
    if prod_rev is None:
        return {**out, "status": "unknown"}
    if int(prod_rev) != int(yaml_rev):
        return {**out, "status": "mismatch"}
    if table is not None:
        idx = _read_json(Path(book_dir) / "_raw_index.json") or {}
        name = raw_name or (lambda pg: f"{pg}.png")
        bad = []
        for row in table.get("pages", []):
            rec = idx.get(name(row["page"]))
            if rec is not None and rec.get("sha256") != row.get("sha256"):
                bad.append(row["page"])
        if bad:
            return {**out, "status": "mismatch", "bad_pages": bad[:50]}
    return {**out, "status": "ok"}


def verdict(mixed: dict[str, int], src: dict) -> bool:
    return not mixed and src.get("status") not in ("mismatch", "unknown")


def check(book_id: str, products_root: Path, src=None) -> dict:
    """存包前的整册检查（只读）。要装着跑这份产物的 cv、本机有册 yaml 与数据目录；
    页表取不到（离线）就只比 rev。返回写进产物包 manifest 的 `purity`。"""
    from ..core import cv_version as CV
    from ..core.book import load_book
    from ..core.engine import Engine
    from ..core.pipeline import default_pipeline_id, load_pipeline

    book = load_book(book_id)
    eng = Engine(book, load_pipeline(default_pipeline_id(book)), log=lambda s: None)
    pages = book.resolve_pages("all")
    mixed = code_mixed(eng.status(pages=pages, code_ok=False))

    table = None
    yaml_rev = getattr(book, "source_rev", None)
    mark = _read_json(Path(products_root) / book_id / "_source.json") or {}
    if yaml_rev is not None and mark.get("book_id") and mark.get("vol"):
        try:
            from ..datastore import sources as S
            from ..datastore.client import WorkerSource
            table = S.read_table(src or WorkerSource(), mark["book_id"], mark["vol"], int(yaml_rev))
        except Exception:  # noqa: BLE001 —— 取不到页表只比 rev
            table = None
    srcc = source_check(Path(products_root) / book_id, yaml_rev, table,
                        raw_name=lambda pg: book.raw_path(pg).name)
    return {"pure": verdict(mixed, srcc), "code_mixed": mixed, "source": srcc,
            "pages": len(pages), "cv_version": CV.describe()[0],
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def describe(purity: dict | None) -> str:
    """一句中文：给 promote 的拒绝理由、存包时的打印用。"""
    if not purity:
        return "没有纯净性记录（老包或存包时没查）"
    if purity.get("error"):
        return f"纯净性没查成：{purity['error']}"
    bits = []
    if purity.get("code_mixed"):
        bits.append("代码对不上（混版本）：" + "、".join(f"{s} {n} 页" for s, n in purity["code_mixed"].items()))
    s = purity.get("source") or {}
    st = s.get("status")
    if st == "mismatch":
        bits.append(f"图源对不上：产物页表 r{s.get('products_rev')}，册 yaml source_rev {s.get('yaml_rev')}"
                    + (f"，原图 sha 不符 {len(s['bad_pages'])} 页（{s['bad_pages'][:5]}…）" if s.get("bad_pages") else ""))
    elif st == "unknown":
        bits.append("产物没记出自哪一版页表（_source.json 缺），原图来历不明")
    elif st == "unpinned":
        bits.append("册 yaml 没钉 source_rev（只记，不算不纯）")
    if purity.get("pure"):
        return "纯净" + (f"（{'；'.join(bits)}）" if bits else "")
    return "不纯：" + "；".join(bits)
