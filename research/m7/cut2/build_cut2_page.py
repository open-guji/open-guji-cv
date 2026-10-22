# -*- coding: utf-8 -*-
"""M7 异体字组 U-Net 切分：一条切线标注页（机器预填、没把握标黄，人只改错的）。壳同 skill review-artifact。

    python research/m7/cut2/build_cut2_page.py <cards.json> <out.html> --key m7-cut2-b1 --title 标题

cards.json：[{id, group, form, orient('h'|'v'), pre:[[x,y],…](机器预填折线，归一化左上原点), warn: bool, note, img: 'data:image/png;base64,…'}]
裁决值 `poly:[[点…],[]]`（第一条是切线；点 h 按 x 排序、v 按 y 排序）；`idk` 看不清；`bad` 图不对。
复用 build_cutline_page 的壳与脚本，打补丁改成「一条线、按卡方向」。
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_cutline_page as B

js = B.PAGE_JS
def sub(a, b, count=1):
    global js
    assert a in js, a[:70]
    js = js.replace(a, b) if count == 0 else js.replace(a, b, count)

TITLE_JS = "__T__"
sub("const complete = id => { const p = plOf(id); return p[0].length >= 2 && p[1].length >= 2; };",
    "const complete = id => plOf(id)[0].length >= 2;\nconst orientOf = id => { const r = D.rows.find(x => x.id === id); return (r && r.orient) || 'h'; };")
# 折线：h 两端水平延伸；v 两端竖向延伸
sub("""  const svg = p.map((pts,k)=> pts.length<2 ? '' :
    `<polyline class="pl b${k}" points="${[[0,pts[0][1]],...pts,[1,pts[pts.length-1][1]]].map(q=>(q[0]*100).toFixed(2)+','+(q[1]*100).toFixed(2)).join(' ')}"/>`).join('');""",
"""  const vv = orientOf(id) === 'v';
  const svg = p.slice(0,1).map((pts,k)=> pts.length<2 ? '' :
    `<polyline class="pl b${k}" points="${(vv ? [[pts[0][0],0],...pts,[pts[pts.length-1][0],1]] : [[0,pts[0][1]],...pts,[1,pts[pts.length-1][1]]]).map(q=>(q[0]*100).toFixed(2)+','+(q[1]*100).toFixed(2)).join(' ')}"/>`).join('');""")
sub("const dots = p.map(", "const dots = p.slice(0,1).map(")
# 排序键
sub("p[k].push(q); p[k].sort((a,b)=>a[0]-b[0]);", "p[k].push(q); { const s = orientOf(id) === 'v' ? 1 : 0; p[k].sort((a,b)=>a[s]-b[s]); }")
sub("p.forEach(a=>a.sort((x,y)=>x[0]-y[0])); drag = null;", "{ const s = orientOf(id) === 'v' ? 1 : 0; p.forEach(a=>a.sort((x,y)=>x[s]-y[s])); } drag = null;")
# 去掉红/蓝选择；撤销文案；卡片紧凑、警示黄
sub('''<div class="seg2"><button class="b0" data-act="0" aria-pressed="${a===0}">① 画 上/中 线（红）</button>
      <button class="b1" data-act="1" aria-pressed="${a===1}">② 画 中/下 线（蓝）</button></div>''', "")
sub("撤销当前线的上一点", "撤销一点")
sub("这张全部重画", "重画")
sub("✓ 机器画得对，采纳", "✓ 对，采纳")
sub('${r.auto && !v ?', '${r.pre && !v ?')
sub('<article class="card" data-id="${r.id}"${v?` data-v="${v.split(\':\')[0]}"`:\'\'}>', '<article class="card" data-id="${r.id}" data-w="${r.warn?1:0}"${v?` data-v="${v.split(\':\')[0]}"`:\'\'}>')
sub("<h3>${esc(r.title)}</h3><p>${esc(r.note)}</p>", "<h3>${esc(r.title)}${r.warn?' <span class=\"wn\">⚠ 没把握</span>':''}</h3><p>${esc(r.note)}</p>")
sub("else if (verdictOf(id).startsWith('poly:')){", "else if (verdictOf(id).startsWith('poly:')){")
# 裁决导出：一条线
sub("""return JSON.stringify(v.startsWith('poly:') ? {id:r.id, verdict:'poly', upper_mid: JSON.parse(v.slice(5))[0], mid_lower: JSON.parse(v.slice(5))[1]} : {id:r.id, verdict:v});""",
    """return JSON.stringify(v.startsWith('poly:') ? {id:r.id, verdict:'poly', orient:orientOf(r.id), cut: JSON.parse(v.slice(5))[0]} : {id:r.id, verdict:v});""")
# 介绍
i0 = js.index('<details class="intro"'); i1 = js.index('</details>') + len('</details>')
js = js[:i0] + ('<details class="intro" id="intro" open><summary>怎么点</summary>'
    '<p>每张图是一个字块，要在字的<b>两个部件之间</b>切一刀。绿线是机器<b>已经预画好</b>的切线（横向字块：线从左到右；左右结构：线从上到下）。'
    '<b>对就点「✓ 对，采纳」；不对就拖点（点可拖，点图空白处加点），拖完自动算数</b>。标「⚠ 没把握」的是机器自己不确定的，请重点看。'
    '图不对／看不清点下面的按钮。</p></details>') + js[i1:]
CSS = B.CSS + """
.cv{width:100%;max-width:150px;aspect-ratio:auto}.cv img{height:auto}
.cv .pl.b0{stroke:#1f9d55;stroke-width:2.5}.cv .dot.b0{background:#1f9d55;width:14px;height:14px;margin:-7px 0 0 -7px}
.card{padding:8px 9px}.card h3{font-size:14px}.card p{margin:3px 0 0;font-size:12px}
.card[data-w="1"]{border-left-color:var(--ochre);background:color-mix(in srgb,var(--ochre) 10%,var(--surface))}
.wn{font-size:12px;color:var(--ochre);font-weight:600}
.tools button,.verdicts button{min-height:38px}
.list{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:8px}
"""

def main():
    cards = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
    title, key = arg("--title", "切线标注"), arg("--key", "m7-cut2")
    rows, imgs = [], {}
    for c in cards:
        imgs[c["id"]] = c["img"]
        if len(c["pre"]) > 5:       # 预填点太密手机上难拖，抽成 5 点
            ix = sorted({round(i * (len(c["pre"]) - 1) / 4) for i in range(5)})
            c["pre"] = [c["pre"][i] for i in ix]
        rows.append({"id": c["id"], "img": c["id"], "title": f"{c['group']} {c['id']}", "orient": c["orient"],
                     "pre": [[[round(x, 4), round(y, 4)] for x, y in c["pre"]], []], "warn": bool(c.get("warn")),
                     "note": c.get("note", "")})
    page = js.replace(B.TITLE, title)
    html = B.render(title, key, verdicts={}, css=CSS, page_js=page, payload={"rows": rows, "imgs": imgs})
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {len(html)/1024:.0f} KB  {len(rows)} 卡")

if __name__ == "__main__":
    main()
