# -*- coding: utf-8 -*-
"""锚点对账（F3，overview#398）：CV 产物 → guji-page → lines.md，再数 lines.md 推锚点，与 CV 格 id 逐位比。

只读产物。两套「数出来的锚点」都量：
- `legacy`：`scripts/test_vol02_extract.py::build_anchor_map` 原样（book-text wip/siku-vol02 的 punct/entity 就是它出的）；
- `fixed`：`formats/guji_format.derive_anchors`（抬头跳 0、`:zi` 算一字、单边夹注）。

对不上的位按**列内第一处错位的成因**归类（一列里一旦错位，后面跟着错；归到引起它的那一处）：

| 类 | 判据 |
|---|---|
| 空列 | 本页此列之前有 Step3 列没出 md 行（列里没字），列号整体前移 |
| 抬头 | 抬头列（raised>0）格号错（legacy 抬头从 −r 数到 0；或抬头格本身是排除格，md 照写 `^`） |
| 行首排除/留白 | 列首几格是排除格（墨污）或留白但没折进 `lead_blank`，md 不留痕 |
| 列中空格 | 列中间有 blank 格（版式空位），md 不留痕 |
| 列中排除格 | 列中间有排除格（非字），md 不留痕 |
| 夹注 | 夹注段里或夹注之后格号/子列错（左右不等长、单边夹注、夹注格号与正文格号口径不同） |
| 组字 | `:zi[…]` 被 legacy 当成多字 |
| 记号误数 | legacy 把夹注里的 `[[]]`、`□{guess=…}` 逐个符号当字数（`<…>` 内部不再分单元），本页此后字流整体错位 |
| Step3/7 不同步 | 该列在导出时报了 Step3/Step7 对不上（产物过期），或 Step3 有格而 Step7 没有记录 |
| 其他 | 以上都不是（逐条列出） |

    python scripts/reconcile_lines_anchors.py --products <root> --book vol02 --out report.json [--pages 3-20]
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.formats import guji_format as gf  # noqa: E402
from open_guji_cv.formats import guji_page as gp  # noqa: E402
from open_guji_cv.formats.guji_page_cv import export_page  # noqa: E402


def _legacy_builder():
    spec = importlib.util.spec_from_file_location("_tv02", REPO / "scripts" / "test_vol02_extract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.build_anchor_map


def _pages_in(products: Path, book: str) -> list[int]:
    d = products / book / "seed_admit"
    return sorted(int(p.stem[1:]) for p in d.glob("p*.json"))


def _structure(page: dict):
    """每列：CV 格号 → 什么格（字 / blank / excluded），供归因。"""
    by_col: dict[str, dict[tuple[int, str], str]] = collections.defaultdict(dict)
    for g in page["glyphs"]:
        a = gf.parse_anchor(gf.anchor_of(g["cv_id"]))
        by_col[g["col"]][(a[2], a[3])] = "char"
    for m in page["marks"]:
        if m.get("kind") in ("blank", "excluded") and m.get("col"):
            by_col[m["col"]].setdefault((m["slot"], ""), m["kind"])
    return by_col


def align(text: list[str], chars: list[str], anchors: list[str]) -> list[str | None]:
    """数出来的字流与 text 不等长（legacy 把记号当字数）时，按字对齐；对不上的位给 None。"""
    if len(chars) == len(text):
        return list(anchors)
    import difflib
    out: list[str | None] = [None] * len(text)
    sm = difflib.SequenceMatcher(None, text, chars, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k] = anchors[j1 + k]
    return out


def classify(page: dict, derived: list[str | None]) -> list[dict]:
    """一页：逐字比 CV 锚点与数出来的锚点（已按字对齐），返回对不上的位（带成因）。"""
    text = page["text"]
    stale_cols = {int(m.group(1)) for w in page.get("warnings", []) for m in [re.search(r"col(\d+):", w)] if m}
    at = gf._glyph_at(page)
    struct = _structure(page)
    cols = [c for _, c in gp.iter_columns(page)]
    empty_before: dict[str, int] = {}
    n_empty = 0
    for c in cols:
        empty_before[c["id"]] = n_empty
        if not any(r["text"][1] > r["text"][0] for r in c["runs"]):
            n_empty += 1
    col_of = {c["id"]: c for c in cols}
    zi_pos = {z["i"] for z in page.get("zi", [])}

    bad = []
    cause_in_col: dict[str, str] = {}
    prev_in_col: dict[str, tuple] = {}
    for i in range(len(text)):
        g = at.get(i)
        if g is None or not g.get("cv_id"):
            continue
        cv = gf.anchor_of(g["cv_id"])
        dv = derived[i] if i < len(derived) else None
        cp, cc, cs, csub = gf.parse_anchor(cv)
        col = col_of[g["col"]]
        prev = prev_in_col.get(g["col"])
        prev_in_col[g["col"]] = (cs, csub, g["lane"])
        if dv == cv:
            continue
        cause = None
        if dv is None:
            cause = "记号误数"
        elif cc in stale_cols:
            cause = "Step3/7 不同步"
        else:
            dp, dc, ds, dsub = gf.parse_anchor(dv)
            if dp != cp:
                cause = "拆页"
            elif dc != cc:
                cause = "空列" if empty_before[g["col"]] else "其他"
            elif g["col"] in cause_in_col:
                cause = cause_in_col[g["col"]]
            else:
                st = struct[g["col"]]
                lead = [k for k in sorted(st) if k[0] < cs]
                if i in zi_pos:
                    cause = "组字"
                elif prev is None and cs > 1 and not col.get("raised") and not lead:
                    cause = "Step3/7 不同步"            # 列首前面的格 Step7 没有记录（page_slots 不收）
                elif prev is None:                       # 列首字就错
                    if col.get("raised"):
                        cause = "抬头"
                    elif any(st[k] in ("excluded", "blank") for k in lead):
                        cause = "行首排除/留白"
                    elif g["lane"] != "main":
                        cause = "夹注"
                    else:
                        cause = "其他"
                else:
                    ps, psub, plane = prev
                    gap = [k for k in sorted(st) if ps < k[0] < cs and not k[1]]
                    kinds = {st[k] for k in gap}
                    if g["lane"] != "main" or plane != "main":
                        cause = "夹注"
                    elif "blank" in kinds:
                        cause = "列中空格"
                    elif "excluded" in kinds:
                        cause = "列中排除格"
                    elif col.get("raised") and cs > 0:
                        cause = "抬头"
                    else:
                        cause = "其他"
                cause_in_col[g["col"]] = cause
        bad.append({"i": i, "cv": cv, "derived": dv, "char": text[i], "cause": cause})
    return bad


def run(products: Path, book: str, pages: list[int], meta: dict) -> dict:
    legacy = _legacy_builder()
    rep = {"book": book, "pages": 0, "chars": 0, "skipped": [], "legacy": collections.Counter(),
           "fixed": collections.Counter(), "legacy_bad": 0, "fixed_bad": 0, "examples": {"legacy": {}, "fixed": {}},
           "per_page": []}
    for p in pages:
        m = json.loads(json.dumps(meta))
        m.setdefault("page", {})["index"] = p
        try:
            page = export_page(products, book, p, m)
        except Exception as e:  # noqa: BLE001 — 缺产物的页记下来跳过
            rep["skipped"].append(f"p{p}: {type(e).__name__}: {e}")
            continue
        md = gp.to_guji_markdown(page)
        lc, la = legacy(md)
        leg = align(page["text"], lc, [la[k] for k in sorted(la)])
        dfx = gf.derive_anchors(md)
        fix = align(page["text"], [d["t"]["t"] or "〓" for d in dfx], [d["a"] for d in dfx])
        rep["pages"] += 1
        rep["chars"] += len(page["text"])
        row = {"page": p, "chars": len(page["text"])}
        for name, der in (("legacy", leg), ("fixed", fix)):
            bad = classify(page, der)
            rep[f"{name}_bad"] += len(bad)
            row[name] = len(bad)
            for b in bad:
                rep[name][b["cause"]] += 1
                ex = rep["examples"][name].setdefault(b["cause"], [])
                if len(ex) < 6:
                    ex.append({"page": p, **{k: b[k] for k in ("cv", "derived", "char")}})
        rep["per_page"].append(row)
    rep["legacy"] = dict(rep["legacy"].most_common())
    rep["fixed"] = dict(rep["fixed"].most_common())
    return rep


def _parse_pages(s: str | None, products: Path, book: str) -> list[int]:
    if not s:
        return _pages_in(products, book)
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += range(int(a), int(b) + 1)
        elif part.strip():
            out.append(int(part))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--products", required=True)
    ap.add_argument("--book", required=True)
    ap.add_argument("--meta", required=True, help="同 export_guji_page.py --meta（只用 defaults）")
    ap.add_argument("--pages", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    products = Path(a.products)
    meta = json.loads(Path(a.meta).read_text(encoding="utf-8")).get("defaults", {})
    rep = run(products, a.book, _parse_pages(a.pages, products, a.book), meta)
    Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{a.book}: {rep['pages']} 页 {rep['chars']} 字；legacy 错 {rep['legacy_bad']} 位 {rep['legacy']}；"
          f"fixed 错 {rep['fixed_bad']} 位 {rep['fixed']}；跳过 {len(rep['skipped'])} 页")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
