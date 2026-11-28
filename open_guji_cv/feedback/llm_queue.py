"""待裁清单：管线不调 API 后，文意 L3 没命中缓存的格怎么交给对话统一审（sheldon 2026-11-05）。

流程：
1. 管线照常跑：`groups/ctx_llm` 只查裁定库，没命中 → 弃权 `abstain:llm_pending`，并在 seed_admit 产物该格
   `evidence.group.solvers[*].ask` 里记下这一问（提示词版本、前后文窗口）；
2. `export`：扫一册或多册的 seed_admit 产物，把这些问题按（组、提示词版本、窗口）去重，写成 jsonl 待裁清单。
   每行：`{group, ver, l, r, members, prompt, cells[], ref}`；`prompt` 是该组提示词文件（`config/groups/<组>/prompt.md`）；
3. 对话读清单逐条判，按原行补上 `char`（组内字或「其他」）、`conf`（high/mid/low）、`why`（≤60 字），存成答案 jsonl；
4. `import`：答案写回裁定库（`feedback/rulings/<批次>.jsonl`，kind `ctx_ruling`，`model` 记 `--model`），
   之后 `guji db sync` 推中心库，再从 seed_admit 重放即命中缓存。

裁定库的键是（组、窗口哈希、提示词版本），与模型无关，所以对话给的裁定和以前 API 给的一样用。

    python -m open_guji_cv.feedback.llm_queue export vol20 vol21 --products <产物根> --out 待裁.jsonl
    python -m open_guji_cv.feedback.llm_queue import 答案.jsonl --model session --batch llm-session-20261105

第三步看图 `glyph_vis` 的离线 ask（只看字块图、写 `<feedback>/vis_glyph/`，与上面第四步文意 ask 互不相干）挂在同一命令组下，
实现与流程见 `feedback/vis_queue.py`：

    python -m open_guji_cv.feedback.llm_queue vis-export vol20 vol21 -w <工作区> --out 看图待判/ [--pages 1-30]
    python -m open_guji_cv.feedback.llm_queue vis-import 看图待判/answers.jsonl --name A24
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..core.decide_names import final_dir, final_page_dict

PENDING = "abstain:llm_pending"


def _cells(page_doc: dict):
    body = final_page_dict(page_doc, strict=False)
    for col in body.get("columns") or []:
        for r in col.get("chars") or []:
            yield r


def questions_of_page(page_doc: dict) -> list[dict]:
    """一页 seed_admit 产物 → 这页记下的待裁问题（未去重）。"""
    out = []
    for r in _cells(page_doc):
        g = ((r.get("evidence") or {}).get("group") or {})
        for t in g.get("solvers") or []:
            ask = t.get("ask")
            if not ask or (t.get("why") != PENDING and not t.get("ask_rf")):   # ask_rf：ruling_first 组 L2 小头给的字也交对话核
                continue
            out.append({"group": g.get("id"), "ver": ask.get("ver"), "l": ask.get("l") or "", "r": ask.get("r") or "",
                        "cell": r.get("id"), "cur": r.get("char")})
    return out


def collect(page_files) -> list[dict]:
    """多页 → 按（组、提示词版本、窗口）去重的待裁清单。"""
    from ..groups.registry import FLOW_GROUPS
    rows: dict[tuple, dict] = {}
    for f in page_files:
        try:
            doc = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for q in questions_of_page(doc):
            k = (q["group"], q["ver"], q["l"], q["r"])
            row = rows.get(k)
            if row is None:
                spec = FLOW_GROUPS.get(q["group"])
                row = rows[k] = {"group": q["group"], "ver": q["ver"], "l": q["l"], "r": q["r"],
                                 "members": sorted(spec.members) if spec else [],
                                 "prompt": f"config/groups/{q['group']}/prompt.md", "cells": []}
                if str(q["ver"] or "").startswith("vis"):       # 看图判（groups/vis_llm）：提示词在代码里，要对着字块图判
                    row.update({"vis": True, "prompt": "open_guji_cv/groups/vis_llm.py:SYSTEM",
                                "image": "按 cells 的格号取字块图（research/a24/r4/dump_patches.py）；答案 ver 原样带回"})
            row["cells"].append(q["cell"])
    return sorted(rows.values(), key=lambda x: (x["group"] or "", x["cells"][0] or ""))


def import_answers(rows, *, model: str, batch: str | None = None, store=None) -> dict:
    """答案行（导出行＋char/conf/why）→ 写进裁定库。→ {written, skipped}。"""
    from .rulings import OTHER, RulingStore
    st = store if store is not None else RulingStore()
    if batch:
        st._batch = batch
    n = skip = 0
    for a in rows:
        ch, conf = a.get("char"), a.get("conf")
        mem = set(a.get("members") or [])
        if conf not in ("high", "mid", "low") or not ch or (mem and ch not in mem and ch != OTHER):
            skip += 1
            continue
        st.put(a["group"], a["ver"], a.get("l") or "", a.get("r") or "", char=ch, conf=conf, why=a.get("why") or "",
               model=model, cell=(a.get("cells") or [None])[0], pending_reason=a.get("pending_reason"))
        n += 1
    return {"written": n, "skipped": skip}


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="从 seed_admit 产物导出待裁清单")
    e.add_argument("books", nargs="+", help="册号（产物根下的子目录名）")
    e.add_argument("--products", default="", help="产物根；缺省本机产物根")
    e.add_argument("--out", required=True)
    i = sub.add_parser("import", help="答案写回裁定库")
    i.add_argument("answers")
    i.add_argument("--model", default="session", help="记进裁定的 model 字段（谁判的）")
    i.add_argument("--batch", default=None, help="裁定批次名（feedback/rulings/<批次>.jsonl），缺省 llm-ctx-<日期>")
    ve = sub.add_parser("vis-export", help="第三步 glyph_vis 的 pending ask → 题图 PNG＋manifest（feedback/vis_queue）")
    ve.add_argument("books", nargs="+", help="册号")
    ve.add_argument("-w", "--workspace", default=None, help="书的工作区（缺省读 GUJI_WORKSPACE）")
    ve.add_argument("--products", default="", help="产物根；缺省本机产物根")
    ve.add_argument("--pages", default=None, help="只扫这些页，如 1-30,45；缺省全册（只能配一册用）")
    ve.add_argument("--out", required=True, help="输出目录（img/、manifest.jsonl、prompt.md）")
    ve.add_argument("--overwrite", action="store_true", help="输出目录已有 manifest 时覆盖（旧答案没导入会对不上题号）")
    vi = sub.add_parser("vis-import", help="对话看图判的答案写回 vis_glyph 缓存（只写本机）")
    vi.add_argument("answers")
    vi.add_argument("--name", required=True, help="判题人名，写成 model=session:<名>")
    vi.add_argument("--manifest", default=None, help="导出时的 manifest；缺省答案文件同目录的 manifest.jsonl")
    vi.add_argument("--batch", default=None, help="缓存批次名（<feedback>/vis_glyph/<批次>.jsonl），缺省 glyph-vis-session-<日期>")
    vi.add_argument("-w", "--workspace", default=None, help="书的工作区（定 feedback 根；缺省读 GUJI_WORKSPACE）")
    a = ap.parse_args(argv)
    if a.cmd in ("vis-export", "vis-import"):
        return _vis_main(a)
    if a.cmd == "export":
        if a.products:
            root = Path(a.products)
        else:
            from ..products.store import default_products_root
            root = default_products_root()
        files = [f for b in a.books for f in sorted(((final_dir(root, b) or root / b / "seed_admit")).glob("p*.json"))]
        rows = collect(files)
        Path(a.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"{len(files)} 页 → 待裁 {len(rows)} 问（{sum(len(r['cells']) for r in rows)} 格）→ {a.out}", file=sys.stderr)
    else:
        res = import_answers(_read_jsonl(Path(a.answers)), model=a.model, batch=a.batch)
        print(json.dumps(res, ensure_ascii=False))
    return 0


def _vis_main(a) -> int:
    import os

    from . import vis_queue as VQ
    if a.workspace:
        os.environ["GUJI_WORKSPACE"] = str(Path(a.workspace).expanduser().resolve())
    elif os.environ.get("GUJI_WORKSPACE"):
        print(f"  未给 -w，用 GUJI_WORKSPACE={os.environ['GUJI_WORKSPACE']}", file=sys.stderr)
    if a.cmd == "vis-export":
        out = Path(a.out)
        if (out / VQ.MANIFEST).exists() and not a.overwrite:
            print(f"{out / VQ.MANIFEST} 已有：上一批答案导入了再导，或加 --overwrite", file=sys.stderr)
            return 2
        pages = VQ.parse_pages(a.pages)
        if pages is not None and len(a.books) > 1:
            print("--pages 只能配一册用", file=sys.stderr)
            return 2
        rows, pngs, rep = VQ.collect([(VQ.book_ctx(b, a.products or None), pages) for b in a.books])
        VQ.write_export(out, rows, pngs)
        print(json.dumps(rep, ensure_ascii=False), file=sys.stderr)
        print(f"待判 {rep['questions']} 题（{rep['cells']} 格）→ {out}；按 {out / VQ.PROMPT_FILE} 判完存 answers.jsonl，"
              f"再 vis-import", file=sys.stderr)
        return 0
    ans = Path(a.answers)
    man = Path(a.manifest) if a.manifest else ans.parent / VQ.MANIFEST
    if not man.exists():
        print(f"找不到 manifest：{man}（用 --manifest 指定）", file=sys.stderr)
        return 2
    rep = VQ.import_answers(VQ.read_jsonl(ans), VQ.read_jsonl(man), name=a.name, batch=a.batch)
    print(json.dumps(rep, ensure_ascii=False))
    if rep["not_accepted"]:
        print(f"⚠ 本书 glyph_vis.accept_models 没列 {rep['model']}：重跑不会命中，先在书配置里加上", file=sys.stderr)
    if rep["written"] or rep["updated"]:
        print("缓存内容不进指纹：要从 glyph_vis 起 force 重跑才生效，如 "
              "`guji-cv pipeline <管线> <册> -w <工作区> --from glyph_vis --force`（只写了本机，没推中心库）", file=sys.stderr)
    return 1 if rep["rejected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
