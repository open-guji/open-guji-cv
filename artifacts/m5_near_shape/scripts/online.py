import sys,pickle,collections; sys.path.insert(0,sys.argv[1])
from common import *
from open_guji_cv.clustering.near_shape import NearShapeConfig
from open_guji_cv.steps.glyph_match import consensus_same
name=sys.argv[2]; grouped=sys.argv[3]=='page'
cfg=NearShapeConfig(**(json.loads(sys.argv[4]) if len(sys.argv)>4 else {}))
d=np.load(f'{S}/{name}.npz'); ids=[str(i) for i in d['ids']]
m,human=load(name, near_shape=cfg)
if name!='siku':
    prov=json.load(open(f'{S}/prov_{name}.json')); human={i for i,v in prov.items() if 'human' in v}
m.trusted_ids=set(human)
def page(i): p=i.split(':'); p=p[1:] if p[0] in('v1','v2') else p; return tuple(p[:2])
bypage=collections.defaultdict(set)
for i in ids: bypage[page(i)].add(i)
nconf=collections.Counter(c for i,c in zip(ids,m._chars) if i in human)
out=[]
for j,i in enumerate(ids):
    if i not in human: continue
    if grouped: m.trusted_ids=human-bypage[page(i)]
    r=m.match(m._patches[j],feat=m._feats[j],exclude_id=i)
    out.append((j,m._chars[j],r.verdict,r.guard,r.cov,r.candidates[:5],r.near_shape))
pickle.dump(out,open(f'{S}/online_{name}_{sys.argv[3]}.pkl','wb'))
st=collections.Counter(); pairs=collections.Counter(); good=collections.Counter(); errs=[]
for j,c,v,g,cov,cands,ns in out:
    if ns is None: continue
    st[(g,ns['reason'])]+=1
    if ns['winner']:
        ok=ns['winner']==c; key=tuple(sorted(ns['pair'])); pairs[(key,g)]+=1; good[(key,g)]+=ok
        if not ok: errs.append((ids[j],c,ns['pair'],ns['score'],g))
print(sorted(st.items(),key=str))
dec=sum(pairs.values()); print('decided',dec,'correct',sum(good.values()))
print('unguarded',sum(n for (k,g),n in pairs.items() if g is None),sum(n for (k,g),n in good.items() if g is None))
print('errs',errs)
agg=collections.Counter(); aggok=collections.Counter()
for (k,g),n in pairs.items(): agg[k]+=n; aggok[k]+=good[(k,g)]
print([(''.join(k),n,aggok[k],nconf[k[0]],nconf[k[1]]) for k,n in agg.most_common(25)])
