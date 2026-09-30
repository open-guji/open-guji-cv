# -*- coding: utf-8 -*-
"""9.3 报告的 HTML 视图：从 JSON 正本渲染，**不重算**。

设计见 `overview` 仓 `Step9-结果整理/04-与整理本对比校验.md` §三·5。
跟原型 `scripts/build_collation_report.py::render` 的两点不同：

1. **吃 JSON 不吃产物**——正本是 `run.collate_book()` 的输出，HTML 与控制台
   tab 从同一份数据渲染，两处不会漂移；
2. **每条差异带深链**，点过去落到控制台对应的格/列（04 卡 §二·4）：
   字符类 → Step7 该页该格；增删/列结构 → Step3 该页该列。

## 分层 + 截条图（2026-09-27 起，`report/collation_grade.py` + `report/strips.py`）

原来只接在单证人的旧脚本 `scripts/build_collation_report.py` 上，现在按证人各自
分好的 `grade`（避諱/系统性/异体/人裁/整段错位/存疑）在这里分区渲染——「存疑」
默认展开（真正要看的只有这一档），其余是「成果」或「另计」，折叠。

截条图不再内嵌 base64（旧脚本那样做全册要 2.1 MB，焖进一个 HTML 文件）：
`report/strips.py` 把图写成 webp 文件、`Diff.strip` 存相对路径，这里直接
`<img src>`。**深链有两种去处**：给了 `console` 就跳控制台（在线改判）；
没给（离线交付包）就退到 `strip` 本身——图已经在包里，点开就是看大图，
不依赖正在跑的控制台（任务书「离线交付包」那一条）。两者都没有（既没
`console` 也没生成截图）才什么都不给，跟原来一样。
"""
from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

from .collation_grade import GRADE_LABEL

KIND_LABEL = {
    "same": "一致",
    "conv.known": "已记账的转换（旧报告；2026-09-26 取消读法后不再产生）",
    "variant.to_orthodox": "异体 → 整理本正字",
    "variant.to_simp": "异体/繁体 → 简体",
    "variant.other": "同组异形（方向不明）",
    "sub.confusable": "形近字（最可能认错）",
    "sub.other": "不同字",
    "missing": "整理本有、我们无（漏切）",
    "extra": "我们有、整理本无",
    "unreadable": "无法辨认",
}
COL_LABEL = {
    "col.ok": "列长一致",
    "col.short": "我们少字（丢格）",
    "col.long": "我们多字",
    "col.drift": "列首未对齐（抬头/标题或累积错位）",
}
#: 要人看的类（`same`/`conv.known` 不列条目，只计数）
DETAIL_KINDS = ("sub.confusable", "sub.other", "unreadable", "missing", "extra",
                "variant.other", "variant.to_simp", "variant.to_orthodox")

#: 分层小结的说明文字（`collation_grade.GRADE_LABEL` 只给标题，这里补一句「为什么」）。
GRADE_NOTE = {
    "suspect": "只出现一两次、无已知关系——最该先看这批",
    "gap": "刻本多出或整理本多出，多半是漏切/两字并一格，或整理本据他本补字",
    "taboo": "清刻本避諱改字，整理本回改原字；录刻本形是对的",
    "systematic": "同一字对全书反复出现（≥3 次），是版本用字差异而非识别错",
    "variant": "异体关系图已收，同字异形",
    "human": "人已看过这张图并定了字——这是人判定的版本差异，不是待办",
    "misanchor": "这一页与整理本对不上号（锚到了错的位置），不是逐字认错；转写本身多半是对的",
}
#: 展示顺序：存疑在最前且默认展开，其余「成果/另计」折叠。
GRADE_ORDER = ("suspect", "misanchor", "gap", "human", "taboo", "systematic", "variant")


