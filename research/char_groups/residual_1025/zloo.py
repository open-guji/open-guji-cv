import json,sys
exec(open('zheng_eval.py').read().split('cfg=FlowConfig')[0])
from open_guji_cv.groups import ids_online as O, ids_whole
import numpy as np
sp=O.SPECS['zheng']
d=json.load(open('/home/user/open-guji-cv/config/groups/zheng/ids_bank.json'))
bank=O.load_bank('/home/user/open-guji-cv/config/groups/zheng/ids_bank.json')
books=d['source']['books']; keys=d['source']['keys']
print(type(bank), {k:type(v) for k,v in list(bank.items())[:3]})
rows=[]
for l in open('/home/user/open-guji-dataset/char-groups/labels/unified.jsonl'):
    r=json.loads(l)
    if r['form'] in ('徵','徴') and r['kind']=='shape':
        v=r['id'].split(':')[0]
        import os
        if not os.path.exists(f'/home/user/prod/{v}'): continue
        g=patch(r['id'])
        if g is None: continue
        sub={n:[t for j,t in enumerate(bank[n]) if books[n][j]!=v] for n in ('徵','徴')}
        best,m,sc=ids_whole.score(np.asarray(g),sub,sp.whole,tuple(sp.region),sp.lam,sp.size)
        rows.append((r['id'],r['form'],best,round(float(m),3)))
for x in sorted(rows,key=lambda x:-x[3]):
    if x[1]!=x[2]: print('WRONG',x)
for t in (0.45,0.6,0.7,0.8,0.9):
    g=[x for x in rows if x[3]>=t]; print(t,len(g),'/',len(rows),sum(x[1]!=x[2] for x in g))
