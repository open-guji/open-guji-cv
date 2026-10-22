import json,glob,re,sys,io,base64,pickle
sys.path.insert(0,'/home/user/open-guji-cv'); sys.path.insert(0,'/home/user/open-guji-cv/.claude/skills/review-artifact/scripts')
import numpy as np
from PIL import Image
import cv2
from review_shell import render
from open_guji_cv.groups import ids_online as O
from open_guji_cv.groups.ids_segment import ink_of
G,MEM,TITLE,KEY=sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]
WS=glob.glob('/home/user/guji-workspace/96mid*/data_full/zongmu')[0]
src=open('build2.py').read(); exec(src[src.index("def clean"):src.index("sel=[h for h")])
DS=f'/home/user/open-guji-dataset/char-groups/variant/{G}'
have=set(json.loads(l)['id'] for l in open(DS+'/labels.jsonl'))
bank=O.load_bank(O.bank_path(G)); spec=O.SPECS[G]
cells=json.load(open(f'prod_{G}.json'))
rows=[];imgs={};crops={}
for cid,ch,prov in cells:
    if cid in have: continue
    v,p,c,s=cid.split(':')[:4]
    if not s.isdigit(): continue
    d=json.load(open(f'/tmp/prod/{v}/row_segment/p{int(p):04d}.json'))['cells']; q=None
    for col in d['columns']:
        if col['col']==int(c):
            for ce in col['cells']:
                if ce.get('slot')==int(s) and ce.get('sub') is None: q=ce['quad_page']
    if not q: continue
    im=Image.open(f'{WS}/{v}/{p}.png').convert('L')
    xs=[im.width-pt[0] for pt in q]; ys=[pt[1] for pt in q]
    a=clean(np.asarray(im.crop((int(min(xs))-6,int(min(ys))-6,int(max(xs))+6,int(max(ys))+6))))
    crops[cid]=a
    vd=O.judge_with(G,a,bank,spec); pred=vd.char
    t=Image.fromarray(a); t.thumbnail((120,120)); b=io.BytesIO(); t.quantize(16).save(b,'PNG',optimize=True)
    imgs[cid]='data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()
    rows.append(dict(id=cid,title=f'{v} 第{p}页',note=f'对位文字 {ch}'+('' if pred in (None,ch) else f' · 机器看是 {pred}'),img=cid,al=ch,pred=pred,
                     dis=(pred is not None and pred!=ch)))
rows.sort(key=lambda r:(not r['dis'],r['id']))
ver={r['id']:{'v':'A'+MEM.index(r['al']) if False else ('f'+str(MEM.index(r['al']))),'t':1} for r in rows if not r['dis']}
print(len(rows),'disagree',sum(r['dis'] for r in rows))
pickle.dump((rows,crops),open(f'page_{G}.pkl','wb'))
VERD=[(f'f{i}',m,'ok' if i==0 else 'indigo') for i,m in enumerate(MEM)]+[('no','都不是','zhu'),('idk','拿不准','faint')]
n=len(VERD)
CSS=f""".card{{background:var(--surface);border:1px solid var(--rule);border-left:3px solid transparent;border-radius:3px;padding:8px 10px;box-shadow:var(--shadow);display:flex;gap:10px;align-items:center}}
.card img{{width:96px;height:96px;object-fit:contain;image-rendering:pixelated;background:var(--tile);border-radius:2px;flex:none}}
.card .mid{{flex:1;min-width:0}}.card h3{{margin:0 0 6px;font-size:13px;font-weight:500}}.card small{{color:var(--muted);font-weight:400}}
.verdicts{{display:grid;grid-template-columns:repeat({n},1fr);gap:5px}}
.verdicts button{{min-height:44px;border:1px solid var(--rule-hard);border-radius:3px;background:var(--surface);color:var(--ink);font-size:15px;font-weight:500;cursor:pointer}}
.verdicts button[aria-pressed="true"]{{color:var(--on-solid);border-color:transparent}}
"""+"".join(f'.card[data-v="{v}"]{{border-left-color:var(--{c})}}\n.verdicts button.{v}[aria-pressed="true"]{{background:var(--{c})}}\n' for v,_,c in VERD)
JS="""
const BODY=`<header class="top"><div class="top-in"><span class="brand">__T__</span><span class="save" id="save">本机</span><span class="count" id="count">0 / 0</span></div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap"><details class="intro" id="intro" open><summary>怎么标</summary>
<p>字形和位置来自已跑完的整册产物，「对位文字」是整理本对位出来的字，已经预点。<b>前面几张写了“机器看是…”的，机器和对位文字不一致，请你定</b>（没预点）。后面的是两边一致，已预点，只看有没有错的。点错再点一次取消。自动存回本页。</p></details>
<div class="ctrl"><div class="seg" id="filter"><button data-f="todo" aria-pressed="true">未标</button><button data-f="all" aria-pressed="false">全部</button><button data-f="done" aria-pressed="false">已标</button></div><button class="ghost" id="copy">复制</button><button class="ghost" id="reset">清空</button></div>
<div class="list" id="list"></div></div>
<div class="sheet" id="sheet" hidden><div class="sheet-in"><h2>结果</h2><p id="sheet-note"></p><textarea id="sheet-text" readonly></textarea><div class="row"><button class="ghost" id="sheet-copy">复制</button><button class="ghost" id="sheet-close">关闭</button></div></div></div>`;
const VERDICTS=__V__;
const rowId=r=>r.id;
function card(r){const v=verdictOf(r.id);const btn=([k,t])=>`<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
return `<article class="card" data-id="${r.id}"${v?` data-v="${v}"`:''}><img data-src="${r.img}" alt=""><div class="mid"><h3>${esc(r.title)} <small>${esc(r.note)}</small></h3><div class="verdicts">${VERDICTS.map(btn).join('')}</div></div></article>`;}
let filter='all';
function visibleRows(){if(filter==='all')return D.rows;const d=filter==='done';return D.rows.filter(r=>!!verdictOf(r.id)===d);}
document.addEventListener('click',e=>{const b=e.target.closest('#filter button');if(!b)return;filter=b.dataset.f;[...b.parentElement.children].forEach(x=>x.setAttribute('aria-pressed',String(x===b)));draw();});
function afterVerdict(){}
function payload(){return D.rows.filter(r=>verdictOf(r.id)).map(r=>JSON.stringify({id:r.id,verdict:verdictOf(r.id)})).join('\\n');}
""".replace('__V__',json.dumps([[v,t] for v,t,_ in VERD],ensure_ascii=False)).replace('__T__',TITLE)
html=render(TITLE,KEY,verdicts=ver,css=CSS,page_js=JS,payload={'rows':[{k:r[k] for k in('id','title','note','img')} for r in rows],'imgs':imgs})
open(f'page_{G}.html','w',encoding='utf-8').write(html); print(len(html)//1024,'KB')
