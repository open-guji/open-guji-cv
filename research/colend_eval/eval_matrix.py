"""B 批列端标签 × 现行 Step2 列端规则(column_border_trim 档位) 两轴评测。

输入:dataset `char-segmentation/column-end-class/items.jsonl`(取 source=L3-batch,带引擎出卡时档位快照,
      fp_match=true 即快照与点卡时产物一致)。不改 steps/*,不读页图。
用法: python3 -I eval_matrix.py <items.jsonl> [out_dir]
"""
import json, sys, re, math, collections, pathlib

def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = k / n; d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d; h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return (max(0, c-h), min(1, c+h))

def parse(case):
    letter = case[0]; layers = int(re.sub(r"\D", "", case) or 1); inner = case.endswith("i")
    return letter, layers, inner

def pred_class(case):
    """规则对这一端的"结论":b 只削 3 行=认为粘字;c 不削=认为没框;a/d/e=整段可削;多层或 i=认为有内框(双层)。"""
    letter, layers, inner = parse(case)
    if layers >= 2 or inner: return "double"
    return {"a": "trim", "d": "trim", "e": "trim", "b": "glued", "c": "none"}[letter]

def load(p):
    rows = []
    for l in open(p, encoding="utf-8"):
        d = json.loads(l)
        if d["input"]["source"] != "L3-batch": continue
        e = d["expected"]
        rows.append(dict(id=d["id"], end=e["end"], label=e["class"], case=e["engine_trim_case"],
                         px=e.get("engine_trim_px"), eclass=e.get("engine_end_class"),
                         w=d["input"].get("stratum_weight", 1), fp=d["input"].get("fp_match")))
    return rows

def table(rows, rk, ck, rl, cl):
    t = collections.Counter((rk(r), ck(r)) for r in rows)
    out = ["| 人判＼规则 | " + " | ".join(cl) + " | 合计 |", "|---|" + "---|"*(len(cl)+1)]
    for a in rl:
        n = sum(t[(a, b)] for b in cl)
        out.append(f"| **{a}** | " + " | ".join(str(t[(a, b)]) for b in cl) + f" | {n} |")
    out.append("| 合计 | " + " | ".join(str(sum(t[(a, b)] for a in rl)) for b in cl) + f" | {len(rows)} |")
    return "\n".join(out)

