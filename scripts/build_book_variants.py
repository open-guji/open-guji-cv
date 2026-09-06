# -*- coding: utf-8 -*-
"""本书用字账：从产物 + 字形库 + 整理本语料派生 ``config/variants/books/<edition>.json``。

    python scripts/build_book_variants.py [--edition wuyingdian_zongmu] [--books vol01,vol02]
                                          [--corpus corpus/zongmu_wuyingdian_reference.txt]
                                          [--glyph-db output/glyph.db] [--dry-run]

**永不手编**——每次重跑整份重建（确定性输出，便于 diff）。三处来源：

1. ``seed_admit`` 产物 ``AdmitRec(char, reading, channel, admit)``：v2 管线自动放行的
   刻本形与转换对（``reading ≠ char`` 就是一次 字形→文意 转换）；
2. ``glyph.db`` ``admissions × instances``：全部已进库实例的字形标签，按 provenance
   分 human / match / context / align；人裁的 ``evidence.shape/reading/conversion`` 与
   ``correction.old_char/new_char`` 给出人确认的转换对；
3. 整理本语料字频：每个形在整理本里印了几次（``ref``）。

分组：以每个书内形为起点，沿关系图的异体/互通/简繁来源取一跳邻居，**只留本书或
整理本里出现过的**（字典里那些刻本不会用的古文异体就此过滤掉，variant_strategy.md
§2.3），再按 canonical（教育部正字优先，其次整理本最常用形）归并。

产出只收「有异体故事」的组：书里刻了 ≥2 种形、或刻了非 canonical 的形、或有转换记录。
关系图里没有边的转换对（㫖→旨 这类 UCV 认同形、己/巳 这类文意改判）单列
``unknown_pairs``——那是 §3.3 说的「三选一」审队列的种子。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.variant_ledger import (DEFAULT_EDITION, SCHEMA_VERSION,  # noqa: E402
                                         han_counter, ledger_path)
from open_guji_cv.variants import (BRIDGE_SOURCES, NEVER_SOURCES,  # noqa: E402
                                   SIMPLIFIED_SOURCES, T2_SOURCES, VariantGraph)

DEFAULT_CORPUS = "corpus/zongmu_wuyingdian_reference.txt"
DEFAULT_DB = "output/glyph.db"
#: 分组时走的边：异体 + 互通 + 简繁（简繁边只用来把 无/無 这类俗字连起来，
#: 边本身是不是刻本异体由 tier 与 ref_policy 说话）。形近/通假永不走。
GROUP_SOURCES = BRIDGE_SOURCES | T2_SOURCES | SIMPLIFIED_SOURCES

_AUTO_CHANNELS_WITH_READING = {"dual", "match_ref", "match_replace",
                               "match_ref_weak", "match_margin"}


# ── 采集 ─────────────────────────────────────────────────

def collect_products(books: list[str]) -> tuple[Counter, dict, int]:
    """v2 seed_admit 产物 → (刻本形计数, 转换对, 记录数)。

    只数 ``admit=True`` 的：人审位还没定字。转换对键 (char, reading)，值带通道与首例。
    """
    from open_guji_cv.products import kinds as _k  # noqa: F401  注册产物种类
    from open_guji_cv.products.store import ProductStore

    st = ProductStore()
    forms: Counter = Counter()
    pairs: dict[tuple[str, str], dict] = {}
    n = 0
    for book in books:
        try:
            keys = st.keys(book, "seed_admit")
        except Exception:
            keys = []
        for k in keys:
            raw = st.read_raw(book, "seed_admit", k)
            if not raw:
                continue
            pa = raw.get("seed_admit") or raw
            for col in pa.get("columns", []):
                for rec in col.get("chars", []):
                    n += 1
                    if not rec.get("admit") or not rec.get("char"):
                        continue
                    ch = rec["char"]
                    forms[ch] += 1
                    rd = rec.get("reading")
                    if rd and rd != ch:
                        p = pairs.setdefault((ch, rd), {"n": 0, "channels": Counter(),
                                                        "first": rec.get("id", "")})
                        p["n"] += 1
                        p["channels"][rec.get("channel") or "?"] += 1
    return forms, pairs, n


def collect_glyph_db(path: Path) -> tuple[dict[str, Counter], dict, int]:
    """glyph.db → (形 → 按 provenance 的计数, 人确认的转换对, 实例数)。

    人裁转换两种写法：新的事件式 ``evidence.shape/reading``（conversion=1），
    旧的改判式 ``evidence.correction.old_char/new_char``（字形照录 label，释读改
    ``admissions.char``）。两种都按 (label, admissions.char) 取——label 是刻本形，
    ``admissions.char`` 是文意。
    """
    if not path.exists():
        return {}, {}, 0
    db = sqlite3.connect(str(path))
    forms: dict[str, Counter] = defaultdict(Counter)
    pairs: dict[tuple[str, str], dict] = {}
    n = 0
    sql = ("select i.instance_id, i.label, a.char, a.provenance, a.evidence "
           "from instances i join admissions a using(instance_id) "
           "where i.label is not null")
    for iid, label, char, prov, ev in db.execute(sql):
        n += 1
        forms[label][prov or "?"] += 1
        forms[label]["db"] += 1
        if prov != "human" or not char or char == label:
            continue
        # 人裁且 释读≠字形：一次转换。单个拉丁字母是键盘误入（x/y/z/s 那 4 条），跳过
        if len(char) != 1 or not han_counter(char):
            continue
        p = pairs.setdefault((label, char), {"n": 0, "first": iid})
        p["n"] += 1
    db.close()
    return forms, pairs, n


# ── 分组 ─────────────────────────────────────────────────

#: 整理本「多形」的门槛：第二个形至少印这么多次，且不低于组内总频次的 1%。
#: 皍 ×1 对 即 ×563 是整理本的孤例（多半错字），不能让它把整组变成 multi；
#: 无 41 / 無 1370（3%）、攷 31 / 考 1256（2.4%）才是整理本真的在区分。
REF_MULTI_MIN = 2
REF_MULTI_FRAC = 0.01

#: 整理本两形都用到这个次数以上 → 不是同词异写，别并组（见 build_groups.ref_distinguishes）。
#: 实测分界很干净：真异体组绝大多数一边是 0（整理本只用一个形），
#: 而通假/简繁误合并的那批最小的一边也有 52（乾/干）。
REF_BOTH_MIN = 50
#: 例外：整理本自己就在混用的真异体对，不受上面那道闸约束。
#: 巳/已 是用户 2026-09-04 定的「字形与文意分开」三字之一（本就该同组，靠 needsReading 分流）；
#: 彛/彝 是同一个字的两种写法，整理本两种都印（60 / 180）。
REF_BOTH_EXEMPT = frozenset({frozenset("巳已"), frozenset("彛彝"),
                             frozenset("己已"), frozenset("己巳")})


def ref_policy_of(refs: dict[str, int]) -> tuple[str, list[str]]:
    """(single | multi | none, 被当孤例忽略的形)。"""
    total = sum(refs.values())
    floor = max(REF_MULTI_MIN, int(total * REF_MULTI_FRAC))
    major = [m for m, n in refs.items() if n >= floor]
    minor = [m for m, n in refs.items() if 0 < n < floor]
    if len(major) >= 2:
        return "multi", minor
    if any(n > 0 for n in refs.values()):
        return "single", minor
    return "none", minor


def build_groups(g: VariantGraph, book_forms: set[str], ref: Counter,
                 pairs: set[tuple[str, str]]) -> dict[str, set[str]]:
    """书内每个形 → 一跳 **T1** 邻居（只留本书或整理本出现过的）→ 按 canonical 归并；
    再把**人裁确认过**转换的 T2 邻居并进来。

    只走 T1 是刻意的（第一版走了 hydzd/T2 边，廳 把 聽 拉进来、歷 把 曆/厲 拉进来，
    297 组里 291 组成了「整理本多形」——那是不同的词，不是同词异形）。T2 对
    （注/註、鍾/鐘、已/巳）两头都是正字，整理本在区分它们，只有本书**记过转换**
    才有资格同组（variant_strategy.md §3.1「账本确认的 T2 对」）。

    ⚠️ 那条「记过转换」必须是**人裁**的（2026-09-06 修）。原来 prod_pairs（管线自动
    转换）也算数，于是形成正反馈：dual/match_replace 通道把刻本的「注」按整理本写成
    「註」→ 产生 2 条 auto 转换记录 → 下次建账把 注/註 并成一组、preferred=註 →
    整理本印「注」的 60 个字位有 58 个卡在人审（97%），而「註」只有 28%。
    机器自己的错误不能反过来当合并的证据；人裁没确认过的 T2 对，两个字各自成组。
    """
    attested = lambda c: c in ref or c in book_forms  # noqa: E731

    def twedu_claims(x: str, y: str) -> bool:
        """教育部字典把 y 指认为 x 的正字（或反过来）。"""
        return any(r == y and "twedu" in t for r, t in g.regulars_of(x)) \
            or any(r == x and "twedu" in t for r, t in g.regulars_of(y))

    def ref_distinguishes(x: str, y: str) -> bool:
        """整理本自己在区分这两个形——它俩各自都是本书的常用字，不是同词异写。

        2026-09-06 加。中/仲、正/政、女/汝、常/裳 这些经 hydzd（含 hydzd-borrowed
        通假）连成 T1，被并成一组；但整理本里 中 1438 次、仲 151 次，两个字都在用、
        分工明确。整理本是本书的独立文本证据，它区分的字，刻本层面也该区分——
        合并的代价是 preferred 会把其中一个压成人审（注/註 实测 97% vs 28%）。

        门槛取「两形都 ≥ REF_BOTH_MIN 次」：真异体不会两头都这么高频
        （厯 0 / 歷 119、㫖 0 / 旨 73——整理本只用其中一个形）。
        REF_BOTH_EXEMPT 里的对是整理本自己就在混用的真异体，不受这道闸约束。
        """
        if frozenset((x, y)) in REF_BOTH_EXEMPT:
            return False
        return ref.get(x, 0) >= REF_BOTH_MIN and ref.get(y, 0) >= REF_BOTH_MIN

    def members(f: str) -> set[str]:
        out = {f}
        for b, tags in g.variants_of(f):
            if not (set(tags) & GROUP_SOURCES) or not attested(b):
                continue
            if ref_distinguishes(f, b):
                continue
            tier = g.edge_tier(f, b)
            # T1 直接进；T2 里有一种是先验被噪声抬上去的：twedu 明明白白说 卽 是 即 的
            # 异体，只因 hydzd 又给 卽 挂了个 堲 当正字，一形多正 → T2。教育部的有向
            # 指认比 hydzd 的一条边硬，采信它——但两头都是教育部正字（註/注、三/參）
            # 仍不进，那是真的两个词。
            if tier == "T1" or (tier == "T2" and twedu_claims(f, b)
                                and not (g.is_regular(f) and g.is_regular(b))):
                out.add(b)
        return out

    def canonical(f: str, mem: set[str]) -> str:
        # 教育部指认的正字在组里 → 它；多个 → 整理本更常用的
        regs = [r for r, tags in g.regulars_of(f) if "twedu" in tags and r in mem]
        if len(regs) == 1:
            return regs[0]
        if regs:
            return max(regs, key=lambda c: (ref.get(c, 0), -ord(c)))
        if g.is_regular(f):
            return f
        # 没人指认：整理本里最常用的成员；都没有 → 自己
        best = max(mem, key=lambda c: (ref.get(c, 0), c == f, -ord(c)))
        return best if ref.get(best, 0) > 0 else f

    # 每个形可能被几个组头认领（叁 既是 三 的异体也是 參 的异体）。**不并组**——
    # 并了就是连通分量，叁 会把 三 和 參 串成一团（异体关系不传递）。每个形只归
    # 一个头：twedu 指认唯一的那个 > 整理本更常用的头 > 码位小的。
    claims: dict[str, set[str]] = defaultdict(set)
    for f in sorted(book_forms):
        mem = members(f)
        canon = canonical(f, mem)
        for m in mem | {canon}:
            claims[m].add(canon)

    def pick_head(m: str, heads: set[str]) -> str:
        if m in heads:
            return m
        if len(heads) == 1:
            return next(iter(heads))
        tw = [r for r, tags in g.regulars_of(m) if "twedu" in tags and r in heads]
        if len(tw) == 1:
            return tw[0]
        return max(heads, key=lambda h: (ref.get(h, 0), -ord(h)))

    groups: dict[str, set[str]] = defaultdict(set)
    for m, heads in claims.items():
        h = pick_head(m, heads)
        groups[h].add(m)
        groups[h].add(h)

    # 有转换记录的 T2 对：两头都是正字但本书确实这么转过（註→注、巳→已）。
    # 只在这一处允许并组——由本书的记录驱动，不会沿字典边链式传播。
    own = {m: c for c, ms in groups.items() for m in ms}
    for s, r in sorted(pairs):
        if g.edge_tier(s, r) != "T2" or s not in own:
            continue
        if r in own and own[r] != own[s]:
            # 并进**文意那边**的组：reading 是整理本形，组头该是它（歷 而不是 厯）
            src, dst = own[s], own[r]
            groups[dst] |= groups.pop(src)
            own = {m: c for c, ms in groups.items() for m in ms}
        elif r not in own:
            groups[own[s]].add(r)
            own[r] = own[s]
    return {c: ms for c, ms in groups.items() if len(ms) >= 1}


def main() -> int:
    ap = argparse.ArgumentParser(description="构建本书用字账")
    ap.add_argument("--edition", default=DEFAULT_EDITION)
    ap.add_argument("--books", default="vol01,vol02")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--glyph-db", default=DEFAULT_DB)
    ap.add_argument("--variants", default=None, help="variants.json 路径（默认仓内）")
    ap.add_argument("--out", default=None, help="输出路径（默认 config/variants/books/<edition>.json）")
    ap.add_argument("--dry-run", action="store_true", help="只打印摘要不写文件")
    a = ap.parse_args()
    books = [b.strip() for b in a.books.split(",") if b.strip()]

    g = VariantGraph.load(a.variants)
    corpus_path = REPO / a.corpus if not Path(a.corpus).is_absolute() else Path(a.corpus)
    ref = han_counter(corpus_path.read_text(encoding="utf-8")) if corpus_path.exists() else Counter()

    prod_forms, prod_pairs, n_prod = collect_products(books)
    db_forms, human_pairs, n_db = collect_glyph_db(REPO / a.glyph_db)

    book_forms = set(prod_forms) | set(db_forms)
    # 转换对的目标（整理本形）也进组：髮 即便从没刻过也要在组里露面
    all_pairs = set(prod_pairs) | set(human_pairs)
    for (_c, r) in all_pairs:
        book_forms.add(r)
    # 并组只认**人裁**确认过的 T2 对（见 build_groups 的说明）。all_pairs 仍是全集，
    # 用来出 forms/pairs 的账面数字与 unknown_pairs 队列——那是「记录」，不是「依据」。
    groups = build_groups(g, book_forms, ref, set(human_pairs))
    form_index = {m: c for c, ms in groups.items() for m in ms}

    out_groups: dict[str, dict] = {}
    unknown: list[dict] = []

    def _pair_rec(shape: str, reading: str) -> dict:
        pp = prod_pairs.get((shape, reading), {})
        hp = human_pairs.get((shape, reading), {})
        rec = {
            "n": int(pp.get("n", 0)) + int(hp.get("n", 0)),
            "human": int(hp.get("n", 0)),
            "auto": int(pp.get("n", 0)),
            "channels": dict(sorted(pp.get("channels", Counter()).items())),
            "first": hp.get("first") or pp.get("first") or "",
            "sources": list(g.sources_of(shape, reading)),
        }
        return rec

    for canon, mem in groups.items():
        forms: dict[str, dict] = {}
        for m in sorted(mem):
            bc = db_forms.get(m, Counter())
            book = {"products": int(prod_forms.get(m, 0)),
                    "db": int(bc.get("db", 0)),
                    "human": int(bc.get("human", 0)),
                    "align": int(bc.get("align", 0))}
            forms[m] = {
                "book": book,
                "ref": int(ref.get(m, 0)),
                "tier": None if m == canon else g.edge_tier(m, canon),
                "sources": [] if m == canon else list(g.sources_of(m, canon)),
            }
        pairs = {f"{s}→{r}": _pair_rec(s, r)
                 for (s, r) in sorted(all_pairs)
                 if form_index.get(s) == canon and form_index.get(r) == canon}
        carved = {m: (forms[m]["book"]["products"] + forms[m]["book"]["db"]
                      - forms[m]["book"]["align"])
                  for m in forms}
        carved_pos = {m: n for m, n in carved.items() if n > 0}
        has_story = (len(carved_pos) >= 2
                     or any(m != canon for m in carved_pos)
                     or bool(pairs))
        if not has_story:
            continue
        policy, minor = ref_policy_of({m: forms[m]["ref"] for m in forms})
        # preferred 人裁优先（2026-09-06 改）：products 计数含机器写错的形——變 组 products 52
        # 全是 dual 通道把整理本形当刻本形，人裁 8 次全是 𠮓，按刻次多数选就选错。
        # 有人确认过的形先按人裁次数比，没人确认的才看刻次。
        preferred = (max(carved_pos, key=lambda m: (forms[m]["book"]["human"], carved_pos[m], -ord(m)))
                     if carved_pos else canon)
        out_groups[canon] = {
            "canonical": canon,
            "members": sorted(mem),
            "forms": forms,
            "pairs": pairs,
            "ref_policy": policy,
            "ref_minor": minor,          # 整理本里的孤例形，判 policy 时忽略
            "preferred": preferred,
        }

    for (s, r) in sorted(all_pairs):
        if form_index.get(s) is not None and form_index.get(s) == form_index.get(r):
            continue
        rec = _pair_rec(s, r)
        rec.update({"shape": s, "reading": r,
                    "why": "no_edge" if not rec["sources"] else "different_groups"})
        unknown.append(rec)

    n_single = sum(1 for x in out_groups.values() if x["ref_policy"] == "single")
    n_multi = sum(1 for x in out_groups.values() if x["ref_policy"] == "multi")
    doc = {
        "meta": {
            "schema": SCHEMA_VERSION,
            "edition": a.edition,
            "books": books,
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "inputs": {"products_records": n_prod, "glyph_db_instances": n_db,
                       "corpus_tokens": int(sum(ref.values())), "corpus_types": len(ref),
                       "book_forms": len(book_forms)},
            "stats": {"groups": len(out_groups), "ref_single": n_single,
                      "ref_multi": n_multi,
                      "ref_none": len(out_groups) - n_single - n_multi,
                      "pairs": sum(len(x["pairs"]) for x in out_groups.values()),
                      "unknown_pairs": len(unknown)},
            "note": "只由 scripts/build_book_variants.py 派生，永不手编。"
                    "book 计数分来源：human > products/db > align（align 是整理本形，别信）。",
        },
        "groups": dict(sorted(out_groups.items())),
        "unknown_pairs": unknown,
    }

    # 摘要
    print(f"用字账 {a.edition}：组 {len(out_groups)}（整理本单形 {n_single} / 多形 {n_multi}），"
          f"转换对 {doc['meta']['stats']['pairs']}，关系图外 {len(unknown)}；"
          f"输入：产物 {n_prod} 条、glyph.db {n_db} 例、书内形 {len(book_forms)}")
    top = sorted(out_groups.values(),
                 key=lambda x: -sum(p["n"] for p in x["pairs"].values()))[:12]
    for x in top:
        ps = "  ".join(f"{k} ×{v['n']}(人{v['human']})" for k, v in x["pairs"].items())
        fs = " ".join(f"{m}{x['forms'][m]['book']['db'] + x['forms'][m]['book']['products']}"
                      for m in x["members"])
        print(f"  {x['canonical']}  [{x['ref_policy']}]  形 {fs}  | {ps}")
    if unknown:
        print("  关系图外的转换对：" + "  ".join(
            f"{u['shape']}→{u['reading']}×{u['n']}({u['why']})" for u in unknown[:12]))

    if a.dry_run:
        return 0
    out = Path(a.out) if a.out else ledger_path(a.edition)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=False) + "\n",
                   encoding="utf-8")
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
