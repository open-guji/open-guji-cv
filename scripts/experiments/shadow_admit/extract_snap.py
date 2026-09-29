# -*- coding: utf-8 -*-
"""影子放行模型·从快照产物抽**全书**信号（不读图、不跑 OCR）——给 vol03 这种只有 snap 分支产物的册用。

    GUJI_WORKSPACE=<临时工作区：软链原工作区 + products/<book> 指到快照> PYTHONPATH=. \
        ~/shadow-venv/bin/python scripts/experiments/shadow_admit/extract_snap.py vol03 \
        --snap-ts 2026-09-28T17:08:15Z --out <scratch>/signals_all.jsonl

与 `extract.py` + `augment.py` 的差别（2026-09-29，D 道 vol03 影子试跑，overview#269）：
- **没有 OCR**：vol03 快照里没有 `ocr_candidates` 产物（seed_admit evidence.ocr 全空），`ocr_missing=1`、其余 OCR 列置缺省值；
- **不算小笔画判别器**：要先生成字块缓存（`char_patch`），本轮不碰 cache，`disc_*` 置缺省值；
- **库信号不重算**：extract.py 对「库里有自身人裁实例」的格会读图重算并摘自身，这里读不到图块缓存、做不了，
  只打 `in_lib_self` 标记，评测时分开报；
- **标签口径**（任务卡定）：人裁经绑定表（`feedback/bindings.py`）落到现行编号，后到覆盖；
  `seg_defect` / `not_a_char` 不当字标签；己已巳一族合并成「己」一个标签（候选、现字、整理本字一并合并）；
  `via=doubt:occluded`（印章遮挡）的格打 `occluded=1`，单独报。
- 一次出齐 v1 + v2（整理本关系 / 对齐可靠度）信号，外加分拆用的元数据（doubts、slot、admit、kind、批次）。
只读产物与事件，不写 products/、不写事件。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

JYS = set("己已巳")


def J(c):
    return "己" if c in JYS else c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("--snap-ts", required=True, help="快照时刻（UTC ISO）：此后的裁决不可能影响产物，用来分「干净标签」")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    import yaml
    from open_guji_cv.clustering.confusable import partners as _partners
    from open_guji_cv.clustering.variants import VariantMap
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.core.workspace import feedback_root, glyph_store_path, workspace_root
    from open_guji_cv.feedback.bindings import book_bindings, usable
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.report.slots import page_slots

    book = a.book
    st, vm, partners = ProductStore(), VariantMap.load(), _partners()
    repo = Path(__file__).resolve().parents[3]

    # ── 标签：与 feedback.lookup.human_chars 同一条路（时间序、后到覆盖、过绑定表、认撤下标记），
    #    但保留 v / via，按任务卡口径分流
    gs = glyph_store_path()
    stale: dict[str, str] = {}
    for l in open(gs / "admissions.jsonl", encoding="utf-8"):
        r = json.loads(l)
        prov = r.get("provenance") or ""
        if prov.startswith("human_stale_"):
            iid = r["instance_id"]
            key = iid[3:] if iid.startswith("v2:") else iid
            if key.startswith(book + ":"):
                stale[key] = prov.rsplit("_", 1)[-1]
    sv = feedback_root() / "lists" / "stale_verdicts.tsv"
    if sv.exists():
        for l in sv.read_text(encoding="utf-8").splitlines():
            p = l.split("\t")
            if len(p) >= 2 and p[0].startswith(book + ":"):
                stale[p[0]] = p[1]
    log = EventLog()
    bound = book_bindings(book, log)
    evs = sorted((e for e in log.iter_all() if e.kind == "confirm" and e.target.unit == "cell"
                  and e.target.key.startswith(book + ":") and e.target.step == "seed_admit"),
                 key=lambda e: (e.ts, e.batch, e.seq))
    verdict: dict[str, dict] = {}
    n_unbound = n_stale = 0
    for e in evs:
        p = e.payload or {}
        cut = stale.get(e.target.key)
        if cut and e.ts.replace("-", "").replace(":", "")[:len(cut)] <= cut:
            n_stale += 1
            continue
        key = usable(bound.get(e.id)) if e.id in bound else e.target.key
        if key is None:
            n_unbound += 1
            continue
        verdict[key] = {"v": p.get("v"), "shape": p.get("shape"), "via": p.get("via"), "ts": e.ts, "batch": e.batch}
    print(f"裁决事件 {len(evs)}；撤下作废 {n_stale}；绑定不采信 {n_unbound}；落格 {len(verdict)}", file=sys.stderr)

    # ── 字形库人裁实例（human_n）：摘快照之后才入库的
    inst_status = {}
    for f in (gs / "instances").glob("*.jsonl"):
        for l in open(f, encoding="utf-8"):
            r = json.loads(l)
            inst_status[r["instance_id"]] = r.get("label_status") or ""
    human_ids: dict[str, set[str]] = defaultdict(set)
    for l in open(gs / "exemplars.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if inst_status.get(r["instance_id"]) == "human" and r["added_at"] < a.snap_ts.replace("Z", "+00:00"):
            human_ids[J(r["char"])].add(r["instance_id"].replace("v2:", ""))
    lib_self = {i for s in human_ids.values() for i in s if i.startswith(book + ":")}

    jiajie = set()
    for l in (repo / "config/dicts/jiajie.tsv").read_text(encoding="utf-8").splitlines():
        if l and not l.startswith("#"):
            x, y = l.split("\t")[:2]
            jiajie |= {(x, y), (y, x)}
    conv = set()
    y = yaml.safe_load((workspace_root() / "books" / f"{book}.yaml").read_text(encoding="utf-8"))
    for c in y.get("char_conventions") or []:
        x, z = c["pair"]
        conv |= {(x, z), (z, x)}

    pages = sorted(int(p.stem[1:]) for p in (st.root / book / "seed_admit").glob("p*.json"))
    out = open(a.out, "w", encoding="utf-8")
    n_cells = n_rows = n_unc = 0
    for pg in pages:
        key = page_key(pg)
        gm = {r["id"]: r for c in st.read(book, "glyph_match", key, "glyph_match").model_dump()["columns"]
              for r in (c.get("chars") or [])}
        rc = {r["id"]: r for c in st.read(book, "rare_candidates", key, "rare_candidates").model_dump()["columns"]
              for r in (c.get("chars") or [])}
        al = {r["id"]: r for r in st.read(book, "align_ref", key, "align_ref").model_dump()["chars"]}
        sa = {r["id"]: r for c in st.read(book, "seed_admit", key, "seed_admit").model_dump()["columns"]
              for r in (c.get("chars") or [])}
        slots = [s for s in page_slots(st, book, pg) if s.is_text]
        seq = [s.id for s in slots]
        ops = [(al.get(i) or {}).get("align_op") for i in seq]
        for k, s in enumerate(slots):
            win = [o for j, o in enumerate(ops[max(0, k - 5):k + 6]) if j != min(k, 5)]
            local_mis = sum(o != "equal" for o in win) / max(1, len(win))
            vd = verdict.get(s.id)
            truth = J(vd["shape"]) if (vd and vd["v"] == "confirm" and vd["shape"]) else None
            n_cells += 1
            g = gm.get(s.id) or {}
            lib: dict[str, float] = {}
            for c, v in (g.get("candidates") or []):
                lib[J(c)] = max(lib.get(J(c), 0.0), float(v))
            rare: dict[str, float] = {}
            for x in (rc.get(s.id) or {}).get("candidates") or []:
                rare[J(x["char"])] = max(rare.get(J(x["char"]), 0.0), float(x["score"]))
            ar = al.get(s.id) or {}
            ref, op = ar.get("align_char"), ar.get("align_op")
            ref = J(ref) if ref else ref
            cur = J(s.char) if s.char else None
            lib_sorted = sorted(lib.items(), key=lambda t: -t[1])
            cands = list(dict.fromkeys(
                [c for c, _ in lib_sorted[:5]]
                + [c for c, _ in sorted(rare.items(), key=lambda t: -t[1])[:3]]
                + ([ref] if ref else []) + ([cur] if cur else [])))
            if not cands:
                continue
            if truth is not None and truth not in cands:
                n_unc += 1
            rec = sa.get(s.id) or {}
            meta = {"slot": s.slot, "sub": s.sub, "kind": s.kind, "admit": bool(s.admit),
                    "doubts": [d.split("(")[0] for d in (s.doubts or [])],
                    "verdict_v": vd["v"] if vd else None, "verdict_batch": vd["batch"] if vd else None,
                    "verdict_ts": vd["ts"] if vd else None,
                    "occluded": int(bool(vd and vd.get("via") == "doubt:occluded") or "occluded" in (s.doubts or [])),
                    "in_lib_self": int(s.id in lib_self), "truth": truth,
                    "ref_char": ref or "", "admit_char": J(rec.get("char")) if rec.get("char") else None}
            for c in cands:
                others = [v for x, v in lib.items() if x != c]
                hn = len([e for e in human_ids.get(c, ()) if e != s.id])
                rel = "none"
                if ref:
                    if c == ref:
                        rel = "exact"
                    elif (c, ref) in conv:
                        rel = "convention"
                    elif vm.semantic(c) == vm.semantic(ref):
                        rel = "variant"
                    elif (c, ref) in jiajie:
                        rel = "jiajie"
                    elif ref in partners.get(c, frozenset()):
                        rel = "confusable"
                    else:
                        rel = "unrelated"
                row = {
                    "id": s.id, "page": pg, "cand": c, "cur": cur, "channel": s.channel,
                    "label": None if truth is None else int(c == truth),
                    "lib_cov": lib.get(c, 0.0), "lib_in": int(c in lib),
                    "lib_top1": int(bool(lib_sorted) and lib_sorted[0][0] == c),
                    "lib_margin": lib.get(c, 0.0) - (max(others) if others else 0.0),
                    "lib_top_cov": lib_sorted[0][1] if lib_sorted else 0.0,
                    "human_n": hn, "human_any": int(hn > 0),
                    "ocr_p": 0.0, "ocr_rank": 9, "ocr_top1": 0, "ocr_missing": 1,
                    "rare_score": rare.get(c, 0.0),
                    "ref_eq": int(ref == c), "ref_sem": int(bool(ref) and ref != c and vm.semantic(ref) == vm.semantic(c)),
                    "ref_none": int(not ref), "ref_op_equal": int(op == "equal"),
                    "confusable": int(bool(partners.get(c, frozenset()) & set(cands))),
                    "disc_d": -1.0, "disc_has": 0, "disc_margin": 0.0,
                    "n_cands": len(cands),
                    **{f"rel_{k2}": int(rel == k2) for k2 in ("exact", "variant", "jiajie", "convention", "confusable", "unrelated")},
                    "ref_run": float(ar.get("ref_run") or 0), "ref_local_mismatch": local_mis,
                    **meta,
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                n_rows += 1
    out.close()
    lab = sum(1 for v in verdict.values() if v["v"] == "confirm" and v["shape"])
    print(f"完成：{n_cells} 格、{n_rows} 行；带字标签 {lab} 格，真值不在候选集 {n_unc} 格", file=sys.stderr)


if __name__ == "__main__":
    main()
