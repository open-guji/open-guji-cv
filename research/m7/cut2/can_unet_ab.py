import sys,json,collections
import numpy as np, torch
torch.set_num_threads(4)
from dataclasses import asdict
from pathlib import Path
from open_guji_cv.groups import ids_online as O
from open_guji_cv.groups.ids_unet import NpNet
DS=Path('/home/user/open-guji-dataset')
g='can'; spec=O.SPECS[g]
rows,_=O._pool(g,DS)
vols=sorted({r[0].split(':')[0] for r in rows}); fo={v:k%5 for k,v in enumerate(vols)}
print(len(rows),vols,flush=True)
res=collections.defaultdict(list)   # method -> [(ok,margin)]
for k in range(5):
    test=[r for r in rows if fo[r[0].split(':')[0]]==k]; rest=[r for r in rows if fo[r[0].split(':')[0]]!=k]
    if not test: continue
    net=NpNet.from_torch(O._train_unet2([(img,cut) for i,f,img,cut in rest],spec.orient,epochs=60))
    bank=O._templates(g,rest)
    for i,f,img,_ in test:
        for name,sp,n in (('自动缝',spec,None),('U-Net',O.IdsSpec(**{**asdict(spec),'unet':'x'}),net)):
            v=O.judge_with(g,img,bank,O.IdsSpec(**{**asdict(sp),'min_margin':0.0}),net=n)
            m=float(v.extra.get('margin',0) or 0)
            res[name].append((v.char==f,m if v.char else 0.0,v.char,i,f))
    print('fold',k,flush=True)
for name,v in res.items():
    n=len(v); wrong=[m for ok,m,*_ in v if not ok]; thr=max(wrong) if wrong else 0
    print(name,'n',n,'对',sum(ok for ok,*_ in v),'错',len(wrong),'0错门槛',round(thr,3),'覆盖',sum(1 for ok,m,*_ in v if ok and m>thr))
    for m_ in (0.02,0.04,0.06):
        r=sum(1 for ok,m,*_ in v if m>=m_ and ok); w=sum(1 for ok,m,*_ in v if m>=m_ and not ok); print('  margin',m_,'对',r,'错',w,'弃',n-r-w)
    print('  错例',[(i,f,c,round(m,3)) for ok,m,c,i,f in v if not ok][:8])
