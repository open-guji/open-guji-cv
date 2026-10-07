# -*- coding: utf-8 -*-
"""出待标清单的审查页（Y1，overview#471）。

用法：python build_review.py <book> <重放 seed_admit 产物根> <快照 products 根> <cache 根> <out.html>
卡 = pending_<book>.jsonl 里的一格：字块图、30 字上下文、系统建议字、库候选、整理本字；
裁决：对 / 错（填正字）/ 拿不准。回收：harvest.py（出看图结论.jsonl 同格式，可直接当 exp 的 vision 标签）。
"""
import base64, io, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / ".claude/skills/review-artifact/scripts"))
from PIL import Image
from review_shell import render
from lib import load_step

book, prod, src, cache, out = sys.argv[1:6]
prior = sys.argv[6] if len(sys.argv) > 6 else None   # 线上旧页（带用户裁决），重发时把裁决带过去
cards = [json.loads(l) for l in open(HERE / f"pending_{book}.jsonl", encoding="utf-8")]
sa = load_step(prod, book, "seed_admit"); ci = load_step(src, book, "cell_shrink")
cols = {}
for k, r in sa.items():
    _, p, c, _s = k.split(":")[:4]
    cols.setdefault((p, c), []).append(k)
def skey(k):
    s = k.split(":")[3]; n = int("".join(ch for ch in s if ch.isdigit())); return (n, s)
for v in cols.values():
    v.sort(key=skey)

def context(k, w=15):
    _, p, c, _s = k.split(":")
    ids = cols[(p, c)]; i = ids.index(k)
    ch = lambda j: (sa[ids[j]]["char"] or "□")
    return "".join(ch(j) for j in range(max(0, i - w), i)), ch(i), "".join(ch(j) for j in range(i + 1, min(len(ids), i + 1 + w)))

