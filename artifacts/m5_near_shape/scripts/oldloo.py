import sys,json,numpy as np
from open_guji_cv.clustering.match import _SHAPE_BOX,_crop_dice,_shape_font_template
S=sys.argv[1]; d=np.load(f'{S}/{sys.argv[2]}.npz'); prov=json.load(open(f'{S}/{sys.argv[3]}'))
ids=[str(i) for i in d['ids']]; ch=list(d['chars']); P=d['P']
for a,b in [('强','強'),('却','卻'),('回','囘'),('并','幷')]:
    box=_SHAPE_BOX[frozenset((a,b))]; y0,y1,x0,x1=box
    A=[j for j,i in enumerate(ids) if ch[j]==a and 'human' in prov.get(i,[])]
    B=[j for j,i in enumerate(ids) if ch[j]==b and 'human' in prov.get(i,[])]
    def best(q,L,c):
        v=[_crop_dice(q[y0:y1,x0:x1],P[k][y0:y1,x0:x1]) for k in L]
        if not v:
            t=_shape_font_template(c); return None if t is None else _crop_dice(q[y0:y1,x0:x1],t[y0:y1,x0:x1])
        return max(v)
    ok=n=0
    for j in A+B:
        sa=best(P[j],[k for k in A if k!=j],a); sb=best(P[j],[k for k in B if k!=j],b)
        if sa is None or sb is None: continue
        pick=a if sa>=sb else b; n+=1; ok+=pick==ch[j]
    print(a,b,len(A),len(B),'old LOO',ok,'/',n)
