import sys,json,numpy as np,collections
from open_guji_cv.clustering.near_shape import NearShapeConfig, decide_pair
S=sys.argv[1]; d=np.load(f'{S}/{sys.argv[2]}.npz'); prov=json.load(open(f'{S}/{sys.argv[3]}'))
ids=[str(i) for i in d['ids']]; ch=list(d['chars']); P=d['P']
cfg=NearShapeConfig(min_exemplars=int(sys.argv[4]))
for a,b in [('强','強'),('却','卻'),('回','囘'),('并','幷')]:
    A=[j for j,i in enumerate(ids) if ch[j]==a and 'human' in prov.get(i,[])]
    B=[j for j,i in enumerate(ids) if ch[j]==b and 'human' in prov.get(i,[])]
    res=[]
    for j in A+B:
        r=decide_pair(P[j],[P[k] for k in A if k!=j],[P[k] for k in B if k!=j],cfg,(a,b))
        res.append((ch[j],r.winner,r.reason, None if r.score is None else round(r.score,2)))
    print(a,b,len(A),len(B),res)
