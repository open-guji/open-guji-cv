"""decide-bench 打分（CV4，2026-11-23）：seed_admit 产物 × 金标分片 → 按书报分＋翻转清单。

用法：
  python -m open_guji_cv.eval.decide_bench.score --items <decide-bench/small/items.jsonl> --run 03=<产物根/03> --run 004=<…/004> --run vol01=<…/vol01> \
      --out result.jsonl [--against 上一次的result.jsonl] [--flips flips.tsv]

<产物根/册> 下要有 seed_admit/p*.json（`guji exp run` 的变体目录 `<实验>/<变体>/<册>`，或任何产物根）。
格按金标 anchor 的冻结格号对（第四步不改切分）。

每格结果（outcome）：放对／放成异体／放错字／拦住·首选对／拦住·首选错／缺格。
- 己已巳、日曰组内任一字算对；
- 异体＝cv variants 图 ∪ cv config/hanzi/core/edges.tsv 的 variant 边。
指标：wrong_admit（放错字，必须 0）、variant_admit、admit_rate、review_top1_ok。
--against：和上一次逐格比，结果变了的列成翻转清单（好转／变坏／其它）。
"""
import argparse, re, collections, glob, json, os, sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--items", required=True)
ap.add_argument("--run", action="append", required=True, help="册=产物根/册；册号跨书重名（史記 01／脉经 01）时写 工作区id/册=…")
ap.add_argument("--out")
ap.add_argument("--against")
ap.add_argument("--flips")
ap.add_argument("--rebind", action="store_true", help="按金标原图框对现行切分的格（IoU≥0.5、次格<0.2），动态层用")
ap.add_argument("--only-present", action="store_true", help="只评产物里有这一页的金标格（中途停掉的部分跑用；缺页的格不计缺格）")
ap.add_argument("--no-substeps", action="store_true", help="不出子步指标与错因位置列（只出收尾口径）")
ap.add_argument("--max-missing", type=float, default=0.01, help="缺格率上限（缺省 1%%）：超了就不算通过，打印后以退出码 3 结束。收尾大面积失败时 wrong_admit=0 是假通过")
ap.add_argument("--cv", default=os.environ.get("GUJI_CV_REPO", str(Path(__file__).resolve().parents[3])))
a = ap.parse_args()

FOLD = [set("己已巳"), set("日曰")]
same = lambda x, y: x == y or any(x in g and y in g for g in FOLD)
try:
    from open_guji_cv.variants import are_variants as _cv_var
except Exception:  # noqa: BLE001
    _cv_var = lambda x, y: False
EDGES = set()
ef = Path(a.cv) / "config/hanzi/core/edges.tsv"
if ef.exists():
    for l in open(ef, encoding="utf-8"):
        t = l.split("\t")
        if len(t) > 2 and t[2] == "variant":
            EDGES.add((t[0], t[1])); EDGES.add((t[1], t[0]))
else:
    print(f"⚠ 找不到 {ef}，异体只认 cv variants 图")
is_var = lambda x, y: bool(x and y) and (_cv_var(x, y) or (x, y) in EDGES)

def _box(q):
    xs, ys = [p[0] for p in q], [p[1] for p in q]
    return [min(xs), min(ys), max(xs), max(ys)]


def _iou(p, q):
    ix = max(0, min(p[2], q[2]) - max(p[0], q[0])); iy = max(0, min(p[3], q[3]) - max(p[1], q[1]))
    u = (p[2] - p[0]) * (p[3] - p[1]) + (q[2] - q[0]) * (q[3] - q[1]) - ix * iy
    return ix * iy / u if u > 0 else 0.0


