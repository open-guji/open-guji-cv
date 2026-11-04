"""给中心库里现行的待审单补 `pending_reason`（A31，sheldon 2026-11-03 定：已有数据也改写，推不出写 unknown）。

    python scripts/zhengli/backfill_pending_reason.py -w <工作区> [--books vol20,vol56] [--write] [--report out.md]

每张单（数据目录 `feedback/lists/proofing/<文本号>/<章>.pending.json`）：
1. 取它出单那一版的产物包 `rev-<rev>`（republish 出单时存的，格号与单子一致）；没有就退回 ★main 包，并在报告里记下；
2. 用 `review/reasons.py` 判每格原因（与 republish 出单同一套判法），写 `pending_reason`（必有）、`pending_reason_detail`；
   产物里找不到的格只按单上字段判，判不出就是 `unknown`；
3. 只加这两个字段，别的字段（含 `cause`、`cls`）一字不动。

缺省只试跑：判完写报告，不改文件。`--write` 才写回数据目录；推中心库另跑 `guji db push -w <工作区>`（动线上数据，先问用户）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

CV = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CV))

from guji_manager.review.pending_reason import PendingReason, specs  # noqa: E402
from guji_manager.review.reasons import reasons_for_pending, stamp  # noqa: E402


def guji(*args, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "open_guji_cv.cli_v2", *map(str, args)], text=True,
                          capture_output=True, env={**os.environ, "PYTHONPATH": str(CV)}, **kw)


def data_dir(ws: Path) -> Path:
    """迁了中心库的工作区是数据目录，没迁的就是工作区自己（`core.workspace.data_root`，同 republish）。"""
    from open_guji_cv.core.workspace import data_root
    return data_root(ws)


def packs(ws: Path, book: str) -> list[tuple[bool, str]]:
    """(是否 ★main, 标签)。"""
    out = []
    for line in guji("products", "pack", "list", book, "-w", ws).stdout.splitlines():
        main = line.startswith("★")
        f = line.lstrip("★ ").split("\t")[0]
        if "products/" in f:
            out.append((main, f.rsplit("/", 1)[1]))
    return out


def fetch(ws: Path, book: str, label: str, to: Path) -> Path | None:
    p = guji("products", "pack", "fetch", book, "-w", ws, "--label", label, "--to", to)
    for cand in (to / book / book, to / book, to):
        if (cand / "seed_admit").exists():
            return cand.parent
    sys.stderr.write(f"  ⚠ {book} {label} 取包失败：{(p.stderr or p.stdout)[-300:]}\n")
    return None


def book_of(chapter: str, prefix: str) -> str:
    return f"{prefix}{int(chapter):02d}" if chapter.isdigit() else chapter


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--books", default="", help="只做这些册（逗号分隔），缺省全部")
    ap.add_argument("--book-prefix", default="vol", help="章号 → 册名的前缀（殿本 020 → vol20）")
    ap.add_argument("--data-dir", default="", help="数据目录，缺省 core.workspace.data_root")
    ap.add_argument("--write", action="store_true", help="写回数据目录（缺省只试跑）")
    ap.add_argument("--report", default="", help="报告 md 路径")
    ap.add_argument("--tmp", default="", help="取包的临时目录")
    a = ap.parse_args(argv)
    ws = Path(a.workspace).resolve()
    dd = Path(a.data_dir) if a.data_dir else data_dir(ws)
    gdb = ws / "output" / "glyph.db"
    only = {b.strip() for b in a.books.split(",") if b.strip()}
    tmp = Path(a.tmp or tempfile.mkdtemp(prefix="pr_backfill_"))
    lists = sorted((dd / "feedback" / "lists" / "proofing").glob("*/*.pending.json"))
    total: Counter = Counter()
    rows = []
    for f in lists:
        chap = f.name.split(".")[0]
        book = book_of(chap, a.book_prefix)
        if only and book not in only:
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        rev = doc.get("rev") or ""
        have = packs(ws, book)
        label, src = f"rev-{rev}", "rev"
        if (False, label) not in have and (True, label) not in have:
            mains = [l for m, l in have if m]
            label, src = (mains[0], "main") if mains else (None, "none")
        prod = fetch(ws, book, label, tmp / book) if label else None
        if prod is None:
            src = "none"
        res = reasons_for_pending(doc, prod or tmp / "_none", book, glyph_db=gdb)
        before = sum(1 for c in doc.get("cells", []) if c.get("pending_reason"))
        n = stamp(doc, res)
        total.update(n)
        rows.append((book, rev, src, label or "", len(doc.get("cells", [])), n.get("unknown", 0), before))
        print(f"{book}\t{rev}\t包 {src}:{label}\t{len(doc.get('cells', []))} 格\tunknown {n.get('unknown', 0)}", flush=True)
        if a.write:
            f.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = [f"# 待审单补 pending_reason（{'已写回' if a.write else '试跑，未写回'}）", "",
          f"数据目录 `{dd}`，{len(rows)} 张单，{sum(total.values())} 格；刻例数取 `{gdb}`。", "",
          "| 原因 | 码 | 去向 | 格数 |", "|---|---|---|---|"]
    for r, n in total.most_common():
        s = specs()[PendingReason(r)]
        md.append(f"| `{r}` {s.label} | {s.code} | {s.route.value} | {n} |")
    md += ["", "| 册 | 单 rev | 用包 | 标签 | 格数 | unknown | 原已有 |", "|---|---|---|---|---|---|---|"]
    md += [f"| {b} | {rv} | {s} | {l} | {n} | {u} | {bf} |" for b, rv, s, l, n, u, bf in rows]
    if a.report:
        Path(a.report).write_text("\n".join(md) + "\n", encoding="utf-8")
        print(f"报告 → {a.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