def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _link(console: str, book: str, d: dict) -> str:
    """深链：字符类 → Step7 该格；增删类 → Step3 该页该列（04 卡 §二·4）。

    没给 `console`（离线交付包）时退到 `d["strip"]`——截图已经在包里，点开
    就是看大图，不必依赖正在跑的控制台；两者都没有才返回空串（不出链接）。
    """
    if not console:
        return d.get("strip") or ""
    base = console.rstrip("/")
    if d["kind"] in ("missing", "extra"):
        return f"{base}/{book}/step/step3/?page={d['page']}&col={d['col']}"
    return f"{base}/{book}/step/step7/?id={_e(d['id'])}"


def render(doc: dict, console: str = "") -> str:
    book = doc["book"]
    ws = doc["witnesses"]
    summ = doc["summary"]["by_witness"]
    diffs = doc["diffs"]
    cols = doc["cols"]

    # ── 证人总表 ──────────────────────────────────────
    wrows = []
    for w in ws:
        s = summ.get(w["label"], {})
        c = s.get("counts", {})
        n_un = len(doc["unanchored"].get(w["label"], []))
        wrows.append(
            f"<tr><td>{_e(w['label'])}</td><td><span class='q q-{_e(w['quality'])}'>{_e(w['quality'])}</span></td>"
            f"<td class='num'>{s.get('n_equal', 0):,}</td>"
            + "".join(f"<td class='num'>{c.get(k, 0) or ''}</td>" for k in DETAIL_KINDS)
            + f"<td class='num muted'>{n_un}</td>"
            f"<td class='num'>{s.get('n_settled', 0)}</td>"
            f"<td class='num warn'>{s.get('n_todo', 0)}</td></tr>")

    # ── 列结构（只有 line_is_column 的证人有）────────────
    colsec = ""
    for w in ws:
        cc = summ.get(w["label"], {}).get("cols", {})
        if not cc:
            continue
        rows = "".join(
            f"<tr><td>{_e(COL_LABEL.get(k, k))}</td><td class='num'>{v}</td></tr>"
            for k, v in sorted(cc.items(), key=lambda kv: -kv[1]))
        # 按丢字数排序——丢 5 个字的列比丢 1 个的值钱得多，别按页码顺序埋在中间
        bad = sorted((c for c in cols
                      if c["witness"] == w["label"] and c["kind"] == "col.short"),
                     key=lambda c: (c["delta"], c["page"], c["col"]))
        items = "".join(
            f"<a class='chip' href='{_link(console, book, {**c, 'kind': 'missing', 'id': ''})}'>"
            f"p{c['page']}·col{c['col']} <b>{c['delta']}</b></a>" for c in bad[:200])
        colsec += f"""<section><h2>列结构 · {_e(w['label'])}</h2>
<p class="note">这份证人的<b>行就是我们的列</b>（实测见 05 卡 §二）。列长不等是
<b>独立于字符对齐</b>的丢格信号——页尾那一列字符比对结构上看不见（窗口余量规则），
只有这条通道抓得到。</p>
<table class="t"><tr><th>裁定</th><th>列数</th></tr>{rows}</table>
<h3>少字的列（点击跳 Step3 该页该列）</h3><div class="chips">{items}</div></section>"""

    # ── 异体对 ────────────────────────────────────────
    all_examples = doc.get("variant_examples") or {}
    vsec = ""
    for w in ws:
        vp = summ.get(w["label"], {}).get("variant_pairs", [])
        if not vp:
            continue
        ex_by_pair = all_examples.get(w["label"], {})
        # 不在 f-string 表达式里写反斜杠：服务器是 Python 3.11，那种写法 3.12 才支持（值守 09-27 报）
        rows = ""
        for a, b, n in vp[:40]:
            imgs = "".join('<img class="th" src="' + _e(p) + '">'
                           for p in ex_by_pair.get(a + "\t" + b, []))
            rows += (f"<tr><td class='gl'>{_e(a)}</td><td class='gl'>{_e(b)}</td>"
                     f"<td class='num'>{n}</td><td>{imgs}</td></tr>")
        vsec += (f"<section><h2>异体对 · {_e(w['label'])}</h2>"
                 f"<table class='t'><tr><th>刻本</th><th>整理本</th><th>次数</th><th>例</th></tr>{rows}</table></section>")

    # ── 人裁仍不同 ────────────────────────────────────
    hsec = ""
    for w in ws:
        hd = summ.get(w["label"], {}).get("human_disagree", [])
        if not hd:
            continue
        hsec += (f"<section><h2>人裁过仍与「{_e(w['label'])}」不同（{len(hd)}）</h2>"
                 f"<p class='note'>要回答的是<b>整理本错还是人裁错</b>，不是自动改。</p>"
                 + "".join(_entry(d, book, console) for d in hd) + "</section>")

    # ── 差异条目：按层分区（2026-09-27 起，见模块头「分层 + 截条图」）──────
    # 存疑排最前且默认展开——那是唯一真正要人看的；其余是「成果」（避諱/系统性/
    # 异体/人裁）或「另计」（增删/整段错位），折叠但留着，理由是排序不是闸
    # （`collation_grade` 模块头）。同一层跨证人合并，条目自己带证人徽标。
    gsec = ""
    for g in GRADE_ORDER:
        es = [d for d in diffs if d.get("grade") == g]
        if not es:
            continue
        by_w = Counter(d["witness"] for d in es)
        render_fn = _gap_entry if g == "gap" else _entry
        inner = "".join(render_fn(d, book, console) for d in es[:400])
        trunc = "<p class='note'>只列前 400 条，全部在 JSON 里</p>" if len(es) > 400 else ""
        gsec += (f'<details id="g-{_e(g)}"{" open" if g == "suspect" else ""}>'
                 f"<summary><span class='gname'>{_e(GRADE_LABEL[g])}</span>"
                 f"<span class='muted'>{len(es)}</span>"
                 f"<span class='note' style='margin:0'>{_e(GRADE_NOTE.get(g, ''))}"
                 f"（{_e('，'.join(f'{a} {b}' for a, b in by_w.items()))}）</span></summary>"
                 f"<div class='ents'>{inner}{trunc}</div></details>")

    n_settled_all = sum(s.get("n_settled", 0) for s in summ.values())
    n_todo_all = sum(s.get("n_todo", 0) for s in summ.values())
    nav = "".join(f"<a href='#g-{_e(g)}'>{_e(GRADE_LABEL[g])}</a>"
                  for g in GRADE_ORDER if any(d.get("grade") == g for d in diffs))

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>对勘报告 · {_e(book)}</title>
<style>{_CSS}</style></head><body>
<header><h1>对勘报告 · {_e(book)}</h1>
<p class="sub">{len(doc['pages'])} 页 · 生成 {_e(doc['built_at'])} · {_e(doc['elapsed_s'])}s
{' · <b class="warn">数据版本不同步 ' + str(len(doc['stale'])) + ' 处</b>' if doc['stale'] else ''}</p>
<p class="lede">按层分：<b>{n_settled_all:,}</b> 处是两个本子的真实不同（避諱改字、正俗、异体、
人裁定字，转写忠于刻本，不用改）；真正<b>存疑待覈的只有 {n_todo_all:,} 处</b>
（各证人分开算，见下表「已定层／存疑」两列；判据见
<code>report/collation_grade.py</code>，分层是排序不是闸）。</p>
<nav>{nav}</nav></header>
<section><h2>证人总览</h2>
<p class="note">按质量加权，<b>不是简单多数</b>：与最好的证人不一致优先怀疑我们错。
一致数里约 85% 是「与整理本一致才放行」的回声（这些字当初就是靠它选的），
真正有信息量的是下面各类差异与人裁位。</p>
<div class="scroll"><table class="t"><tr><th>证人</th><th>质量</th><th>一致</th>
{''.join(f'<th>{_e(KIND_LABEL.get(k, k))}</th>' for k in DETAIL_KINDS)}<th>未锚定页</th>
<th>已定层</th><th>存疑</th></tr>
{''.join(wrows)}</table></div></section>
{colsec}{vsec}{hsec}
<section><h2>差异（按层）</h2>{gsec}</section>
<footer>JSON 正本同目录同名 .json · 深链指向 {_e(console) if console else '包内截图（离线）' if any(d.get("strip") for d in diffs) else '（未配置控制台地址，也没有截图）'}</footer>
</body></html>"""


def _entry(d: dict, book: str, console: str) -> str:
    url = _link(console, book, d)
    jump = "跳去改 →" if console else "看大图 →"
    a0 = f"<a class='jump' href='{_e(url)}'>{jump}</a>" if url else ""
    badge = "<span class='src human'>人裁</span>" if d.get("human") else \
            (f"<span class='src auto'>{_e(d.get('channel') or '')}</span>" if d.get("admit")
             else "<span class='src guess'>未放行</span>")
    strip = d.get("strip")
    img = f'<img class="strip" src="{_e(strip)}" alt="截图">' if strip else ""
    return f"""<div class="ent">
  {img}
  <div class="head"><span class="mono">{_e(d['id'])}</span> {badge}
    <span class="kind">{_e(KIND_LABEL.get(d['kind'], d['kind']))}</span>
    <span class="wit">{_e(d['witness'])}</span> {a0}</div>
  <div class="pair"><span class="k">刻本</span><span class="gl big">{_e(d['char']) or '—'}</span>
    <span class="k">整理本</span><span class="gl big">{_e(d['ref']) or '—'}</span></div>
  <div class="ctx"><span class="k">我们</span><span class="gl">{_e(d['hyp_ctx'])}</span></div>
  <div class="ctx"><span class="k">整理本</span><span class="gl">{_e(d['ref_ctx'])}</span></div>
