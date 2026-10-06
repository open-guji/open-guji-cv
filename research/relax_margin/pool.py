# -*- coding: utf-8 -*-
"""D 高置信落审放宽候选（2026-09-28，任务书 item 1–2）：捞「库 top1 置信度高、只因上下文
margin 不足而落审」的格，按库置信度分档，量人裁一致率与整理本一致率。

读的是**关掉人裁通道重跑**的 `seed_admit` 产物（`use_human_verdicts=false`）——
不关的话人裁过的格已经走 `human` 通道放行了，池子里恰好少掉有真值的那一批。

    GUJI_WORKSPACE=<ws> GUJI_PRODUCTS_DIR=<沙箱> GUJI_GLYPH_DB=<沙箱库> \\
      .venv/bin/python research/relax_margin/pool.py vol04 \\
        --admit <关人裁重跑的 seed_admit 目录> --out pool_vol04.jsonl

每格一行 JSON：id、库候选、Step6 ranked、整理本对齐、疑问、各项排除标记、人裁真值。
分档表由 `bins.py` 读这些 jsonl 出。
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MARGIN_DOUBT = "上下文 margin 不足"


def _load(path: Path) -> dict:
    x = json.loads(path.read_text(encoding="utf-8"))
    return next(iter(x.values()))


def _by_id(prod: dict) -> dict:
    out = {}
    for c in prod.get("columns") or []:
        for r in c.get("chars", []):
            out[r["id"]] = r
    for r in prod.get("chars") or []:
        out[r["id"]] = r
    return out


def human_truth(book: str, bind: bool = True) -> dict[str, str]:
    """人裁真值 `{裸 id: 字}`：事件侧（`human_chars`，含绑定）优先，字形库人裁补缺。
    与 `seed_admit` 人裁通道同一份来源。"""
    from open_guji_cv.feedback.bindings import rebind_library_shapes
    from open_guji_cv.feedback.lookup import human_chars
    from open_guji_cv.steps.seed_admit import SeedAdmitParams, _human_shapes
    p = SeedAdmitParams()
    shapes = _human_shapes(p.db_path)
    shapes = {k: v for k, v in shapes.items() if k.startswith(f"{book}:")}
    if shapes and bind:
        shapes = rebind_library_shapes(book, shapes)
    texts = human_chars(book, bind=bind)
    return {**shapes, **texts}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book")
    ap.add_argument("--admit", required=True, help="关人裁重跑的 seed_admit 产物目录")
    ap.add_argument("--out", required=True)
    ap.add_argument("--nobind", action="store_true",
                    help="人裁不过绑定表、按编号直取（vol02 老事件全是 unanchored，绑定后只剩 2 条）")
    a = ap.parse_args()

    from open_guji_cv.clustering.confusable import partners
    from open_guji_cv.clustering.iron_evidence import _CONFIG as IRON_CFG
    from open_guji_cv.clustering.seeding import NEAR_FORM_CHARS
    from open_guji_cv.clustering.variants import VariantMap
    from open_guji_cv.core.workspace import products_root
    from open_guji_cv.utils.ji_yi_si import FAMILY as JYS

    vm = VariantMap.load(None)
    part = partners()
    extra: dict[str, set[str]] = {}
    try:
        cfg = json.loads(Path(IRON_CFG).read_text(encoding="utf-8"))
        for a_, b_ in cfg.get("extra_confusable_pairs") or []:
            extra.setdefault(a_, set()).add(b_)
            extra.setdefault(b_, set()).add(a_)
    except Exception:
        pass

    truth = human_truth(a.book, bind=not a.nobind)
    pd = Path(products_root()) / a.book
    n_all = n_pool = 0
    with open(a.out, "w", encoding="utf-8") as fo:
        for f in sorted(glob.glob(f"{a.admit}/p*.json")):
            name = Path(f).name
            adm = _by_id(_load(Path(f)))
            try:
                gm = _by_id(_load(pd / "glyph_match" / name))
            except FileNotFoundError:
                continue
            try:
                cd = _by_id(_load(pd / "context_decide" / name))
            except FileNotFoundError:
                cd = {}
            try:
                ar_raw = _load(pd / "align_ref" / name)
                anchored = bool(ar_raw.get("anchored"))
                ar = _by_id(ar_raw) if anchored else {}
            except FileNotFoundError:
                anchored, ar = False, {}
            for iid, r in adm.items():
                n_all += 1
                if r["admit"] or not any(MARGIN_DOUBT in d for d in r["doubts"]):
                    continue
                m = gm.get(iid) or {}
                cands = m.get("candidates") or []
                if not cands:
                    continue
                n_pool += 1
                top, c1 = cands[0]
                c2 = cands[1][1] if len(cands) > 1 else 0.0
                d = cd.get(iid) or {}
                ranked = d.get("ranked") or []
                al = ar.get(iid) or {}
                ach = al.get("align_char")
                others = {c for c, _ in cands[1:]}
                conf = (top in NEAR_FORM_CHARS
                        or bool(part.get(top, frozenset()) & others)
                        or bool(extra.get(top, set()) & others))
                h = truth.get(iid)
                rec = {
                    "id": iid, "book": a.book,
                    "top": top, "c1": c1, "c2": c2, "gap": round(c1 - c2, 4),
                    "cands": cands[:5],
                    "verdict": m.get("verdict"), "guard": m.get("guard"),
                    "wmax": m.get("wmax"),
                    "ctx_top": ranked[0][0] if ranked else None,
                    "ctx_margin": d.get("margin"),
                    "ctx_top_is_lib": bool(ranked) and vm.semantic(ranked[0][0]) == vm.semantic(top),
                    "anchored": anchored,
                    "align_char": ach, "align_op": al.get("align_op"),
                    "ref_agree": (ach is not None and vm.semantic(ach) == vm.semantic(top)),
                    "doubts": r["doubts"],
                    "jys": top in JYS or (ach in JYS if ach else False),
                    "confusable": conf,
                    "conf_any": (top in NEAR_FORM_CHARS or top in part or top in extra),
                    "human": h,
                    "human_ok": (None if h is None else vm.semantic(h) == vm.semantic(top)),
                    "human_exact": (None if h is None else h == top),
                    "sub": r.get("sub"),
                }
                fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"{a.book}: 全部 {n_all} 格，margin 不足落审 {n_pool} 格，人裁 {len(truth)} 条", file=sys.stderr)


if __name__ == "__main__":
    main()