def _alt_remap(root, sa_file, sa):
    """备选切法（alt_cut）换了列的页：seed_admit 里这些列的格号是备选格网的号，与主切法同号却不是同一格
    （脉经目录页前导空格：备选格网把空格剔了，主切法第 3 格＝备选第 1 格）。按原图框把备选号换成主切法同位置的格号，
    金标（按主切法冻结格号）才对得上。CV4 11-27。"""
    if not sa.get("alt_cols"):
        return {}
    page = sa["page"]
    f = Path(root) / "row_segment" / f"p{page:04d}.json"
    if not f.exists():
        return {}
    cells = json.load(open(f))["cells"]

    def boxes(cols, only=None):
        out = {}
        for col in cols:
            if only is not None and col["col"] not in only:
                continue
            for cl in col.get("cells") or []:
                if cl.get("quad_page") and cl.get("kind") not in ("blank", None):
                    out[f"{col['col']}:{cl['slot']}{cl.get('sub') or ''}"] = _box(cl["quad_page"])
        return out
    alt_cols = set(sa["alt_cols"])
    main, alt = boxes(cells["columns"], alt_cols), boxes(cells.get("alt_columns") or [], alt_cols)
    remap = {}
    for k, b in alt.items():
        best = max(((_iou(b, mb), mk) for mk, mb in main.items()), default=(0, None))
        pre = next((x["id"].rsplit(":", 2)[0] for c in sa["columns"] for x in c["chars"][:1]), None)
        # 对不上主切法任何格（IoU<0.5）的备选格：号别留着，否则会和主切法同号的另一格撞车
        remap[f"{pre}:{k}"] = f"{pre}:{best[1]}" if best[0] >= 0.5 else f"alt!{pre}:{k}"
    return remap


_DIG = re.compile(r"\d+")


def vnum(v):
    """册号 → 整数串（册号位数 11-27 起按全书册数统一、会改号：03／003／vol03 都是 3）。工作区前缀保留。"""
    v = str(v)
    ws, _, b = v.rpartition("/")
    m = _DIG.search(b)
    b = str(int(m.group())) if m else b
    return f"{ws}/{b}" if ws else b


def ck(cid):
    """格号 册:页:列:格 → 册号按数值（vol01:88:6:9b → 1:88:6:9b）；alt! 前缀照留。"""
    pre = "alt!" if cid.startswith("alt!") else ""
    v, _, rest = cid[len(pre):].partition(":")
    return f"{pre}{vnum(v)}:{rest}"


algo = {}
for spec in a.run:
    vol, root = spec.split("=", 1)
    fs = glob.glob(str(Path(root) / "char_decide" / "p*.json")) or glob.glob(str(Path(root) / "seed_admit" / "p*.json"))   # 11-28 起收尾叫 char_decide，旧册还是 seed_admit
    if not fs:
        raise SystemExit(f"{root} 下没有 char_decide／seed_admit 产物")
    for f in fs:
        _d = json.load(open(f))
        _sa = _d.get("char_decide") or _d["seed_admit"]
        _remap = _alt_remap(Path(root), f, _sa)
        for col in _sa["columns"]:
            for x in col.get("chars") or []:
                adm = bool(x.get("admit"))
                ev = x.get("evidence") or {}
                rule = f"admit:{x.get('channel')}" if adm else \
                    "review:" + str(((ev.get("demoted_from") or {}).get("by")) or ((x.get("doubts") or ["?"])[0]))
                algo[(vnum(vol), ck(_remap.get(x["id"], x["id"])))] = (x.get("char"), adm, rule)
vols = {vnum(s.split("=", 1)[0]) for s in a.run}
roots = {vnum(k): r for k, r in (s.split("=", 1) for s in a.run)}
_cells = {}


def _box(q):
    xs, ys = [p[0] for p in q], [p[1] for p in q]
    return [min(xs), min(ys), max(xs), max(ys)]


def _iou(p, q):
    ix = max(0, min(p[2], q[2]) - max(p[0], q[0])); iy = max(0, min(p[3], q[3]) - max(p[1], q[1]))
    u = (p[2] - p[0]) * (p[3] - p[1]) + (q[2] - q[0]) * (q[3] - q[1]) - ix * iy
    return ix * iy / u if u > 0 else 0.0