</div>"""


def _gap_entry(d: dict, book: str, console: str) -> str:
    """增删（脱衍）**只出文字，不出图**（旧脚本 2026-09-22 定的口径，见
    `collation_grade` 模块头「另计」）：`missing` 那一侧我们压根没有格子，
    图只能显示邻近几个无关的字，帮不上忙。以我方文本为基准报，方向写清楚。"""
    url = _link(console, book, d)
    a0 = f"<a class='jump' href='{_e(url)}'>跳去改 →</a>" if url else ""
    if d["kind"] == "missing":
        verb, seg = "整理本多出", d.get("ref", "")
    else:
        verb, seg = "整理本无（刻本多出）", d.get("char", "")
    return f"""<div class="ent gap">
  <div class="head"><span class="gapverb">{_e(verb)}</span>
    <span class="gl big">{_e(seg) or '—'}</span>
    <span class="muted">{d.get('n', 1)} 字</span>
    <span class="mono">{_e(d['id'])}</span>
    <span class="wit">{_e(d['witness'])}</span> {a0}</div>
  <div class="ctx"><span class="k">我们</span><span class="gl">{_e(d['hyp_ctx'])}</span></div>
  <div class="ctx"><span class="k">整理本</span><span class="gl">{_e(d['ref_ctx'])}</span></div>