def main(p, outdir="."):
    rows = load(p); out = []
    P = out.append
    P(f"# 列端评测:B 批 {len(rows)} 端 × 现行 Step2 规则(数据 {p})\n")
    P(f"fp_match 全真: {all(r['fp'] for r in rows)};stratum_weight 缺省按 1(样本是分层超采样,**下列比例不是全书率**)。\n")
    for r in rows: r["pred"] = pred_class(r["case"])
    cls = ["trim", "double", "glued", "none"]
    P("## 1 四类混淆矩阵(规则结论按档位映射:a/d/e→trim;多层或 i→double;b→glued;c→none)\n")
    P(table(rows, lambda r: r["label"], lambda r: r["pred"], cls, cls)); P("")
    # 轴一:内框有无
    P("## 2 轴一:内框有无(人判 double=有内框 [含模糊]);规则=多层(层数≥2)或 i 档\n")
    for name, sub in (("全部", rows), ("下端", [r for r in rows if r["end"] == "bot"]), ("上端", [r for r in rows if r["end"] == "top"])):
        tp = sum(1 for r in sub if r["label"] == "double" and r["pred"] == "double")
        fn = sum(1 for r in sub if r["label"] == "double" and r["pred"] != "double")
        fp = sum(1 for r in sub if r["label"] != "double" and r["pred"] == "double")
        tn = sum(1 for r in sub if r["label"] != "double" and r["pred"] != "double")
        rec = wilson(tp, tp+fn); pre = wilson(tp, tp+fp)
        P(f"- {name}(n={len(sub)}):TP={tp} FN={fn} FP={fp} TN={tn};召回 {tp}/{tp+fn}={tp/max(1,tp+fn):.0%} (95%CI {rec[0]:.0%}–{rec[1]:.0%});精确 {tp}/{tp+fp}={tp/max(1,tp+fp):.0%} (CI {pre[0]:.0%}–{pre[1]:.0%})")
    P("")
    # 轴二:整段能否削 —— 限人判 trim/double(两类都"能整段削",区别只在是否要连第二道)
    P("## 3 轴二:整段能否削(trim vs double,只看人判 trim/double 的端)\n")
    sub = [r for r in rows if r["label"] in ("trim", "double")]
    P(f"n={len(sub)};规则对这些端的结论分布:\n")
    P(table(sub, lambda r: r["label"], lambda r: r["pred"], ["trim", "double"], ["trim", "double", "glued", "none"])); P("")
    cut_ok = sum(1 for r in sub if r["pred"] in ("trim", "double")); P(f"- 规则认为\"能整段削\"(trim/double 结论): {cut_ok}/{len(sub)} = {cut_ok/len(sub):.0%};漏削(规则结论 glued/none): {len(sub)-cut_ok} 端\n")
    # 分档错误表
    P("## 4 分档错误表(按规则档位字母)\n")
    P("| 档 | n | 人判 trim | double | glued | none | 与规则结论一致 |"); P("|---|---|---|---|---|---|---|")
    by = collections.defaultdict(list)
    for r in rows: by[parse(r["case"])[0]].append(r)
    for L in "abcde":
        s = by[L]
        if not s: continue
        c = collections.Counter(r["label"] for r in s); ok = sum(1 for r in s if r["label"] == r["pred"])
        P(f"| {L} | {len(s)} | {c['trim']} | {c['double']} | {c['glued']} | {c['none']} | {ok}/{len(s)}={ok/len(s):.0%} |")
    P("")
    P("## 4b 按完整档位(含层数/i)\n"); P("| 档位 | n | trim | double | glued | none |"); P("|---|---|---|---|---|---|")
    byc = collections.defaultdict(list)
    for r in rows: byc[r["case"]].append(r)
    for k in sorted(byc, key=lambda x: (parse(x)[0], parse(x)[1], parse(x)[2])):
        c = collections.Counter(r["label"] for r in byc[k]); P(f"| {k} | {len(byc[k])} | {c['trim']} | {c['double']} | {c['glued']} | {c['none']} |")
    P("")
    P("## 5 错例清单(规则结论≠人判);glued/none 只列清单不报精度\n")
    P("类型 | id | 端 | 档位 | 削行数 | triage end_class | 人判 | 规则结论"); P("---|---|---|---|---|---|---|---")
    def kind(r):
        a, b = r["label"], r["pred"]
        if a == "glued" and b in ("trim", "double"): return "漏判粘字(叠图后:削线在框下沿,未见伤字)"
        if a in ("trim", "double") and b in ("glued", "none"): return "漏削(残框)"
        if a == "double" and b == "trim": return "漏内框(少削一道)"
        if a == "trim" and b == "double": return "多削内框(trim↔double 边界,人眼也可能难分)"
        if a == "none" and b != "none": return "无框被当有框"
        if a == "glued": return "粘字被当none/b以外"
        return "其他"
    errs = [r for r in rows if r["label"] != r["pred"]]
    for r in sorted(errs, key=lambda r: (kind(r), r["case"], r["id"])):
        P(f"{kind(r)} | {r['id']} | {r['end']} | {r['case']} | {r['px']} | {r['eclass']} | {r['label']} | {r['pred']}")
    P(f"\n共 {len(errs)}/{len(rows)} 端不一致。")
    P("\n### 错例类型计数\n"); 
    for k, v in collections.Counter(kind(r) for r in errs).most_common(): P(f"- {k}: {v}")
    P("\n## 6 glued / none 清单(不报精度)\n")
    for lab in ("glued", "none"):
        P(f"- **{lab}**({sum(1 for r in rows if r['label']==lab)}): " + ", ".join(f"{r['id']}[{r['case']}→{r['pred']}]" for r in rows if r["label"] == lab))
    pathlib.Path(outdir, "mid_result.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ".")