def rebind(vol, page, bbox):
    """金标原图框 → 现行切分格号；对不上返回 None。"""
    if (vol, page) not in _cells:
        f, out = Path(roots[vol]) / "row_segment" / f"p{page:04d}.json", []
        if f.exists():
            for col in json.load(open(f))["cells"]["columns"]:
                for cl in col.get("cells") or []:
                    if cl.get("quad_page") and cl.get("kind") not in ("blank", None):
                        out.append((f"{vol.rpartition('/')[2]}:{page}:{col['col']}:{cl['slot']}{cl.get('sub') or ''}", _box(cl["quad_page"])))
        _cells[(vol, page)] = out
    c = sorted(((_iou(bbox, b), k) for k, b in _cells[(vol, page)]), reverse=True)
    if not c or c[0][0] < 0.5 or (len(c) > 1 and c[1][0] >= 0.2):
        return None
    return c[0][1]


rows, M = [], collections.defaultdict(collections.Counter)
for l in open(a.items):
    it = json.loads(l)
    an = it["anchor"]
    vk = vnum(f"{an.get('ws')}/{an['book']}")
    vk = vk if vk in vols else vnum(an["book"])
    if vk not in vols or it.get("status", "active") != "active":
        continue
    key, truth, bk = an.get("key_at_freeze"), it["expected"].get("char"), it.get("book_title") or an["book"]
    if a.rebind:
        key = rebind(vk, int(an["page"]), an["bbox"])
    x = algo.get((vk, ck(key))) if key else None
    if x is None and a.only_present and not (key and any((Path(roots[vk]) / n / f"p{int(an['page']):04d}.json").exists() for n in ("char_decide", "seed_admit"))):
        continue
    if x is None:
        oc, ch, rule = "缺格", None, None
    else:
        ch, adm, rule = x
        if adm:
            oc = "放对" if same(ch, truth) else ("放成异体" if is_var(ch, truth) else "放错字")
        else:
            oc = "拦住·首选对" if ch and same(ch, truth) else "拦住·首选错"
    rows.append({"id": it["id"], "book": bk, "truth": truth, "algo": ch, "rule": rule, "outcome": oc,
                 "stratum": it.get("stratum"), "_vk": vk, "_key": key})
    M[bk][oc] += 1

cols = ["放对", "放成异体", "放错字", "拦住·首选对", "拦住·首选错", "缺格"]
print("书\t" + "\t".join(cols) + "\t放行率\t人审首选对率")
for bk, c in M.items():
    n = sum(c.values()); adm = c["放对"] + c["放成异体"] + c["放错字"]; rv = c["拦住·首选对"] + c["拦住·首选错"]
    print(f"{bk}\t" + "\t".join(str(c[k]) for k in cols) + f"\t{adm / n:.4f}\t{(c['拦住·首选对'] / rv if rv else 0):.3f}")
bad = [r for r in rows if r["outcome"] == "放错字"]
_miss = sum(1 for r in rows if r["outcome"] == "缺格")
_miss_rate = _miss / len(rows) if rows else 1.0
MISS_FAIL = _miss_rate > a.max_missing
print(f"wrong_admit = {len(bad)}" + ("  ✗ 必须为 0" if bad else ("  ⚠ 不算通过（见下）" if MISS_FAIL else "  ✓")))
print(f"缺格 {_miss}／{len(rows)}（{_miss_rate:.2%}，上限 {a.max_missing:.2%}）" + ("  ✗ 收尾没跑出这些格，wrong_admit=0 不可信" if MISS_FAIL else "  ✓"))
for r in bad[:20]:
    print("  放错字", r["id"], r["truth"], "→", r["algo"], r["rule"])

