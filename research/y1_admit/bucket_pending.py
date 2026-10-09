# -*- coding: utf-8 -*-
"""待审按拦截原因分桶（overview#493，只量不改 steps/）。
用法：python bucket_pending.py <seed_admit 逐格导出 jsonl> <册名> [gold2.jsonl] [--md]
导出格式：id / admit / char / channel / doubts（道 A 的 vol05-admit-export 同款）。

分桶＝按优先级取「最硬」的那条原因（一格只进一桶；doubts 列表本身的先后只是产生顺序，不是因果）：
  印章遮挡 > 己已巳 > 库里没有（含乱码形）> 库护栏（conflict／never_match）> shadow_veto >
  与整理本冲突/改字（replace_align／context_vs_ref／iron_*／ref_lib_variant）> ctx_guard_ref(_blank) >
  形近（near_form）> 库 same 但准入被拦 > 库 unsure＋margin 不足 > 仅库 unsure > 其它。
另给「任一 doubt」的共现计数。vol05 标签（看图结论＋gold2，用户＞整理看图＞看图结论）里：
默认字（导出里的 char）＝标签字 记「默认字对」（看图判其实可放），≠ 记「默认字错」，标签 unsure/无字记「看不清」。"""
import json, sys, re, collections, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ex_f, book = sys.argv[1:3]
gold_f = next((a for a in sys.argv[3:] if a.endswith(".jsonl")), None)
ex = [json.loads(l) for l in open(ex_f, encoding="utf-8")]
pend = [d for d in ex if not d["admit"]]
norm = lambda x: re.sub(r"[（(].*", "", x)

ORDER = [
    ("印章遮挡", lambda s: "occluded" in s),
    ("己已巳", lambda s: "ji_yi_si_ctx_review" in s or "ji_yi_si_review" in s),
    ("库里没有（含乱码形）", lambda s: "库里没有这个字" in s or "ctx_garble_shape" in s or "ctx_garble_rare" in s),
    ("库护栏 conflict/never_match", lambda s: any(x.startswith("护栏") for x in s)),
    ("shadow_veto", lambda s: "shadow_veto" in s),
    ("与整理本冲突/改字", lambda s: bool(s & {"replace_align", "context_vs_ref", "iron_vs_ref", "ref_lib_variant", "iron_confusable_ref"})),
    ("ctx_guard_ref(_blank)", lambda s: bool(s & {"ctx_guard_ref", "ctx_guard_ref_blank"})),
    ("形近 near_form", lambda s: "near_form" in s),
    ("库 same 但准入被拦", lambda s: "库 same 但准入被拦" in s),
    ("库 unsure＋margin 不足", lambda s: "库 unsure" in s and "上下文 margin 不足" in s),
    ("仅库 unsure", lambda s: "库 unsure" in s),
    ("glyph_timeout", lambda s: "glyph_timeout" in s or "护栏:timeout" in s),
]


def bucket(d):
    s = {norm(x) for x in d["doubts"]}
    for name, f in ORDER:
        if f(s):
            return name
    return "其它:" + "|".join(sorted(s))[:30]


T = {}
if gold_f:
    from lib import labels
    tr = lambda g: g["shown"] if g["v"] == "ok" else (g.get("char") if g["v"] == "wrong" else None)
    for k, g in labels(book).items():
        T[k] = (tr(g), "看图")
    for l in open(gold_f, encoding="utf-8"):
        g = json.loads(l)
        T[g["cell"]] = (tr(g), "人裁" if g.get("src") == "用户" else "看图")

B = collections.defaultdict(lambda: collections.Counter())
for d in pend:
    b = bucket(d)
    B[b]["n"] += 1
    if T and d["id"] in T:
        t, src = T[d["id"]]
        B[b]["lab"] += 1
        if t is None:
            B[b]["unsure"] += 1
        elif t == d["char"]:
            B[b]["ok"] += 1; B[b]["ok_" + src] += 1
        else:
            B[b]["bad"] += 1
N = len(pend)
print(f"{book} 待审 {N}（放行 {len(ex)-N}）")
print("桶｜格数｜占待审%｜有标签｜默认字对(可放)｜默认字错(难)｜看不清" if T else "桶｜格数｜占待审%")
for b, c in sorted(B.items(), key=lambda kv: -kv[1]["n"]):
    row = f"{b}｜{c['n']}｜{100*c['n']/N:.1f}%"
    if T:
        row += f"｜{c['lab']}｜{c['ok']}｜{c['bad']}｜{c['unsure']}"
    print(row)
call = collections.Counter()
for d in pend:
    for x in {norm(y) for y in d["doubts"]}:
        call[x] += 1
print("任一 doubt 共现：", "；".join(f"{k} {v}" for k, v in call.most_common(20)))
