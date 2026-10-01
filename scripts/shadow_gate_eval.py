# -*- coding: utf-8 -*-
"""影子放行闸的离线评估：对一份已落盘的 seed_admit 产物，统计「若开 shadow_veto 会降级哪些格」。

    GUJI_WORKSPACE=<ws> GUJI_PRODUCTS_DIR=<产物目录> python scripts/shadow_gate_eval.py vol03 \
        --model <model.joblib> --signals <extract_snap 的 signals.jsonl> --out <dir> [--no-self-guard]

只读产物，不写产物。对每个「admit=True 且非 human 通道」的格出影子判定（`open_guji_cv.shadow.gate`），
按门槛扫描，分通道统计降级格数，并用三类证据核对：
- 人裁标签（`signals` 里的 `truth`）：降级格的现字 ≠ 人裁字 → 确是错字；= 人裁字 → 误伤；
- 无人裁标签的格只能用**整理本对齐字**当旁证（弱证据，不当真值）：整理本 = 现字（旁证偏向误伤）／
  整理本 = 影子字（旁证偏向确是错字）／两者皆非；
- `--no-self-guard`：评估快照时，本格后来才入库的人裁实例不该触发「自身在库」弃权（快照里的库信号不含它）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

THRS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.99)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("--model", default="")
    ap.add_argument("--signals", help="extract_snap 信号 jsonl（取 truth 当人裁标签）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-self-guard", action="store_true")
    ap.add_argument("--pages", default="")
    ap.add_argument("--fold", default="", help="M:i——只评估 页号 %% M == i 的页（配合 train 的 --holdout-mod）")
    ap.add_argument("--merge", default="", help="逗号分隔的各折输出目录：只合并重出报告")
    a = ap.parse_args()
    if a.merge:
        return merge(a.book, a.merge.split(","), Path(a.out))

    import open_guji_cv.steps  # noqa: F401  注册产物种类
    from open_guji_cv.core.workspace import glyph_db_path
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.shadow.gate import ShadowGate
    from open_guji_cv.shadow.model import load_model
    from open_guji_cv.shadow.offline import page_evidence
    from open_guji_cv.shadow.signals import jmerge, load_context

    truth: dict[str, str] = {}
    if a.signals:
        for ln in open(a.signals, encoding="utf-8"):
            r = json.loads(ln)
            if r.get("truth") and r["id"] not in truth:
                truth[r["id"]] = r["truth"]
    st = ProductStore()
    ctx = load_context(str(glyph_db_path()))
    if a.no_self_guard:
        ctx.lib_ids = frozenset()
    gate = ShadowGate(load_model(a.model), ctx, conf=0.0)
    pages = sorted(int(p.stem[1:]) for p in (st.root / a.book / "seed_admit").glob("p*.json"))
    if a.pages:
        lo, _, hi = a.pages.partition("-")
        pages = [p for p in pages if int(lo) <= p <= int(hi or lo)]
    if a.fold:
        m, i = (int(x) for x in a.fold.split(":"))
        pages = [p for p in pages if p % m == i]
    rows, n_eligible, abst = [], 0, Counter()
    for pg in pages:
        from open_guji_cv.core.spec import page_key
        sa = {r["id"]: r for c in st.read(a.book, "seed_admit", page_key(pg), "seed_admit").model_dump()["columns"]
              for r in (c.get("chars") or [])}
        ev = page_evidence(st, a.book, pg)
        for i, e in ev.items():
            rec = sa[i]
            if not rec["admit"] or rec.get("provenance") == "human" or rec.get("channel") == "human":
                continue
            n_eligible += 1
            v = gate.judge(e)
            if v.reason.startswith("abstain"):
                abst[v.reason] += 1
                continue
            ref = jmerge(e.ref) if e.ref else None
            rows.append({"id": i, "page": pg, "channel": rec["channel"], "cur": e.cur, "pick": v.pick,
                         "conf": round(v.conf, 4), "cur_conf": round(v.cur_conf, 4), "ref": ref,
                         "differs": v.pick != jmerge(e.cur), "truth": truth.get(i)})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"eval_{a.book}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    (out / f"eval_{a.book}.meta.json").write_text(json.dumps(
        {"model": gate.model.version, "pages": len(pages), "n_eligible": n_eligible, "abstain": dict(abst)}), encoding="utf-8")
    report(a.book, rows, {"model": gate.model.version, "pages": len(pages), "n_eligible": n_eligible, "abstain": dict(abst)}, out)


def merge(book: str, dirs: list[str], out: Path) -> None:
    rows, meta = [], {"model": "按页折交叉（见各折）", "pages": 0, "n_eligible": 0, "abstain": Counter()}
    for d in dirs:
        rows += [json.loads(l) for l in open(Path(d) / f"eval_{book}.jsonl", encoding="utf-8") if l.strip()]
        m = json.loads((Path(d) / f"eval_{book}.meta.json").read_text(encoding="utf-8"))
        meta["pages"] += m["pages"]
        meta["n_eligible"] += m["n_eligible"]
        meta["abstain"].update(m["abstain"])
    meta["abstain"] = dict(meta["abstain"])
    out.mkdir(parents=True, exist_ok=True)
    report(book, rows, meta, out)


def report(book: str, rows: list, meta: dict, out: Path) -> None:
    from open_guji_cv.shadow.signals import jmerge
    n_eligible, abst = meta["n_eligible"], meta["abstain"]
    def klass(r):
        t = r["truth"]
        if t is not None:
            return "错字(人裁)" if jmerge(t) != jmerge(r["cur"]) else "误伤(人裁)"
        if r["ref"] and r["ref"] == jmerge(r["cur"]):
            return "无人裁·整理本=现字"
        if r["ref"] and r["ref"] == r["pick"]:
            return "无人裁·整理本=影子"
        return "无人裁·旁证皆非"

    L = [f"# 影子闸离线评估 · {book}\n", f"- 模型 `{meta['model']}`；产物 {meta['pages']} 页；放行且非人裁格 {n_eligible}；"
         f"弃权 {dict(abst)}；其中有人裁标签的格 {sum(1 for r in rows if r['truth'])}（错字 "
         f"{sum(1 for r in rows if r['truth'] and jmerge(r['truth']) != jmerge(r['cur']))}）。\n",
         "## 门槛扫描（影子选了不同字、把握 ≥ 门槛 → 降级）\n",
         "| 门槛 | 降级格 | 占放行% | 错字(人裁) | 误伤(人裁) | 无人裁·整理本=影子 | 无人裁·整理本=现字 | 无人裁·旁证皆非 |",
         "|---|---|---|---|---|---|---|---|"]
    for t in THRS:
        vs = [r for r in rows if r["differs"] and r["conf"] >= t]
        c = Counter(klass(r) for r in vs)
        L.append(f"| {t} | {len(vs)} | {len(vs) / max(1, n_eligible):.2%} | {c['错字(人裁)']} | {c['误伤(人裁)']} | "
                 f"{c['无人裁·整理本=影子']} | {c['无人裁·整理本=现字']} | {c['无人裁·旁证皆非']} |")
    L += ["\n## 分通道（门槛 0.9）\n", "| 通道 | 放行格 | 降级格 | 错字(人裁) | 误伤(人裁) | 整理本=影子 | 整理本=现字 | 旁证皆非 |", "|---|---|---|---|---|---|---|---|"]
    tot = Counter(r["channel"] for r in rows)
    byc = defaultdict(list)
    for r in rows:
        if r["differs"] and r["conf"] >= 0.9:
            byc[r["channel"]].append(r)
    for ch in sorted(tot, key=lambda k: -tot[k]):
        c = Counter(klass(r) for r in byc[ch])
        L.append(f"| {ch} | {tot[ch]} | {len(byc[ch])} | {c['错字(人裁)']} | {c['误伤(人裁)']} | "
                 f"{c['无人裁·整理本=影子']} | {c['无人裁·整理本=现字']} | {c['无人裁·旁证皆非']} |")
    lab = [r for r in rows if r["truth"]]
    L += [f"\n## 有人裁标签的放行格（{len(lab)}）逐格\n", "| 字位 | 通道 | 现字 | 人裁 | 影子 | 把握 | 整理本 |", "|---|---|---|---|---|---|---|"]
    L += [f"| {r['id']} | {r['channel']} | {r['cur']} | {r['truth']} | {r['pick']} | {r['conf']} | {r['ref'] or '—'} |"
          for r in sorted(lab, key=lambda r: -r["conf"])]
    L += ["\n## 把握 ≥0.9 且无人裁的降级格（前 60，按把握）\n", "| 字位 | 通道 | 现字 | 影子 | 把握 | 整理本 |", "|---|---|---|---|---|---|"]
    un = sorted((r for r in rows if r["differs"] and r["conf"] >= 0.9 and not r["truth"]), key=lambda r: -r["conf"])
    L += [f"| {r['id']} | {r['channel']} | {r['cur']} | {r['pick']} | {r['conf']} | {r['ref'] or '—'} |" for r in un[:60]]
    (out / f"eval_{book}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:30]))


if __name__ == "__main__":
    main()