# ───────── 子步指标（P1b，CV4 2026-11-28；设计见 第四步定字-子步重构设计-2026-11-28.md）─────────
# 只读产物：align_ref（4a）、context_decide（4b）、seed_admit evidence（4c/4d/收尾）、glyph_match（第三步候选）。
# 4c/4d 现在还没独立产物，指标先从 seed_admit evidence 反推（字段名见 SUB_NOTE），拆出后改读各自产物。
SUB = {}


def _sub_page(vk, page):
    """读一页的 4a/4b/第三步/收尾 产物 → {格id: {...}}；缺的产物留空。"""
    if (vk, page) in SUB:
        return SUB[(vk, page)]
    root, out = Path(roots[vk]), {}
    def load(step, top):
        for st in ((step, "seed_admit") if step == "char_decide" else (step,)):
            f = root / st / f"p{page:04d}.json"
            if f.exists():
                d = json.load(open(f))
                return d.get(top) or (d.get("seed_admit") if top == "char_decide" else None) or {}
        return None
    ar, cd, gm, sa = load("align_ref", "align_ref"), load("context_decide", "context_decision"), load("glyph_match", "glyph_match"), load("char_decide", "char_decide")
    if ar:
        seq = ar.get("chars") or []
        for i, c in enumerate(seq):
            near = [seq[j].get("align_char") for j in range(max(0, i - 3), min(len(seq), i + 4)) if j != i]
            out.setdefault(c["id"], {}).update(ref=c.get("align_char"), ref_op=c.get("align_op"), ref_near=near, anchored=ar.get("anchored"))
        for c in ar.get("coord") or []:
            out.setdefault(c["id"], {}).setdefault("coord_ref", c.get("ref_char"))
    for blk, key in ((cd, "ctx"), (gm, "gm")):
        for col in (blk or {}).get("columns") or []:
            for x in col.get("chars") or []:
                out.setdefault(x["id"], {})[key] = x
    for col in (sa or {}).get("columns") or []:
        for x in col.get("chars") or []:
            out.setdefault(x["id"], {})["sa"] = x
    SUB[(vk, page)] = out
    return out


def _page_of(key):
    m = re.match(r"^(?:alt!)?[^:]*:(\d+):", key or "")
    return int(m.group(1)) if m else None


def _gold_fields(r):
    vk, key = r["_vk"], r["_key"]
    pg = _page_of(key)
    if not key or key.startswith("alt!") or pg is None:
        return None
    raw = key.split(":", 1)[1]
    # 产物里的格 id 带原册号写法（vol01:88:6:9b），按册号数值对
    for cid, d in _sub_page(vk, pg).items():
        if ck(cid) == ck(key):
            return d
    return None


def sub_attr(r):
    """每个金标格的子步属性。"""
    d = _gold_fields(r) or {}
    t, out = r["truth"], {}
    ref = d.get("ref") if d.get("ref") is not None else d.get("coord_ref")
    out["ref"] = ref
    if ref is None:
        out["a4"] = "无参校"
    elif same(ref, t) or is_var(ref, t):
        out["a4"] = "对"
    elif any(n and (same(n, t) or is_var(n, t)) for n in d.get("ref_near", [])):
        out["a4"] = "错位"
    else:
        out["a4"] = "真异文"
    cx = d.get("ctx") or {}
    out["ctx_char"] = cx.get("char")
    out["ctx_src"] = cx.get("source")
    out["ctx_top"] = (cx.get("ranked") or [[None]])[0][0]
    out["ctx_margin"] = cx.get("margin")
    sa = d.get("sa") or {}
    ev = sa.get("evidence") or {}
    dem = (ev.get("demoted_from") or {}).get("by")
    out["c4_excl"] = bool(ev.get("excluded") or "excluded" in (sa.get("doubts") or []))   # 人裁排除名单带入，不是算法判的
    # 遮挡/印章空白闸「判无字」且这格因此没放行才算漏字；evidence 里只留了标记、格照样放行的不算（殿本大集 56 格带 occluded 标记，47 格仍放对）
    out["c4_mark"] = bool(not out["c4_excl"] and (ev.get("occluded") or dem in ("seal_blank_flip",)))
    out["c4_flag"] = bool(out["c4_mark"] and not sa.get("admit"))
    g = ev.get("group") if isinstance(ev.get("group"), dict) else None
    out["group_mode"] = g.get("mode") if g else None
    out["group_char"] = (g or {}).get("char") or (g or {}).get("pick")
    gm = d.get("gm") or {}
    out["truth_in_cands"] = any(same(c[0], t) or is_var(c[0], t) for c in (gm.get("candidates") or [])) if gm else None
    return out


