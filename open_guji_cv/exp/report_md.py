# -*- coding: utf-8 -*-
"""`report.json` → 人看的 `report.md`。只排版，不再算任何数。"""
from __future__ import annotations

SCOPE_ZH = {"body": "正文", "nonbody": "非正文", "unknown": "页型未知", "all": "全部"}
METRIC_ZH = {"admit_rate": "放行率", "review_rate": "送审率", "excluded_rate": "排除率",
             "admit_err_rate": "放行错误率（random 标签）"}
FLIP_ZH = {"admit_to_review": "放行→送审", "review_to_admit": "送审→放行", "char_changed": "两边放行、字不同",
           "right_to_wrong": "A 对 B 错（新增放行错）", "wrong_to_right": "A 错 B 对（消除放行错）"}
SHOW_CELLS = 20


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.2f}%"


def _pp(x) -> str:
    return "—" if x is None else f"{x * 100:+.2f}pp"


def _ci(ci) -> str:
    return "—" if not ci else f"[{ci[0] * 100:+.2f}, {ci[1] * 100:+.2f}]pp"


def _metric_rows(blk: dict) -> list[str]:
    out = []
    for m, zh in METRIC_ZH.items():
        b = blk[m]
        if m == "admit_err_rate":
            if b["no_power"]:
                out.append(f"| {zh} | 无检验力（A 有标签 {b['A_n']} 格，B {b['B_n']} 格）| | | |")
                continue
            a = f"{_pct(b['A'])} ({b['A_k']}/{b['A_n']})"
            v = f"{_pct(b['B'])} ({b['B_k']}/{b['B_n']})"
        else:
            a, v = f"{_pct(b['A'])} ({b['A_k']})", f"{_pct(b['B'])} ({b['B_k']})"
        ci = b["ci"]
        noise = ("" if ci is None else "　两边无差异" if ci[0] == ci[1] == 0
                 else "　与噪声不可分" if b["noise"] else "")
        out.append(f"| {zh} | {a} | {v} | {_pp(b['diff'])} | {_ci(b['ci'])}{noise} |")
    return out


