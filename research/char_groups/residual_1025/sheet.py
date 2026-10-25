"""看图页：每格一行：本格放大 + 上下各 3 格的列条；标注 id 库字 整理本 判法。
用法：python sheet.py <rows.json> <out.png> [--filter g=wj]"""
import json,sys,cv2,numpy as np
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
F=ImageFont.truetype('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',18)
_sh={};_im={}
def box(cid):
    v,p=cid.split(':')[0],int(cid.split(':')[1])
    k=(v,p)
    if k not in _sh:
        f=Path(f'/home/user/prod/{v}/cell_shrink/p{p:04d}.json')
        sh=json.load(open(f))['char_index']['columns']
        W=img(v,p).shape[1]
        cv=lambda b:(W-1-b[2],b[1],W-1-b[0],b[3])
        _sh[k]=({c['id']:cv(c['bbox_page']) for col in sh for c in col['chars']},[[c['id'] for c in col['chars']] for col in sh])
    return _sh[k]
def img(v,p):
    if (v,p) not in _im: _im[(v,p)]=cv2.imread(f'/home/user/imgs/{v}/{p}.png',cv2.IMREAD_GRAYSCALE)
    return _im[(v,p)]
def crop(cid,pad=4):
    v,p=cid.split(':')[0],int(cid.split(':')[1])
    bx,cols=box(cid); I=img(v,p)
    b=bx.get(cid)
    if b is None or I is None: return np.full((80,80),255,np.uint8),None
    x0,y0,x1,y1=[int(t) for t in b]
    c=I[max(0,y0-pad):y1+pad,max(0,x0-pad):x1+pad]
    # 列条：同列前后 3 格
    col=[cc for cc in cols if cid in cc][0]; i=col.index(cid)
    ids=col[max(0,i-3):i+4]
    bs=[bx[x] for x in ids]
    X0=int(min(b[0] for b in bs))-4;X1=int(max(b[2] for b in bs))+4;Y0=int(min(b[1] for b in bs));Y1=int(max(b[3] for b in bs))
    strip=I[max(0,Y0):Y1,max(0,X0):X1].copy()
    strip=cv2.cvtColor(strip,cv2.COLOR_GRAY2BGR)
    cv2.rectangle(strip,(x0-X0,y0-Y0),(x1-X0,y1-Y0),(0,0,255),2)
    return c,strip
def main():
    rows=json.load(open(sys.argv[1])) if sys.argv[1].endswith('.json') else [json.loads(l) for l in open(sys.argv[1])]
    filt=[a for a in sys.argv[3:] if '=' in a]
    for f in filt:
        k,v=f.split('=',1); rows=[r for r in rows if str(r.get(k))==v]
    H=200;W=900
    canvas=Image.new('RGB',(W,H*len(rows)+10),'white'); d=ImageDraw.Draw(canvas)
    for n,r in enumerate(rows):
        c,strip=crop(r['id'])
        y=n*H
        s=150/max(c.shape); ci=cv2.resize(c,(max(1,int(c.shape[1]*s)),max(1,int(c.shape[0]*s))))
        canvas.paste(Image.fromarray(ci),(5,y+5))
        if strip is not None:
            s2=(H-10)/strip.shape[0]; st=cv2.resize(strip,(max(1,int(strip.shape[1]*s2)),H-10))
            canvas.paste(Image.fromarray(cv2.cvtColor(st,cv2.COLOR_BGR2RGB)),(165,y+5))
        lab=r.get('label') or f"{n+1}. {r['id']} 库{r.get('lib')} 整{r.get('ref')}"
        tx=165+80
        for j,line in enumerate(lab.split('\n')):
            d.text((tx,y+8+j*24),line,fill='black',font=F)
        d.line((0,y+H-1,W,y+H-1),fill=(200,200,200))
    canvas.save(sys.argv[2])
main()