def thumb(k):
    pk = ci[k]["patch_key"]; f = Path(cache) / book / "char_patch" / f"{pk}.png"
    im = Image.open(f).convert("L"); im.thumbnail((128, 128))
    im = im.point(lambda x: (x // 16) * 16)
    b = io.BytesIO(); im.save(b, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()

rows, imgs = [], {}
for i, c in enumerate(cards):
    k = c["id"]; a, m, z = context(k)
    imgs[f"i{i}"] = thumb(k)
    sug = sa[k]["char"] or (c["lib_top"][0][0] if c["lib_top"] else "")
    rows.append(dict(id=k, cls=c["cls"], sug=sug, a=a, z=z, lib=[x for x, _ in c["lib_top"]],
                     cov=c["cov"], ref=c.get("ref"), img=f"i{i}", sub=k.split(":")[3][-1] in "ab"))

TITLE = f"{book} 待审格标注"
CSS = """
.card{background:var(--surface);border:1px solid var(--rule);border-left:3px solid transparent;border-radius:3px;padding:12px 13px;box-shadow:var(--shadow)}
.card[data-v="ok"]{border-left-color:var(--ok)}.card[data-v="wrong"]{border-left-color:var(--zhu)}.card[data-v="idk"]{border-left-color:var(--faint)}
.card .id{font:12px var(--mono);color:var(--muted)}
.card .row{display:flex;gap:12px;align-items:center;margin-top:8px}
.card img{width:96px;height:96px;object-fit:contain;background:var(--tile);border-radius:2px;flex:none}
.card .sug{font-family:var(--serif);font-size:34px;line-height:1}
.card .meta{font-size:12px;color:var(--muted);margin-top:4px}
.card .ctx{font-family:var(--serif);font-size:17px;margin-top:8px;word-break:break-all}
.card .ctx b{color:var(--zhu);font-size:21px}
.verdicts{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}
.verdicts button{min-height:44px;border:1px solid var(--rule-hard);border-radius:3px;background:var(--surface);color:var(--ink);font-size:14px;font-weight:500;cursor:pointer}
.verdicts button[aria-pressed="true"]{color:var(--on-solid);border-color:transparent}
.verdicts button.ok[aria-pressed="true"]{background:var(--ok)}
.verdicts button.wrong[aria-pressed="true"]{background:var(--zhu)}
.verdicts button.idk[aria-pressed="true"]{background:var(--faint)}
.fix{margin-top:8px;display:none}.card[data-v="wrong"] .fix{display:block}
.fix input{width:100%;box-sizing:border-box;min-height:44px;font-size:22px;font-family:var(--serif);padding:4px 8px;border:1px solid var(--rule-hard);border-radius:3px;background:var(--surface);color:var(--ink)}
"""
PAGE_JS = """
const BODY = `
<header class="top"><div class="top-in"><span class="brand">__TITLE__</span>
<span class="save" id="save">本机</span><span class="count" id="count">0 / 0</span></div>
<div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
<details class="intro" id="intro" open><summary>怎么裁</summary>
<p><b>每一格问的只有一件事：这一格的字认成哪个字。</b>不问放不放行，也不问切得对不对（框切偏、看不清就点「拿不准」）。你的选择当金标用：已放行格验误放行，待审格标定阈值，不会因为点「对」就放松。</p>
<p>看字块图，判<b>系统建议字</b>对不对。<b>对</b>＝图上就是这个字；<b>错</b>＝不是，在下面填图上的正字（残缺／看不出就点「拿不准」）。
异体按图上刻形填（口径 A，不并通行字）。点错再点一次取消。裁决自动存回本页。</p></details>
<div class="ctrl"><div class="seg" id="filter">
<button data-f="todo" aria-pressed="true">未裁</button><button data-f="all" aria-pressed="false">全部</button><button data-f="done" aria-pressed="false">已裁</button></div>
<button class="ghost" id="copy">复制</button><button class="ghost" id="reset">清空</button></div>
<div class="list" id="list"></div></div>
<div class="sheet" id="sheet" hidden><div class="sheet-in"><h2>裁决结果</h2><p id="sheet-note"></p>
<textarea id="sheet-text" readonly></textarea><div class="row"><button class="ghost" id="sheet-copy">复制</button>
<button class="ghost" id="sheet-close">关闭</button></div></div></div>`;
const rowId = r => r.id;
function card(r){
  const v = verdictOf(r.id), c = (state[r.id]||{}).c || '';
  const b = ([k,t]) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  return `<article class="card" data-id="${r.id}"${v?` data-v="${v}"`:''}>
   <div class="id">${r.id}　${esc(r.cls)}${r.sub?'　夹注':''}</div>
   <div class="row"><img data-src="${r.img}" alt=""><div><div class="sug">${esc(r.sug)}</div>
   <div class="meta">系统建议字　库候选 ${esc(r.lib.join(' '))}　cov ${r.cov}${r.ref?'　整理本 '+esc(r.ref):''}</div></div></div>
   <div class="ctx">${esc(r.a)}<b>【${esc(r.sug)}】</b>${esc(r.z)}</div>
   <div class="verdicts">${[['ok','对'],['wrong','错'],['idk','拿不准']].map(b).join('')}</div>
   <div class="fix"><input data-fix="${r.id}" placeholder="图上的正字（一个字）" value="${esc(c)}"></div></article>`;
}
let filter = 'todo';
function visibleRows(){ if (filter==='all') return D.rows; const d = filter==='done'; return D.rows.filter(r => !!verdictOf(r.id)===d); }
document.addEventListener('click', e => { const b = e.target.closest('#filter button'); if (!b) return;
  filter = b.dataset.f; [...b.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x===b))); draw(); });
document.addEventListener('input', e => { const i = e.target.closest('input[data-fix]'); if (!i) return;
  const id = i.dataset.fix; if (!state[id]) return; state[id] = {...state[id], c: i.value.trim(), t: Date.now()}; persist(); });
function afterVerdict(){ /* 「错」的卡要留着填正字，其余裁完在「未裁」档里消失 */
  if (filter==='all') return;
  document.querySelectorAll('#list .card').forEach(el => { const v = verdictOf(el.dataset.id);
    if ((filter==='todo' && v && v!=='wrong') || (filter==='done' && !v)) el.remove(); }); }
function payload(){ return D.rows.filter(r => verdictOf(r.id)).map(r => JSON.stringify({id:r.id, verdict:verdictOf(r.id), char:(state[r.id]||{}).c||''})).join('\\n'); }
""".replace("__TITLE__", TITLE)
import re
verd = {}
if prior:
    verd = json.loads(re.search(r'<script[^>]*id="data"[^>]*>(.*?)</script>', open(prior, encoding="utf-8").read(), re.S).group(1).replace("<\\/", "</")).get("verdicts") or {}
html = render(TITLE, f"y1-pending-{book}-v1", verdicts=verd, css=CSS, page_js=PAGE_JS, payload={"rows": rows, "imgs": imgs})
Path(out).write_text(html, encoding="utf-8")
print(out, f"{len(html)/1024:.0f} KB", len(rows), "卡")
