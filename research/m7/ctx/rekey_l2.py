"""L2 文意表改键（2026-10-27，A24「统一上线」：殿本换 siku-qiefen-v2 图源后格号变了，L2 表按旧格号查全部 cache_miss）。

用法：

  python rekey_l2.py <产物根> <L2 表目录> <输出目录> [--vols vol07,vol08…] [--map <old_new_cells 目录>] [--codepoints <yaml>]

- 产物根：`guji products pack fetch` 的布局，每册要 `seed_admit/`、`align_ref/`（换源后的新产物）。
- 对每张表（`<组>.json`，schema `group_clf/1`）的每条：在同册新产物里按**同一窗口**（`seed_admit._clf_ctx`，与线上
  `ctx_l2.judge` 取窗一致）找上下文相同的格：
  1. 旧格号在新产物里窗口还对得上 → 不动；
  2. 同册新格里窗口相同（先逐字，再按书级码位归一）且唯一 → 换成新格号；
  3. 不唯一时用格级对照表（ai-team `domain/CV/图源迁移/siku-qiefen-v2/results/old_new_cells/volNN.tsv.gz`，有的册才有）
     给的新格号在候选里 → 用它；
  4. 都不成 → 保留旧键（线上照旧 cache_miss，不会用错）。
- 不改 `ctx`、`char`、票：表的结论是按上下文读出来的，窗口逐字对上才挪，线上 `judge` 还会再核一遍窗口。
- 输出：改键后的表写到输出目录同名文件，`ver` 加 `+rk1027`；`report.json` 记各组各册 保持/改键/对照表/没找到 条数。
"""
import argparse, gzip, json, collections
from pathlib import Path
from types import SimpleNamespace

from open_guji_cv.groups.context import WIDTH, ctx_key
from open_guji_cv.groups.ctx_l2 import DRIFT_CORE, _split_key, ctx_drift
from open_guji_cv.steps.seed_admit import _clf_ctx
from open_guji_cv.utils.jiazhu_order import sort_by_reading

ap = argparse.ArgumentParser()
ap.add_argument("root"); ap.add_argument("tables"); ap.add_argument("out")
ap.add_argument("--vols", default=""); ap.add_argument("--map", default=None)
ap.add_argument("--codepoints", default="")
ap.add_argument("--suffix", default="+rk1027")
ap.add_argument("--drift", type=int, default=2, help="同线上 group_flow_l2_drift：窗口差至多这么多远处字位也算对上")
a = ap.parse_args()
root, out = Path(a.root), Path(a.out)
out.mkdir(parents=True, exist_ok=True)
CP = {}
if a.codepoints:
    import yaml
    CP = {str(k): str(v) for k, v in ((yaml.safe_load(open(a.codepoints, encoding="utf-8")) or {}).get("codepoints") or {}).items()}


def canon(s: str) -> str:
    return "".join(CP.get(c, c) for c in s)


def windows(v: str) -> dict:
    """新产物每格的窗口键 → {格号: ctx}。"""
    res = {}
    for f in sorted((root / v / "seed_admit").glob("p*.json")):
        d = json.load(open(f, encoding="utf-8"))["seed_admit"]
        af = root / v / "align_ref" / f.name
        amap = {}
        if af.exists():
            ar = json.load(open(af, encoding="utf-8"))["align_ref"]
            amap = {c["id"]: (c["align_char"], c.get("align_op")) for c in ar["chars"]}
        cols = []
        for col in sorted(d["columns"], key=lambda c: c["col"]):
            cols.append([SimpleNamespace(id=c["id"], char=c.get("char"), admit=c.get("admit"), doubts=c.get("doubts"),
                                         slot=c.get("slot"), sub=c.get("sub"), col=col["col"]) for c in col["chars"]])
        seq = [r for recs in cols for r in sort_by_reading(recs) if not (r.doubts and "excluded" in r.doubts)]
        for i, r in enumerate(seq):
            res[r.id] = ctx_key(_clf_ctx(seq, amap, i, -1, WIDTH), _clf_ctx(seq, amap, i, 1, WIDTH))
    return res


def core(c: str) -> str:
    """目标字两侧各 DRIFT_CORE 字（ctx_drift 要求这几位必须相同），按码位归一。"""
    sp = _split_key(c)
    return canon(sp[0][-DRIFT_CORE:] + "|" + sp[1][:DRIFT_CORE]) if sp else ""


def _d(x, y, cp) -> int:
    n = ctx_drift(x, y, cp)
    return 99 if n is None else n


def old_new(v: str) -> dict:
    if not a.map:
        return {}
    p = Path(a.map) / f"{v}.tsv.gz"
    if not p.exists():
        return {}
    m = {}
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            x = line.rstrip("\n").split("\t")
            if len(x) >= 5 and x[4] != "删" and x[0] and x[1]:
                m[x[0]] = x[1]
    return m


tabs = {p.stem: json.load(open(p, encoding="utf-8")) for p in sorted(Path(a.tables).glob("*.json"))}
tabs = {g: t for g, t in tabs.items() if t.get("schema") == "group_clf/1"}
vols = set(a.vols.split(",")) - {""} or {k.split(":")[0] for t in tabs.values() for k in t.get("cells") or {}}
rep = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
new_cells = {g: {} for g in tabs}
by_vol = collections.defaultdict(list)
for g, t in tabs.items():
    for k, e in (t.get("cells") or {}).items():
        v = k.split(":")[0]
        if v in vols and (root / v / "seed_admit").exists():
            by_vol[v].append((g, k, e))
        else:
            new_cells[g][k] = e
for v in sorted(by_vol):
    w = windows(v)
    idx, idx_c, idx_core = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for cid, c in w.items():
        idx[c].append(cid)
        idx_c[canon(c)].append(cid)
        idx_core[core(c)].append(cid)
    cp = canon if CP else None
    m = old_new(v)
    for g, k, e in by_vol[v]:
        ctx = e.get("ctx") or ""
        if ctx and w.get(k) in (ctx,) or (CP and w.get(k) and canon(w[k]) == canon(ctx)):
            nk, how = k, "keep"
        else:
            cand = idx.get(ctx) or idx_c.get(canon(ctx)) or []
            if len(cand) == 1:
                nk, how = cand[0], "ctx"
            elif m.get(k) in cand:
                nk, how = m[k], "map"
            else:
                # 线上 judge 容许远处至多 drift 位不同：同样的容差在同册找，唯一才挪；多个时对照表给的那个优先
                near = [cid for cid in idx_core.get(core(ctx), []) if _d(ctx, w[cid], cp) <= a.drift] if ctx else []
                if len(near) == 1:
                    nk, how = near[0], "drift"
                elif m.get(k) in near:
                    nk, how = m[k], "drift_map"
                else:
                    nk, how = k, "miss" if not (cand or near) else "ambiguous"
        rep[g][v][how] += 1
        if nk in new_cells[g] and new_cells[g][nk] is not e:
            rep[g][v]["collide"] += 1
            continue
        new_cells[g][nk] = e
for g, t in tabs.items():
    t2 = dict(t, cells=new_cells[g], ver=str(t.get("ver") or "") + a.suffix)
    (out / f"{g}.json").write_text(json.dumps(t2, ensure_ascii=False, indent=1), encoding="utf-8")
json.dump({g: {v: dict(c) for v, c in d.items()} for g, d in rep.items()}, open(out / "report.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
tot = collections.Counter()
for d in rep.values():
    for c in d.values():
        tot.update(c)
print(dict(tot))
