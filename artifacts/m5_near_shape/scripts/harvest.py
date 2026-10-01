import sys,pickle; sys.path.insert(0,sys.argv[1])
from common import *
m,human=load()
ids=m._ids
out=[]
t=time.time()
for j,i in enumerate(ids):
    if i not in human: continue
    r=m.match(m._patches[j],feat=m._feats[j],exclude_id=i)
    out.append((j,r.verdict,r.guard,r.cov,list(r.candidates)))
print(len(out),time.time()-t)
pickle.dump(out,open(f'{S}/harvest.pkl','wb'))
