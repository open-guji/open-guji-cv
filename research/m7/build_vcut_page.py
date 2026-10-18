# -*- coding: utf-8 -*-
"""M7 C3：彝组「中段左右竖切」标注页（米｜糸/分）。复用 build_cutline_page 的壳与脚本，打补丁改成一条竖折线。

    python research/m7/build_vcut_page.py <yi_560 目录> <out.html> --done verdicts42.jsonl --pred vcut_pred.json [--cards cards.jsonl]

--done：已确认的上/中、中/下折线（harvest jsonl），在图上画成灰色参照线；--pred：机器预测的竖切线 {id: [[x,y],…]}。
裁决值仍是 `poly:[[竖线点…],[]]`（第二条空），换了 KEY，不会和折线页混。点从上到下排序。
"""
from __future__ import annotations
import base64, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_cutline_page as B

TITLE = "彝组中段竖切标注"
KEY = "m7-yi560-vcut-v1"
js = B.PAGE_JS.replace(B.TITLE, TITLE)
def sub(a, b):
    global js
    assert a in js, a[:60]
    js = js.replace(a, b, 1)

sub("const complete = id => { const p = plOf(id); return p[0].length >= 2 && p[1].length >= 2; };",
    "const complete = id => plOf(id)[0].length >= 2;")
# 参照线（灰虚线）：已确认的上/中、中/下折线；竖线两端沿竖向延伸到图的上下边
sub("""  const svg = p.map((pts,k)=> pts.length<2 ? '' :
    `<polyline class="pl b${k}" points="${[[0,pts[0][1]],...pts,[1,pts[pts.length-1][1]]].map(q=>(q[0]*100).toFixed(2)+','+(q[1]*100).toFixed(2)).join(' ')}"/>`).join('');""",
"""  const row = D.rows.find(r => r.id === id), refs = (row && row.ref) || [];
  const rsvg = refs.map(pts => `<polyline class="pl ref" points="${[[0,pts[0][1]],...pts,[1,pts[pts.length-1][1]]].map(q=>(q[0]*100).toFixed(2)+','+(q[1]*100).toFixed(2)).join(' ')}"/>`).join('');
  const svg = rsvg + p.slice(0,1).map((pts,k)=> pts.length<2 ? '' :
    `<polyline class="pl b${k}" points="${[[pts[0][0],0],...pts,[pts[pts.length-1][0],1]].map(q=>(q[0]*100).toFixed(2)+','+(q[1]*100).toFixed(2)).join(' ')}"/>`).join('');""")
sub("const dots = p.map(", "const dots = p.slice(0,1).map(")
# 点按 y 从上到下排序
js = js.replace("p[k].sort((a,b)=>a[0]-b[0]);", "p[k].sort((a,b)=>a[1]-b[1]);")
js = js.replace("p.forEach(a=>a.sort((x,y)=>x[0]-y[0]));", "p.forEach(a=>a.sort((x,y)=>x[1]-y[1]));")
# 只有一条线：隐藏红/蓝选择
sub('''<div class="seg2"><button class="b0" data-act="0" aria-pressed="${a===0}">① 画 上/中 线（红）</button>
      <button class="b1" data-act="1" aria-pressed="${a===1}">② 画 中/下 线（蓝）</button></div>''', "")
sub("撤销当前线的上一点", "撤销上一点")
CSS = B.CSS + """
.cv .pl.b0{stroke:#1f9d55;stroke-width:2.5}.cv .dot.b0{background:#1f9d55}
.cv .pl.ref{stroke:#8a8575;stroke-dasharray:4 3;stroke-width:1.5}
"""
INTRO_OLD = B.PAGE_JS[B.PAGE_JS.index('<details class="intro"'):B.PAGE_JS.index('</details>') + len('</details>')]
INTRO_NEW = ('<details class="intro" id="intro" open><summary>怎么点（竖切）</summary>'
             '<p>灰色虚线是你已确认的上/中、中/下分界。现在只看<b>中段</b>（两条灰线之间）：把左边的<b>米</b>和右边的'
             '<b>糸／分</b>分开，画一条<b>绿色竖折线</b>，<b>从上到下</b>一个点一个点地点（至少 2 点，可拖）。'
             '机器已经预画了一条：对就点「采纳」，不对就拖点或「这张全部重画」。图不对／看不清点下面的按钮。</p></details>')
sub(INTRO_OLD, INTRO_NEW)

def main():
    d, out = Path(sys.argv[1]), Path(sys.argv[2])
    arg = lambda k: sys.argv[sys.argv.index(k) + 1]
    labels = {}
    for line in (d / "user_parts_labels.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line); labels[r["id"]] = r
    ids = [json.loads(l)["id"] for l in Path(arg("--cards") if "--cards" in sys.argv else "research/m7/cutline_cards.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    ref = {}
    for line in Path(arg("--done")).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if str(r.get("verdict", "")).startswith("poly:"): ref[r["id"]] = json.loads(r["verdict"][5:])
    pred = json.loads(Path(arg("--pred")).read_text(encoding="utf-8"))
    rows, imgs = [], {}
    for i in ids:
        lb = labels[i]
        imgs[i] = "data:image/png;base64," + base64.b64encode((d / "crops" / (i.replace(":", "_") + ".png")).read_bytes()).decode()
        pts = [[round(x, 4), round(y, 4)] for x, y in pred[i]] if pred.get(i) else []
        rows.append({"id": i, "img": i, "title": i, "ref": ref.get(i, []), "pre": [pts, []], "auto": True,
                     "note": f"你之前标的读法：中 {lb['mid']}（米｜右部）　｜　绿线是机器预画的竖切"})
    html = B.render(TITLE, KEY, verdicts={}, css=CSS, page_js=js, payload={"rows": rows, "imgs": imgs})
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {len(html)/1024:.0f} KB  {len(rows)} 卡")

if __name__ == "__main__":
    main()