def errloc(r, at):
    """错因位置：只给最终字不对（放错字、拦住·首选错）的格。按次序归第一个说得通的子步。"""
    if r["outcome"] not in ("放错字", "拦住·首选错"):
        return "—"
    if r["outcome"] == "缺格":
        return "切分"
    if at.get("c4_excl"):
        return "排除名单"
    if at["c4_flag"]:
        return "4c"
    ch = r["algo"]
    if (r["rule"] or "").startswith("admit:group"):   # 字组通道放行放错：归 4d（即使放行字恰好＝参校本字）
        return "4d"
    if ch and at["ref"] and ch == at["ref"] and at["a4"] in ("错位", "真异文"):
        return "4a"
    if r["rule"] and ("group" in r["rule"]) or (at["group_mode"] in ("lift", "joint") and ch and not same(ch, r["truth"])):
        return "4d"
    if r["rule"] and any(k in r["rule"] for k in ("context", "ref_ctx")):
        return "4b"
    if at["truth_in_cands"] is False:
        return "上游3"
    return "收尾"


if not a.no_substeps:
    for r in rows:
        at = sub_attr(r) if r["outcome"] != "缺格" else {"a4": "—", "c4_flag": False, "c4_mark": False, "c4_excl": False, "ctx_src": None, "group_mode": None, "ctx_char": None, "ctx_top": None, "ctx_margin": None, "truth_in_cands": None, "ref": None}
        r.update({k: v for k, v in at.items() if k != "ref"}, ref=at["ref"])
        r["errloc"] = errloc(r, at) if r["outcome"] != "缺格" else "切分"
    pb = collections.defaultdict(list)
    for r in rows:
        pb[r["book"]].append(r)
    pct = lambda n, m: f"{n / m:.4f}" if m else "—"
    print("\n══ 子步指标（按书）══")
    print("【4a 对位】书\t金标格\t参校本对\t错位\t真异文\t无参校\t错位率")
    for bk, rs in pb.items():
        c = collections.Counter(r["a4"] for r in rs)
        print(f"{bk}\t{len(rs)}\t{c['对']}\t{c['错位']}\t{c['真异文']}\t{c['无参校']}\t{pct(c['错位'], len(rs))}")
    print("【4b 上下文】书\t给字格\t其中n-gram上下文(source=context)给字/对\t给字错\t未定格\t未定格首位对\t上下文给字精度（目标≥0.999；db_same是库判同，不算4b）")
    for bk, rs in pb.items():
        dec = [r for r in rs if r.get("ctx_char")]
        cx = [r for r in dec if r.get("ctx_src") == "context"]
        cok = sum(1 for r in cx if same(r["ctx_char"], r["truth"]))
        und = [r for r in rs if not r.get("ctx_char") and r.get("ctx_top")]
        uok = sum(1 for r in und if same(r["ctx_top"], r["truth"]))
        print(f"{bk}\t{len(dec)}\t{len(cx)}/{cok}\t{len(cx) - cok}\t{len(und)}\t{uok}\t{pct(cok, len(cx))}")
    print("【4c 格况】书\t遮挡/印章空白闸判无字且因此送审的金标格（有字判无字＝漏字，必须0）；另列：带遮挡标记但仍放行、人裁排除名单带入（不算法）")
    for bk, rs in pb.items():
        miss = [r for r in rs if r.get("c4_flag")]
        print(f"{bk}\t漏字 {len(miss)}" + ("  ✗" if miss else "  ✓") + f"；带标记仍放行 {sum(1 for r in rs if r.get('c4_mark') and not r.get('c4_flag'))}；排除名单带入 {sum(1 for r in rs if r.get('c4_excl'))}" + ("；漏字例：" + "、".join(r['id'] for r in miss[:5]) if miss else ""))
    print("【4d 字组】书\t组内格\t各mode\t组内最终字错（放错字+拦住首选错）")
    for bk, rs in pb.items():
        gs = [r for r in rs if r.get("group_mode")]
        bad = sum(1 for r in gs if r["outcome"] in ("放错字", "拦住·首选错"))
        print(f"{bk}\t{len(gs)}\t{dict(collections.Counter(r['group_mode'] for r in gs))}\t{bad}")
    print("【收尾】书\t首选对率(全金标格，不管放不放行)\t放错字按通道")
    for bk, rs in pb.items():
        ok = sum(1 for r in rs if r["outcome"] in ("放对", "放成异体", "拦住·首选对"))
        wc = collections.Counter(r["rule"] for r in rs if r["outcome"] == "放错字")
        print(f"{bk}\t{pct(ok, len(rs))}\t{dict(wc) or '无'}")
    print("【错因位置】书\t" + "\t".join(["4a", "4b", "4c", "4d", "收尾", "上游3", "切分", "排除名单"]) + "\t（只统计放错字＋拦住·首选错）")
    for bk, rs in pb.items():
        c = collections.Counter(r["errloc"] for r in rs if r["errloc"] != "—")
        print(f"{bk}\t" + "\t".join(str(c[k]) for k in ["4a", "4b", "4c", "4d", "收尾", "上游3", "切分", "排除名单"]))
    wl = collections.Counter((r["book"], r["errloc"]) for r in rows if r["outcome"] == "放错字")
    print("放错字的错因位置：" + ("，".join(f"{b}·{k}×{n}" for (b, k), n in sorted(wl.items())) or "无"))