</div>"""


_CSS = """
:root{--bg:#fbfaf7;--fg:#232018;--mut:#8a8578;--line:#e2ddd2;--acc:#7a5c2e;--warn:#b4471f}
*{box-sizing:border-box}
body{margin:0;padding:0 16px 60px;background:var(--bg);color:var(--fg);
 font:14px/1.7 system-ui,"Noto Sans TC",sans-serif;max-width:1100px;margin:0 auto}
header{padding:22px 0 10px;border-bottom:2px solid var(--line);margin-bottom:8px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:17px;margin:26px 0 8px;padding-bottom:5px;border-bottom:1px solid var(--line)}
h3{font-size:14px;margin:16px 0 6px;color:var(--mut)}
.sub{color:var(--mut);margin:0}
nav{margin-top:10px;display:flex;flex-wrap:wrap;gap:6px}
nav a{font-size:12px;padding:3px 9px;border:1px solid var(--line);border-radius:11px;
 color:var(--acc);text-decoration:none;background:#fff}
nav a:hover{background:var(--acc);color:#fff}
.note{color:var(--mut);font-size:13px;margin:4px 0 10px}
.t{border-collapse:collapse;width:100%;background:#fff;font-size:13px}
.t th,.t td{border:1px solid var(--line);padding:5px 8px;text-align:left}
.t th{background:#f3efe6;font-weight:600;font-size:12px}
.num{text-align:right;font-variant-numeric:tabular-nums}
.muted{color:var(--mut)}
.warn{color:var(--warn)}
.gl{font-family:"Noto Serif TC",serif}
.big{font-size:21px;margin:0 10px 0 3px}
.q{font-size:11px;padding:1px 7px;border-radius:9px;color:#fff}
.q-best{background:#2f6b3a}.q-mid{background:#8a6b2e}.q-low{background:#9a9488}
.ent{background:#fff;border:1px solid var(--line);border-radius:7px;padding:9px 12px;margin:7px 0}
.head{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:4px}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--mut)}
.src{font-size:11px;padding:1px 7px;border-radius:9px;color:#fff}
.src.human{background:#2f6b3a}.src.auto{background:#5a7fa8}.src.guess{background:#b0a99a}
.wit{font-size:11px;color:var(--acc);border:1px solid var(--line);padding:1px 7px;border-radius:9px}
.jump{margin-left:auto;font-size:12px;color:var(--acc);text-decoration:none;
 border:1px solid var(--acc);padding:2px 9px;border-radius:11px}
.jump:hover{background:var(--acc);color:#fff}
.pair,.ctx{display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.k{font-size:11px;color:var(--mut);min-width:42px}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{font-size:12px;padding:2px 8px;border:1px solid var(--line);border-radius:10px;
 background:#fff;color:var(--acc);text-decoration:none}
.chip:hover{background:var(--acc);color:#fff}
.chip b{color:var(--warn)}
.lede{font-size:14px;line-height:1.85;margin:.4rem 0 1rem;max-width:66ch}
details{border-top:1px solid var(--line);margin:0}
details[open]{padding-bottom:10px}
summary{cursor:pointer;padding:10px 0;display:flex;align-items:baseline;gap:8px;
 flex-wrap:wrap}
summary::marker{color:var(--mut)}
.gname{font-size:15px;font-weight:700}
#g-suspect .gname{color:var(--warn)}
.ents{display:grid;grid-template-columns:repeat(auto-fill,minmax(26rem,1fr));gap:0 20px}
.ent .strip{display:block;background:#fff;border:1px solid var(--line);margin:0 0 5px;
 max-width:100%}
.kind{font-size:11px;color:var(--acc)}
.gapverb{font-size:12px;color:var(--mut)}
.th{height:48px;border:1px solid var(--line);background:#fff;margin-right:3px;
 vertical-align:middle}
footer{margin-top:36px;padding-top:12px;border-top:1px solid var(--line);
 color:var(--mut);font-size:12px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.ctx .gl,.pair .gl{overflow-wrap:anywhere}
.ent{overflow-wrap:anywhere}
@media(max-width:640px){.t{font-size:12px}.big{font-size:18px}
 .head{gap:6px}.jump{margin-left:0}.ents{grid-template-columns:1fr}}
"""


def write_html(doc: dict, out: str | Path, console: str = "") -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(doc, console), encoding="utf-8")
    return out


def from_json(path: str | Path, out: str | Path | None = None, console: str = "") -> Path:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return write_html(doc, out or Path(path).with_suffix(".html"), console)
