"""decide-bench · decide_gate 量法（CV4，2026-11-28）：gate 对「放错字」的检出率与对「放对」的误报率。

用法：
  python -m open_guji_cv.eval.decide_bench.gate_bench --cv <cv 仓根，缺省即本仓> --run 988g3f0wsu/01=<产物根>/988g3f0wsu/01 [--run …] \
      --baseline large1124-A.jsonl [--baseline mj1126-A2.jsonl] [--overlay] [--out gate-bench.json] [--tsv gate-cells.tsv]

<产物根>/<册> 下要有 seed_admit/、align_ref/、glyph_match/，可有 context_decide/、cell_shrink/（char_index，缺了就不做空白格检测）。

两种读法：
- 默认：直接读 seed_admit 产物（`guji exp run` 关人裁的变体目录，或任何产物根）。放错字按 `--baseline` 的 outcome＝「放错字」认。
- `--overlay`：产物是**冻结包**（含人裁，金标格已被人裁覆盖，看不出算法放了什么）时，把 baseline 里金标格的算法结果
  （字、放行与否、通道，decide-bench 关人裁重跑得到的）盖回对应格，去掉人裁标记，再检测。盖回的格没有原来的证据
  （字组、刻形留痕），所以只有依赖候选／参校本／对位的检测项可信；`char_not_in_evidence` 在盖回格上偏高，报告里分开记。

指标（按书、按检测项）：
  检出率＝放错字格里被 fail（或 fail／flag）标出的比例；
  误报率＝「放对」格里被标的比例（盖回读法）、以及全册非人裁放行格被标的比例（真产物，几乎都对：放行抽查 0/180 错）。
页级：fail 页占比（gate 的 fail 要人看，页数太多等于噪声）。
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--cv", default=str(Path(__file__).resolve().parents[3]))
ap.add_argument("--run", action="append", required=True, help="工作区id/册=产物根/册")
ap.add_argument("--baseline", action="append", required=True)
ap.add_argument("--overlay", action="store_true")
ap.add_argument("--items", action="append", default=[], help="decide-bench items.jsonl（取现行金标字重算 outcome：冻结后改过金标的格以它为准）")
ap.add_argument("--out")
ap.add_argument("--tsv")
ap.add_argument("--group", action="store_true", help="也跑 group_without_4d（缺省关）")
a = ap.parse_args()
sys.path.insert(0, a.cv)

from open_guji_cv.gates.decide_gate import DecideGateParams, detect_page  # noqa: E402
from open_guji_cv.products.kinds.chars import PageChars  # noqa: E402
from open_guji_cv.products.kinds.recog import PageAdmit, PageAlignRef, PageMatch, PageDecision  # noqa: E402
from open_guji_cv.groups.registry import FLOW_GROUPS, generic_flow_names  # noqa: E402

_DIG = re.compile(r"\d+")
WS_BOOK = {"988g3f0wsu": "史記", "995ejelvk0": "全唐文", "siku-zongmu": "殿本", "99k3i35yww": "脉经"}


def vnum(v: str) -> str:
    ws, _, b = str(v).rpartition("/")
    m = _DIG.search(b)
    b = str(int(m.group())) if m else b
    return f"{ws}/{b}" if ws else b


def cid(i: str) -> str:
    """基线格号 ws:册:页:列:格 → ws/册数:页:列:格；包内格号 册:页:列:格 → 册数:页:列:格。"""
    p = i.split(":")
    if len(p) == 5:
        return f"{p[0]}/{vnum(p[1])}:{p[2]}:{p[3]}:{p[4]}"
    return f"{vnum(p[0])}:{p[1]}:{p[2]}:{p[3]}"


def load(root: Path, kind: str, page: int, model, key: str | None = None):
    f = root / kind / f"p{page:04d}.json"
    if not f.exists():
        return None
    return model.model_validate(json.load(open(f))[key or kind])


FOLD = [set("己已巳"), set("日曰")]
same = lambda x, y: x == y or any(x in g and y in g for g in FOLD)
from open_guji_cv.variants import are_variants as _cv_var  # noqa: E402
EDGES = set()
_ef = Path(a.cv) / "config/hanzi/core/edges.tsv"
if _ef.exists():
    for l in open(_ef, encoding="utf-8"):
        t = l.split("\t")
        if len(t) > 2 and t[2] == "variant":
            EDGES.add((t[0], t[1])); EDGES.add((t[1], t[0]))
is_var = lambda x, y: bool(x and y) and (_cv_var(x, y) or (x, y) in EDGES)

gold = {}
for f in a.items:
    for l in open(f, encoding="utf-8"):
        it = json.loads(l)
        if it.get("status", "active") == "active":
            gold[it["id"]] = it["expected"].get("char")
base = {}
for b in a.baseline:
    for l in open(b, encoding="utf-8"):
        r = json.loads(l)
        if r["id"] in gold and gold[r["id"]] != r["truth"]:      # 金标冻结后改过：按现行金标重算 outcome
            r["truth"] = gold[r["id"]]
            adm = (r.get("rule") or "").startswith("admit:")
            if adm:
                r["outcome"] = "放对" if same(r["algo"], r["truth"]) else ("放成异体" if is_var(r["algo"], r["truth"]) else "放错字")
            else:
                r["outcome"] = "拦住·首选对" if r["algo"] and same(r["algo"], r["truth"]) else "拦住·首选错"
        elif r["id"] not in gold and gold:                        # 已移出金标（看不清）：不算
            continue
        base[cid(r["id"])] = r

per = collections.defaultdict(lambda: collections.Counter())        # 书 → 计数
hit = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))   # 书 → 检测项 → 结果类 → 数
detail, rows = [], []
for spec in a.run:
    key, root = spec.split("=", 1)
    ws, _, vol = key.rpartition("/")
    root = Path(root)
    book = None
    pages = sorted(int(re.search(r"p(\d+)", f.name).group(1)) for f in (root / "seed_admit").glob("p*.json"))
    gsets = None
    for pg in pages:
        adm = load(root, "seed_admit", pg, PageAdmit)
        if adm is None:
            continue
        pre = f"{ws}/{vnum(vol)}" if ws else vnum(vol)
        gold_here = {}
        for col in adm.columns:
            for rec in col.chars:
                k = f"{pre}:{pg}:{rec.id.split(':', 2)[2]}"
                if k in base:
                    gold_here[k] = (rec, base[k])
        if a.overlay:
            for k, (rec, r) in gold_here.items():
                rule = r.get("rule") or ""
                rec.admit = rule.startswith("admit:")
                rec.channel = rule.split(":", 1)[1] if rec.admit else None
                rec.char = r.get("algo")
                rec.provenance, rec.evidence, rec.doubts = "", {}, []
        for k, (rec, r) in gold_here.items():
            book = r.get("book")
        book = WS_BOOK.get(ws, book)
        names = (tuple(g for g in FLOW_GROUPS if g not in ()) if book == "殿本" else generic_flow_names())
        gchars = {c for g in names if g in FLOW_GROUPS for c in FLOW_GROUPS[g].members}
        res = detect_page(pg, adm, align=load(root, "align_ref", pg, PageAlignRef), match=load(root, "glyph_match", pg, PageMatch),
                          ctxdec=load(root, "context_decide", pg, PageDecision, "context_decision"), chars=load(root, "cell_shrink", pg, PageChars, "char_index"),
                          group_chars=gchars, params=DecideGateParams(check_group=a.group))
        bk = WS_BOOK.get(ws, book or ws)
        c = per[bk]
        c["pages"] += 1
        c["pages_fail"] += (not res.passed)
        by_cell = collections.defaultdict(list)
        for ch in res.checks:
            if ch.unit == "cell":
                by_cell[ch.key].append(ch)
        by_col = collections.defaultdict(list)
        for ch in res.checks:
            if ch.unit == "col":
                by_col[(pre, ch.key)].append(ch)
        for col in adm.columns:
            for rec in col.chars:
                if not rec.admit:
                    continue
                k = f"{pre}:{pg}:{rec.id.split(':', 2)[2]}"
                chs = by_cell.get(rec.id, []) + by_col.get((pre, str(col.col)), [])
                g = base.get(k)
                human = rec.channel == "human" or rec.provenance == "human"
                if g is not None:
                    if not a.overlay:      # 直接读产物：outcome 按这份产物的放行字与金标重算（baseline 的 outcome 是别的代码跑的）
                        oc = "放对" if same(rec.char, g["truth"]) else ("放成异体" if is_var(rec.char, g["truth"]) else "放错字")
                    else:
                        oc = g["outcome"]
                    cls = {"放错字": "wrong", "放对": "right", "放成异体": "variant"}.get(oc, "other")
                elif human:
                    continue
                else:
                    cls = "algo_unlabeled"
                c[cls] += 1
                lv = {x.level for x in chs}
                for lvl in ("fail", "flag"):
                    if lvl in lv:
                        c[f"{cls}_{lvl}"] += 1
                if lv:
                    c[f"{cls}_any"] += 1
                for nm in {x.name for x in chs}:
                    hit[bk][nm][cls] += 1
                if cls == "wrong" or (chs and cls == "right" and len(rows) < 100000):
                    rows.append({"id": k, "book": bk, "cls": cls, "truth": (g or {}).get("truth"), "algo": rec.char,
                                 "channel": rec.channel, "checks": sorted({f"{x.level}:{x.name}" for x in chs})})

print(f"读法：{'盖回基线（冻结包）' if a.overlay else '直接读产物'}\n")
print("书\t页\tfail页\t放错字\t检出(fail)\t检出(fail|flag)\t放对\t误报(fail)\t误报(any)\t非人裁放行(未标)\t误报(fail)\t误报(any)")
for bk, c in per.items():
    w, r, u = c["wrong"], c["right"], c["algo_unlabeled"]
    f = lambda n, d: f"{n}/{d}={n / d:.4f}" if d else f"{n}/0"
    print(f"{bk}\t{c['pages']}\t{c['pages_fail']}\t{w}\t{f(c['wrong_fail'], w)}\t{f(c['wrong_any'], w)}\t{r}\t"
          f"{f(c['right_fail'], r)}\t{f(c['right_any'], r)}\t{u}\t{f(c['algo_unlabeled_fail'], u)}\t{f(c['algo_unlabeled_any'], u)}")
print("\n检测项 × 格类（命中的放行格数；列＝/行/类）")
for bk, d in hit.items():
    print(f"[{bk}]")
    for nm, cc in sorted(d.items()):
        print(f"  {nm}\t" + "\t".join(f"{k}={v}" for k, v in sorted(cc.items())))
print("\n漏检的放错字（没被任何 fail 标出）：")
miss = [r for r in rows if r["cls"] == "wrong" and not any(x.startswith("fail:") for x in r["checks"])]
for r in miss[:40]:
    print(f"  {r['id']}\t{r['truth']}→{r['algo']}\t{r['channel']}\t{r['checks']}")
if a.out:
    Path(a.out).write_text(json.dumps({"per_book": {k: dict(v) for k, v in per.items()},
                                       "hits": {b: {n: dict(c) for n, c in d.items()} for b, d in hit.items()}},
                                      ensure_ascii=False, indent=1))
if a.tsv:
    Path(a.tsv).write_text("格\t书\t类\t金标\t算法\t通道\t检测\n" + "".join(
        f"{r['id']}\t{r['book']}\t{r['cls']}\t{r['truth']}\t{r['algo']}\t{r['channel']}\t{','.join(r['checks'])}\n" for r in rows))
