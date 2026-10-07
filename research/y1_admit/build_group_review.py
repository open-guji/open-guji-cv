# -*- coding: utf-8 -*-
"""字组裁决页（Y1，overview#471）：一组一卡，问「这几块图刻的是哪个字」，用户一点定一组的码位口径。
用法：python build_group_review.py <快照 products 根> <cache 根> <out.html>
组表与图例取自 gold_vol0X.jsonl（用户＞整理看图）里 shown 是变体码位的格。"""
import base64, io, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / ".claude/skills/review-artifact/scripts"))
from PIL import Image
from review_shell import render
from lib import load_step
src, cache, out = sys.argv[1:4]
GROUPS = [("𫎇", ["𫎇", "蒙"]), ("𢑴", ["𢑴", "彝"]), ("㸃", ["㸃", "點"]), ("㕘", ["㕘", "參"]), ("䜟", ["䜟", "讖", "識"]),
          ("𨽾", ["𨽾", "隸"]), ("慎", ["慎", "愼"]), ("顛", ["顛", "顚"]), ("厯", ["厯", "歷"]), ("㫖", ["㫖", "旨"]),
          ("水", ["水", "氷"]), ("官", ["官", "宮"])]
L = {}
for v in ("04", "05"):
    for l in open(HERE / f"gold_vol{v}.jsonl", encoding="utf-8"):
        d = json.loads(l); d["book"] = "vol" + v; L[d["cell"]] = d
ci = {b: load_step(src, b, "cell_shrink") for b in ("vol04", "vol05")}
rows, imgs, n = [], {}, 0
for key, members in GROUPS:
    cells = [d for d in L.values() if d["shown"] == key][:4]
    if not cells: continue
    tiles = []
    for d in cells:
        f = Path(cache) / d["book"] / "char_patch" / f"{ci[d['book']][d['cell']]['patch_key']}.png"
        im = Image.open(f).convert("L"); im.thumbnail((110, 110)); im = im.point(lambda x: (x // 16) * 16)
        b = io.BytesIO(); im.save(b, "PNG", optimize=True)
        imgs[f"i{n}"] = "data:image/png;base64," + base64.b64encode(b.getvalue()).decode(); tiles.append(f"i{n}"); n += 1
    rows.append(dict(id=f"g:{key}", key=key, members=members, tiles=tiles, cells=[d["cell"] for d in cells]))
TITLE = "字组码位裁决"
CSS = """
.card{background:var(--surface);border:1px solid var(--rule);border-left:3px solid transparent;border-radius:3px;padding:12px 13px;box-shadow:var(--shadow)}
.card[data-v]{border-left-color:var(--indigo)}
.card .tiles{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.card .tiles img{width:84px;height:84px;object-fit:contain;background:var(--tile);border-radius:2px}
.card h3{margin:0;font-family:var(--serif);font-size:20px}.card .q{font-size:13px;color:var(--muted);margin-top:4px}
.verdicts{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.verdicts button{min-height:44px;min-width:64px;padding:0 14px;border:1px solid var(--rule-hard);border-radius:3px;background:var(--surface);color:var(--ink);font-size:20px;font-family:var(--serif);cursor:pointer}
.verdicts button.idk{font-size:14px;font-family:var(--sans)}
.verdicts button[aria-pressed="true"]{background:var(--indigo);color:var(--on-solid);border-color:transparent}
"""
PAGE_JS = """
const BODY = `<header class="top"><div class="top-in"><span class="brand">__TITLE__</span><span class="save" id="save">本机</span><span class="count" id="count">0 / 0</span></div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap"><details class="intro" id="intro" open><summary>怎么裁</summary>
<p><b>一组一问：这几块图上，刻的是哪个字？</b>点图上实际刻的那个字（异体按刻形选，口径 A，不并通行字）。你的选择决定这一组在系统里怎么处理（异体归并还是保留刻形），不用再逐格看。</p></details>
<div class="ctrl"><div class="seg" id="filter"><button data-f="todo" aria-pressed="true">未裁</button><button data-f="all" aria-pressed="false">全部</button><button data-f="done" aria-pressed="false">已裁</button></div><button class="ghost" id="copy">复制</button><button class="ghost" id="reset">清空</button></div>
<div class="list" id="list"></div></div>
<div class="sheet" id="sheet" hidden><div class="sheet-in"><h2>裁决结果</h2><p id="sheet-note"></p><textarea id="sheet-text" readonly></textarea><div class="row"><button class="ghost" id="sheet-copy">复制</button><button class="ghost" id="sheet-close">关闭</button></div></div></div>`;
const rowId = r => r.id;
function card(r){ const v = verdictOf(r.id);
  const b = m => `<button data-v="${m}" aria-pressed="${v===m}">${esc(m)}</button>`;
  return `<article class="card" data-id="${r.id}"${v?` data-v="${esc(v)}"`:''}><h3>系统码位 ${esc(r.key)}</h3>
  <div class="q">图上刻的是哪个字？（${r.cells.length} 块样例）</div>
  <div class="tiles">${r.tiles.map(t=>`<img data-src="${t}" alt="">`).join('')}</div>
  <div class="verdicts">${r.members.map(b).join('')}<button class="idk" data-v="idk" aria-pressed="${v==='idk'}">拿不准</button></div></article>`; }
let filter='todo';
function visibleRows(){ if(filter==='all') return D.rows; const d=filter==='done'; return D.rows.filter(r=>!!verdictOf(r.id)===d); }
document.addEventListener('click', e => { const b=e.target.closest('#filter button'); if(!b) return; filter=b.dataset.f;
  [...b.parentElement.children].forEach(x=>x.setAttribute('aria-pressed',String(x===b))); draw(); });
function afterVerdict(){ if(filter!=='all') draw(); }
function payload(){ return D.rows.filter(r=>verdictOf(r.id)).map(r=>JSON.stringify({id:r.id,key:r.key,verdict:verdictOf(r.id)})).join('\\n'); }
""".replace("__TITLE__", TITLE)
html = render(TITLE, "y1-group-codepoint-v1", verdicts={}, css=CSS, page_js=PAGE_JS, payload={"rows": rows, "imgs": imgs})
Path(out).write_text(html, encoding="utf-8"); print(out, f"{len(html)/1024:.0f} KB", len(rows), "组")
