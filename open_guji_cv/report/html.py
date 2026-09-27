# -*- coding: utf-8 -*-
"""9.3 报告的 HTML 视图：从 JSON 正本渲染，**不重算**。

设计见 `overview` 仓 `Step9-结果整理/04-与整理本对比校验.md` §三·5。
跟原型 `scripts/build_collation_report.py::render` 的两点不同：

1. **吃 JSON 不吃产物**——正本是 `run.collate_book()` 的输出，HTML 与控制台
   tab 从同一份数据渲染，两处不会漂移；
2. **每条差异带深链**，点过去落到控制台对应的格/列（04 卡 §二·4）：
   字符类 → Step7 该页该格；增删/列结构 → Step3 该页该列。

截条图暂不内嵌（原型那套 `strip_b64` 要读原图、全册 2.1 MB）。先把
**能跳过去看原图**这条路打通——用户要的是「跳转到前面某一步某个格子去纠正」，
截图只是省一次点击，深链才是那件事本身。要图时再从原型搬 `strip_b64`。
"""
from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

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


def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _link(console: str, book: str, d: dict) -> str:
    """深链：字符类 → Step7 该格；增删类 → Step3 该页该列（04 卡 §二·4）。"""
    if not console:
        return ""
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
            + f"<td class='num muted'>{n_un}</td></tr>")

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
    vsec = ""
    for w in ws:
        vp = summ.get(w["label"], {}).get("variant_pairs", [])
        if not vp:
            continue
        rows = "".join(f"<tr><td class='gl'>{_e(a)}</td><td class='gl'>{_e(b)}</td>"
                       f"<td class='num'>{n}</td></tr>" for a, b, n in vp[:40])
        vsec += (f"<section><h2>异体对 · {_e(w['label'])}</h2>"
                 f"<table class='t'><tr><th>刻本</th><th>整理本</th><th>次数</th></tr>{rows}</table></section>")

    # ── 人裁仍不同 ────────────────────────────────────
    hsec = ""
    for w in ws:
        hd = summ.get(w["label"], {}).get("human_disagree", [])
        if not hd:
            continue
        hsec += (f"<section><h2>人裁过仍与「{_e(w['label'])}」不同（{len(hd)}）</h2>"
                 f"<p class='note'>要回答的是<b>整理本错还是人裁错</b>，不是自动改。</p>"
                 + "".join(_entry(d, book, console) for d in hd) + "</section>")

    # ── 差异条目 ──────────────────────────────────────
    dsec = ""
    for k in DETAIL_KINDS:
        es = [d for d in diffs if d["kind"] == k]
        if not es:
            continue
        by_w = Counter(d["witness"] for d in es)
        dsec += (f"<section id='k-{_e(k)}'><h2>{_e(KIND_LABEL.get(k, k))} "
                 f"<span class='muted'>{len(es)}</span></h2>"
                 f"<p class='note'>按证人：{_e('，'.join(f'{a} {b}' for a, b in by_w.items()))}</p>"
                 + "".join(_entry(d, book, console) for d in es[:400])
                 + (f"<p class='note'>只列前 400 条，全部在 JSON 里</p>" if len(es) > 400 else "")
                 + "</section>")

    nav = "".join(f"<a href='#k-{_e(k)}'>{_e(KIND_LABEL.get(k, k))}</a>"
                  for k in DETAIL_KINDS if any(d["kind"] == k for d in diffs))

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>对勘报告 · {_e(book)}</title>
<style>{_CSS}</style></head><body>
<header><h1>对勘报告 · {_e(book)}</h1>
<p class="sub">{len(doc['pages'])} 页 · 生成 {_e(doc['built_at'])} · {_e(doc['elapsed_s'])}s
{' · <b class="warn">数据版本不同步 ' + str(len(doc['stale'])) + ' 处</b>' if doc['stale'] else ''}</p>
<nav>{nav}</nav></header>
<section><h2>证人总览</h2>
<p class="note">按质量加权，<b>不是简单多数</b>：与最好的证人不一致优先怀疑我们错。
一致数里约 85% 是「与整理本一致才放行」的回声（这些字当初就是靠它选的），
真正有信息量的是下面各类差异与人裁位。</p>
<div class="scroll"><table class="t"><tr><th>证人</th><th>质量</th><th>一致</th>
{''.join(f'<th>{_e(KIND_LABEL.get(k, k))}</th>' for k in DETAIL_KINDS)}<th>未锚定页</th></tr>
{''.join(wrows)}</table></div></section>
{colsec}{vsec}{hsec}{dsec}
<footer>JSON 正本同目录同名 .json · 深链指向 {_e(console or '（未配置控制台地址）')}</footer>
</body></html>"""


def _entry(d: dict, book: str, console: str) -> str:
    url = _link(console, book, d)
    a0 = f"<a class='jump' href='{url}'>跳去改 →</a>" if url else ""
    badge = "<span class='src human'>人裁</span>" if d.get("human") else \
            (f"<span class='src auto'>{_e(d.get('channel') or '')}</span>" if d.get("admit")
             else "<span class='src guess'>未放行</span>")
    return f"""<div class="ent">
  <div class="head"><span class="mono">{_e(d['id'])}</span> {badge}
    <span class="wit">{_e(d['witness'])}</span> {a0}</div>
  <div class="pair"><span class="k">刻本</span><span class="gl big">{_e(d['char']) or '—'}</span>
    <span class="k">整理本</span><span class="gl big">{_e(d['ref']) or '—'}</span></div>
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
footer{margin-top:36px;padding-top:12px;border-top:1px solid var(--line);
 color:var(--mut);font-size:12px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.ctx .gl,.pair .gl{overflow-wrap:anywhere}
.ent{overflow-wrap:anywhere}
@media(max-width:640px){.t{font-size:12px}.big{font-size:18px}
 .head{gap:6px}.jump{margin-left:0}}
"""


def write_html(doc: dict, out: str | Path, console: str = "") -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(doc, console), encoding="utf-8")
    return out


def from_json(path: str | Path, out: str | Path | None = None, console: str = "") -> Path:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return write_html(doc, out or Path(path).with_suffix(".html"), console)
