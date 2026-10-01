import sys,json,pickle,collections,numpy as np
import open_guji_cv.clustering.near_shape as N
from open_guji_cv.clustering.match import _shape_font_template
S=sys.argv[1]; mode=sys.argv[2]
d=np.load(f'{S}/siku.npz'); ids=[str(i) for i in d['ids']]; ch=list(d['chars']); P=d['P']; F=d['F']
prov=json.load(open(f'{S}/prov.json')); human=[i in prov and 'human' in prov[i] for i in ids]
def page(i): p=i.split(':'); p=p[1:] if p[0] in('v1','v2') else p; return tuple(p[:2])
pg=[page(i) for i in ids]
byc=collections.defaultdict(list)
for j in range(len(ids)):
    if human[j]: byc[ch[j]].append(j)
cfg=N.NearShapeConfig()
orig=N._fit_score
def fit_pair(q,A,B,cfg_):
    ma,mb,_=N._stats(A,B,cfg_.lam)
    if mode=='exemplar': R=(A[0]-B[0])**2          # 单例刻例两两残差
    elif mode=='font': R=FONT
    else: return orig(q,A,B,cfg_)
    w=N._region(R,cfg_.top)
    return N._score(q,ma,mb,w),w
N._fit_score=fit_pair
trig=pickle.load(open(f'{S}/trig.pkl','rb'))
H={h[0]:h[4] for h in pickle.load(open(f'{S}/harvest.pkl','rb'))}
dec=ok=0; st=collections.Counter()
for (j,v,g,ct,a,b,cb) in trig:
    pair,why=N.trigger_pair(H[j],cfg)
    if pair is None or why: continue
    if mode=='font':
        fa,fb=_shape_font_template(a),_shape_font_template(b)
        if fa is None or fb is None: st['nofont']+=1; continue
        pa=N._prep(fa,cfg.sigma); FONT=(pa-N._shift_to(N._prep(fb,cfg.sigma),pa,cfg.align))**2
    def ex(c):
        L=[k for k in byc[c] if pg[k]!=pg[j]]; L.sort(key=lambda k:(-float(F[k]@F[j]),k)); return [P[k] for k in L[:cfg.max_exemplars]]
    r=N.decide_pair(P[j],ex(pair[0]),ex(pair[1]),cfg,pair)
    st[(g,r.reason)]+=1
    if r.winner: dec+=1; ok+=r.winner==ch[j]
print(mode,'decided',dec,'correct',ok, sorted(st.items(),key=str))
