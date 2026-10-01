import sys,pickle,collections; sys.path.insert(0,sys.argv[1])
from common import *
d=np.load(f'{S}/siku.npz'); ids=list(d['ids']); ch=list(d['chars'])
prov=json.load(open(f'{S}/prov.json')); human={i for i,v in prov.items() if 'human' in v}
H=collections.Counter(c for i,c in zip(ids,ch) if i in human)
H_all=collections.Counter(ch)
out=pickle.load(open(f'{S}/harvest.pkl','rb'))
cnt=collections.Counter(); pairs=collections.Counter(); ok=collections.Counter()
trig=[]
for j,v,g,cov,c in out:
    cnt[(v,g)]+=1
    if not c: continue
    top,ct=c[0]; nx=next(((a,b) for a,b in c[1:] if a!=top),None)
    if nx is None or ct-nx[1]>=0.03: continue
    if H[top]-(ch[j]==top)<3 or H[nx[0]]-(ch[j]==nx[0])<3: continue
    trig.append((j,v,g,ct,top,nx[0],nx[1]))
    pairs[tuple(sorted((top,nx[0])))]+=1
    ok[(v,g, ch[j]==top, ch[j]==nx[0])]+=1
print(cnt); print(len(trig)); print(ok); print(pairs.most_common(30))
pickle.dump(trig,open(f'{S}/trig.pkl','wb'))