def render(rep: dict) -> str:
    base = rep["base"]
    L = [f"# 实验 {rep['name']}", "",
         f"- 基线 **{base}**；变体 {', '.join('**' + v + '**' for v in rep['comparisons'])}",
         f"- 书：{', '.join(rep['books'])}；跑 {' → '.join(rep['steps'])}；代码 `{rep.get('code_rev') or '?'}`",
         f"- 快照：`{rep.get('snapshot')}`",
         f"- 参数覆盖：" + "；".join(f"{v}=`{p}`" for v, p in rep["params"].items()),
         f"- 评测口径：`{rep['eval_params']}`（各变体相同）",
         f"- 统计：区间是以**页**为簇的配对自助法 95% CI（{rep['bootstrap']} 次，种子 {rep['seed']}）；"
         f"区间跨 0 标「与噪声不可分」", ""]
    lab = rep["labels"]
    L += ["## 标签", "",
          f"共 {lab['n']} 格：random {lab['random']}、picked {lab['picked']}；产物里找不到的 {lab['nocell']}；"
          f"来源冲突 {lab['conflicts']}。", "",
          "| 来源 | 文件 | 格数 | random | picked |", "|---|---|---|---|---|"]
    for s in lab["sources"]:
        L.append(f"| {s['source']} | {s.get('path') or ''} | {s['n']} | {s['random']} | {s['picked']} |")
    L += ["", "> ⚠ **picked 是被挑过的样本**（审查队列、请审单、看图穷举出的错例）：只报计数，"
          "不进错误率。错误率只用 random 标签。", ""]

    for vn, comp in rep["comparisons"].items():
        L += [f"## {base} vs {vn}", ""]
        if comp["only_in_base"] or comp["only_in_variant"]:
            L += [f"⚠ 两边格集合不一致：只在 {base} {comp['only_in_base']} 格，只在 {vn} {comp['only_in_variant']} 格"
                  "（上游不同？只比两边都有的格）", ""]
        for sc, blk in comp["overall"].items():
            L += [f"### 总体 · {SCOPE_ZH.get(sc, sc)}（{blk['cells']} 格 / {blk['pages']} 页）", "",
                  f"| 指标 | {base} | {vn} | 差 | 95% CI |", "|---|---|---|---|---|", *_metric_rows(blk), ""]
        L += ["### 分层 · 按书（正文）", "", f"| 书 | 格 | 放行率 {base} | 放行率 {vn} | 差 | 送审率差 | 放行错误率 {base} | {vn} |",
              "|---|---|---|---|---|---|---|---|"]
        for bk, sc in comp["by_book"].items():
            b = sc["body"]
            e = b["admit_err_rate"]
            L.append(f"| {bk} | {b['cells']} | {_pct(b['admit_rate']['A'])} | {_pct(b['admit_rate']['B'])} | "
                     f"{_pp(b['admit_rate']['diff'])} | {_pp(b['review_rate']['diff'])} | "
                     f"{'无检验力' if e['no_power'] else _pct(e['A'])} | {'' if e['no_power'] else _pct(e['B'])} |")
        L += ["", "### 分层 · 按通道（放行格数；错 = random 标签上的放行错/有标签）", "",
              f"| 通道 | {base} | {vn} | 差 | {base} 错 | {vn} 错 | picked 错 {base}/{vn} |", "|---|---|---|---|---|---|---|"]
        for r in comp["by_channel"]:
            L.append(f"| {r['channel']} | {r['A']} | {r['B']} | {r['B'] - r['A']:+d} | {r['A_err']}/{r['A_judged']} | "
                     f"{r['B_err']}/{r['B_judged']} | {r['A_picked_err']}/{r['B_picked_err']} |")
        L += ["", "### 分层 · 按成因（送审格的 doubts 码，一格多码各计）", "",
              f"| 成因 | {base} | {vn} | 差 |", "|---|---|---|---|"]
        for r in comp["by_doubt"][:30]:
            L.append(f"| {r['doubt']} | {r['A']} | {r['B']} | {r['diff']:+d} |")
        L += ["", "### 逐格翻转", "", "| 类型 | 格数 | 有标签 | 细分 | 格号（前 20） |", "|---|---|---|---|---|"]
        f = comp["flips"]
        detail = {
            "admit_to_review": f"拦对 {f['admit_to_review']['caught']} / 误拦 {f['admit_to_review']['wrongly_blocked']}",
            "review_to_admit": f"放对 {f['review_to_admit']['admit_ok']} / 放错 {f['review_to_admit']['admit_err']}",
            "char_changed": (f"A对B错 {f['char_changed']['a_ok_b_err']} / A错B对 {f['char_changed']['a_err_b_ok']}"
                             f" / 都错 {f['char_changed']['both_err']}"),
            "right_to_wrong": "", "wrong_to_right": ""}
        for k, zh in FLIP_ZH.items():
            cells = ", ".join(f"`{c['cell']}`" for c in f[k]["cells"][:SHOW_CELLS])
            more = f" …共 {f[k]['n']}" if f[k]["n"] > SHOW_CELLS else ""
            L.append(f"| {zh} | {f[k]['n']} | {f[k]['labeled']} | {detail[k]} | {cells}{more} |")
        m = comp["mcnemar"]
        L += ["", "放行错逐格配对（McNemar 精确检验）："]
        for name, r in m.items():
            p = "—" if r["p"] is None else f"{r['p']:.3g}"
            tag = "（含 picked：只说明这些格上两边不同，不外推）" if name == "all" else ""
            L.append(f"- {name}：有标签 {r['n']} 格，A对B错 {r['a_ok_b_err']}、A错B对 {r['a_err_b_ok']}，p = {p}{tag}")
        L += ["", "### 判准（先写后跑）", ""]
        if not comp["guardrails"]:
            L.append("（实验配置里没写 guardrails）")
        mark = {"pass": "达标", "fail": "不达标", "unknown": "判不了", "error": "配置错"}
        for g in comp["guardrails"]:
            L.append(f"- [{mark[g['verdict']]}] {g.get('msg') or g['metric']}")
        n_pass = sum(g["verdict"] == "pass" for g in comp["guardrails"])
        L += ["", f"**结论：判准 {n_pass}/{len(comp['guardrails'])} 达标。开不开由人定。**", ""]
    return "\n".join(L) + "\n"
