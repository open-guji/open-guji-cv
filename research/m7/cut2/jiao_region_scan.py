import json,itertools,collections
import numpy as np
from PIL import Image
from open_guji_cv.groups import ids_whole as W
DS='/home/user/open-guji-dataset/char-groups/variant/jiao'
rows=[]
for l in open(DS+'/labels.jsonl'):
    r=json.loads(l); a=np.asarray(Image.open(f"{DS}/crops/"+r['id'].replace(':','_')+".png").convert('L'))
    rows.append((r['form'],W.norm(a,32),r['id'].split(':')[0]))
rows=[r for r in rows if r[1] is not None]
vols=sorted({r[2] for r in rows}); folds=[vols[i::5] for i in range(5)]
def ev(kind,region,lam):
    res=[]
    for f in folds:
        bank={}
        for fm,x,v in rows:
            if v not in f: bank.setdefault(fm,[]).append(x)
        for fm,x,v in rows:
            if v in f:
                ch,m,_=W.score_norm(x,bank,kind,region,lam); res.append((ch==fm,m))
    wrong=[m for ok,m in res if not ok]; thr=max(wrong) if wrong else 0
    cov=sum(1 for ok,m in res if ok and m>thr)
    return sum(ok for ok,_ in res),len(wrong),round(thr,3),cov
out=[]
for kind in ('hog','pix'):
  for lam in (0.3,1,3):
    for (x1,y1) in [(1,1),(.7,.7),(.6,.6),(.5,.5),(.5,.7),(.7,.5),(.4,.4),(.6,.4),(.4,.6),(.8,.6),(.6,.8)]:
        for (x0,y0) in [(0,0),(0,.1),(.1,0)]:
            if x1<=x0+.3 or y1<=y0+.3: continue
            if kind=='hog' and (int((y1-y0)*32)<16 or int((x1-x0)*32)<16): continue
            try: r=ev(kind,(x0,x1,y0,y1),lam)
            except ValueError: continue
            out.append((r[3],r[1],kind,lam,(x0,x1,y0,y1),r))
out.sort(key=lambda t:(-t[0],t[1]))
n=len(rows); print('n',n,collections.Counter(r[0] for r in rows))
for o in out[:15]: print(o)
print('baseline', [o for o in out if o[4]==(0,1,0,1)][:6])
