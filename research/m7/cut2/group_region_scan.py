import sys,json,itertools
import numpy as np
from PIL import Image
sys.path.insert(0,'/home/user/open-guji-cv')
from open_guji_cv.groups import ids_whole as W
G=sys.argv[1]; D=f'/tmp/grp/{G}'
raw=[]
for l in open(D+'/labels.jsonl'):
    r=json.loads(l); a=np.asarray(Image.open(f"{D}/crops/"+r['id'].replace(':','_')+".png").convert('L')); raw.append((r['form'],a,r['id'].split(':')[0],r['id']))
vols=sorted({r[2] for r in raw}); folds=[vols[i::5] for i in range(5)]
import collections; print(collections.Counter(r[0] for r in raw),vols)
def ev(size,kind,region,lam,rows):
    res=[]
    for fo in folds:
        bank={}
        for f,x,v,i in rows:
            if v not in fo: bank.setdefault(f,[]).append(x)
        if len(bank)<2: continue
        for f,x,v,i in rows:
            if v in fo:
                ch,m,_=W.score_norm(x,bank,kind,region,lam); res.append((ch==f,m,i))
    wrong=[m for ok,m,_ in res if not ok]; thr=max(wrong) if wrong else 0
    return sum(ok for ok,_,_ in res),len(wrong),round(thr,3),sum(1 for ok,m,_ in res if ok and m>thr),len(res)
out=[]
for size in ((64,) if len(sys.argv)>2 else (32,64)):
    rows=[(f,W.norm(a,size),v,i) for f,a,v,i in raw if W.norm(a,size) is not None]
    for kind in ('hog','pix'):
        for lam in (0.3,1,3):
            for reg in [(0,1,0,1),(0,1,0,.5),(0,1,0,.6),(0,1,0,.4),(0,1,.1,.6),(0,.6,0,.5),(.2,.8,0,.5),(.4,1,0,.5),(0,1,.4,1),(0,1,0,.7)]:
                if kind=='hog' and ((reg[1]-reg[0])*size<16 or (reg[3]-reg[2])*size<16): continue
                try: r=ev(size,kind,reg,lam,rows)
                except Exception as e: continue
                out.append((r[3],r[1],size,kind,lam,reg,r))
out.sort(key=lambda t:(-t[0],t[1]))
for o in out[:10]: print(o)
print('full',[o for o in out if o[5]==(0,1,0,1)][:3])
best=out[0]; BK,BR,BL=best[3],best[5],best[4]; print('best',best)
print('=== wrong')
size=best[2]; rows=[(f,W.norm(a,size),v,i) for f,a,v,i in raw if W.norm(a,size) is not None]
wr=[]
for fo in folds:
    bank={}
    for f,x,v,i in rows:
        if v not in fo: bank.setdefault(f,[]).append(x)
    for f,x,v,i in rows:
        if v in fo:
            ch,m,_=W.score_norm(x,bank,BK,BR,BL)
            if ch!=f: wr.append((i,f,ch,round(m,2)))
print(wr)
from PIL import Image as I, ImageDraw
n=len(wr); S=I.new('L',(min(n,11)*130,((n+10)//11)*130),255)
for k,(i,f,ch,m) in enumerate(wr):
    im=I.open(f"{D}/crops/"+i.replace(':','_')+".png").convert('L'); im.thumbnail((126,126)); S.paste(im,((k%11)*130,(k//11)*130))
S.save(f'/tmp/jiao2/wrong_{G}.png')
