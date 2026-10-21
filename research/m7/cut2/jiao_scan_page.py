import sys,json,glob,io,base64
sys.path.insert(0,'/home/user/open-guji-cv/.claude/skills/review-artifact/scripts'); sys.path.insert(0,'/home/user/open-guji-cv')
import numpy as np
from PIL import Image
from review_shell import render
from open_guji_cv.groups import ids_whole as W
WS=glob.glob('/home/user/guji-workspace/96mid*/data_full/zongmu')[0]
DS='/home/user/open-guji-dataset/char-groups/variant/jiao'
H=json.load(open('/tmp/scan/cand.json'))
kp=set()
bank={}
for l in open(DS+'/labels.jsonl'):
    r=json.loads(l); v,p=r['id'].split(':')[:2]; kp.add((v,p))
    a=np.asarray(Image.open(f"{DS}/crops/"+r['id'].replace(':','_')+".png").convert('L')); x=W.norm(a,32)
    if x is not None: bank.setdefault(r['form'],[]).append(x)
REG=(0,0.6,0.1,0.6)
import cv2
from open_guji_cv.groups.ids_segment import ink_of
def clean(a):
    ink=ink_of(a).astype(np.uint8); n,lab,st,_=cv2.connectedComponentsWithStats(ink,connectivity=8)
    h,w=ink.shape; keep=np.zeros_like(ink)
    for i in range(1,n):
        x0,y0,bw,bh,ar=st[i]
        cx,cy=x0+bw/2,y0+bh/2
        if ar>=10 and w*0.2<cx<w*0.8 and h*0.2<cy<h*0.8: keep[lab==i]=1
    ys,xs=np.where(keep)
    if len(ys)==0: return a
    # 并入与主体框相接近的碎件
    x0,x1,y0,y1=xs.min(),xs.max(),ys.min(),ys.max()
    for i in range(1,n):
        bx,by,bw,bh,ar=st[i]
        if ar>=6 and bx>=x0-6 and by>=y0-6 and bx+bw<=x1+6 and by+bh<=y1+6: keep[lab==i]=1
    ys,xs=np.where(keep)
    out=np.full((ys.max()-ys.min()+1+8,xs.max()-xs.min()+1+8),255,np.uint8)
    sub=np.where(keep[ys.min():ys.max()+1,xs.min():xs.max()+1]>0,0,255).astype(np.uint8)
    out[4:4+sub.shape[0],4:4+sub.shape[1]]=sub
    return out
sel=[h for h in H if h[0]>=0.70 and not (h[0]>=0.9 and (h[1],h[2]) in kp)]
rows=[];imgs={}
for s,v,pg,x,y in sel:
    im=Image.open(f'{WS}/{v}/{pg}.png').convert('L').crop((x-14,y-14,x+138,y+138))
    a=clean(np.asarray(im)); im=Image.fromarray(a); xn=W.norm(a,32)
    ch,m,_=W.score_norm(xn,bank,'hog',REG,0.3) if xn is not None else (None,0,0)
    cid=f'{v}:{pg}:x{x}y{y}'
    b=io.BytesIO(); im.resize((120,int(120*im.height/im.width)) if im.width>=im.height else (int(120*im.width/im.height),120),Image.LANCZOS).quantize(16).save(b,'PNG',optimize=True)
    imgs[cid]='data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()
    rows.append(dict(id=cid,title=f'{v} 第{pg}页',note=f'模板相似 {s:.2f}',img=cid,pred=ch,margin=float(m),score=float(s)))
rows.sort(key=lambda r:(r['margin']>0.55, -r['score']))
ver={r['id']:{'v':'jiao' if r['pred']=='教' else 'yi','t':1} for r in rows if r['margin']>0.55}
print(len(rows),len(ver))
json.dump(rows,open('/tmp/jiao2/cards.json','w'),ensure_ascii=False)
VERD=[('jiao','教','ok'),('yi','敎','indigo'),('no','都不是','zhu'),('idk','拿不准','faint')]
CSS=""".card{background:var(--surface);border:1px solid var(--rule);border-left:3px solid transparent;border-radius:3px;padding:8px 10px;box-shadow:var(--shadow);display:flex;gap:10px;align-items:center}
.card img{width:96px;height:96px;image-rendering:pixelated;background:var(--tile);border-radius:2px;flex:none}
.card .mid{flex:1;min-width:0}.card h3{margin:0 0 6px;font-size:13px;font-weight:500}.card small{color:var(--muted);font-weight:400}
.verdicts{display:grid;grid-template-columns:repeat(4,1fr);gap:5px}
.verdicts button{min-height:44px;border:1px solid var(--rule-hard);border-radius:3px;background:var(--surface);color:var(--ink);font-size:15px;font-weight:500;cursor:pointer}
.verdicts button[aria-pressed="true"]{color:var(--on-solid);border-color:transparent}
"""+"".join(f'.card[data-v="{v}"]{{border-left-color:var(--{c})}}\n.verdicts button.{v}[aria-pressed="true"]{{background:var(--{c})}}\n' for v,_,c in VERD)
JS="""
const BODY=`<header class="top"><div class="top-in"><span class="brand">教敎 补标</span><span class="save" id="save">本机</span><span class="count" id="count">0 / 0</span></div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap"><details class="intro" id="intro" open><summary>怎么标</summary>
<p>每张是页面上找到的疑似「教／敎」字（模板匹配找的，有些不是）。点<b>教</b>或<b>敎</b>；不是这两个字点<b>都不是</b>；看不清点<b>拿不准</b>。已预点的是机器较有把握的（准确率约七成，错的改一下）；没预点的是没把握，请你定。自动存回本页。</p></details>
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
""".replace('__V__',json.dumps([[v,t] for v,t,_ in VERD],ensure_ascii=False))
html=render('教敎补标','jiao-supp-v2',verdicts=ver,css=CSS,page_js=JS,payload={'rows':[{k:r[k] for k in('id','title','note','img')} for r in rows],'imgs':imgs})
open('/tmp/jiao2/jiao_supp.html','w',encoding='utf-8').write(html); print(len(html)//1024,'KB')