if a.out:
    Path(a.out).write_text("".join(json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, ensure_ascii=False) + "\n" for r in rows))

if a.against:
    RANK = {"放对": 3, "放成异体": 2, "拦住·首选对": 1, "拦住·首选错": 1, "放错字": 0, "缺格": -1}
    old = {json.loads(l)["id"]: json.loads(l) for l in open(a.against)}
    fl = []
    for r in rows:
        o = old.get(r["id"])
        if o and (o["outcome"], o["algo"]) != (r["outcome"], r["algo"]):
            d = RANK[r["outcome"]] - RANK[o["outcome"]]
            fl.append(("好转" if d > 0 else "变坏" if d < 0 else "其它", r, o))
    cnt = collections.Counter((k, r["book"]) for k, r, _ in fl)
    print(f"\n翻转 {len(fl)} 格：" + "，".join(f"{b}{k}{n}" for (k, b), n in sorted(cnt.items())))
    for k, r, o in sorted(fl, key=lambda t: ("变坏", "其它", "好转").index(t[0]))[:30]:
        print(f"  {k}\t{r['id']}\t金标 {r['truth']}\t{o['algo']}（{o['outcome']}，{o['rule']}）→ {r['algo']}（{r['outcome']}，{r['rule']}）")
    if a.flips:
        Path(a.flips).write_text("类\t格\t金标\t前字\t前结果\t前规则\t后字\t后结果\t后规则\n" + "".join(
            f"{k}\t{r['id']}\t{r['truth']}\t{o['algo']}\t{o['outcome']}\t{o['rule']}\t{r['algo']}\t{r['outcome']}\t{r['rule']}\n" for k, r, o in fl))

if MISS_FAIL:
    sys.exit(3)
