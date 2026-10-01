import numpy as np, json, time
from open_guji_cv.clustering.match import GlyphMatcher
S='/tmp/claude-0/-home-user-open-guji-cv/64c0e019-d8d3-5f71-85a2-254e8d806502/scratchpad'
def load(name='siku', **kw):
    d=np.load(f'{S}/{name}.npz')
    m=GlyphMatcher(**kw)
    for iid,c,p,f in zip(d['ids'],d['chars'],d['P'],d['F']):
        m.add(str(iid),str(c),p,f)
    prov=json.load(open(f'{S}/prov.json'))
    human={i for i,v in prov.items() if 'human' in v}
    return m, human
