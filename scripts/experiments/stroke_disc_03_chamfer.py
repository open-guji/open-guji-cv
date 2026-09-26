# 实验三：成对判别。给字块和两个候选字 A/B（都有人裁实例），比刚性对齐后的对称倒角距离，看选哪个。
import sys,json,cv2,numpy as np,sqlite3,glob
sys.path.insert(0,'/home/sheldon/open-guji-cv')
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.utils.image_io import imread
from open_guji_cv.clustering.match import GlyphMatcher
from open_guji_cv.clustering.normalize import normalize_patch
W=glob.glob('/home/sheldon/guji-workspace/988g7gsqhd-*')[0]; S=96
def prep(g):
    _,b=cv2.threshold(g,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
    n,lab,st,_=cv2.connectedComponentsWithStats(b,8)
    keep=np.zeros_like(b)
    for i in range(1,n):
        if st[i,cv2.CC_STAT_AREA]>=6: keep[lab==i]=255
    ys,xs=np.nonzero(keep)
    if len(ys)==0: return np.zeros((S,S),np.uint8)
    keep=keep[ys.min():ys.max()+1,xs.min():xs.max()+1]; h,w=keep.shape; k=(S-8)/max(h,w)
    r=cv2.resize(keep,(max(1,round(w*k)),max(1,round(h*k))),interpolation=cv2.INTER_AREA)>127
    out=np.zeros((S,S),np.uint8); y=(S-r.shape[0])//2; x=(S-r.shape[1])//2; out[y:y+r.shape[0],x:x+r.shape[1]]=r
    return out
def dt(b): return cv2.distanceTransform((1-b).astype(np.uint8),cv2.DIST_L2,3)
def chamfer(a,b):
    """a,b 二值 → 刚性对齐（平移±5、缩放3档）后的对称倒角距离（取较差的一侧：多出来/缺了都算）"""
    if not a.any() or not b.any(): return 1e9
    da=dt(a); best=1e9; bestbb=None
    for sc in (0.94,1.0,1.06):
        bs=cv2.resize(b,None,fx=sc,fy=sc,interpolation=cv2.INTER_NEAREST); c=np.zeros((S,S),np.uint8)
        h,w=bs.shape; y0=max(0,(h-S)//2); x0=max(0,(w-S)//2); bs=bs[y0:y0+S,x0:x0+S]; oy=(S-bs.shape[0])//2; ox=(S-bs.shape[1])//2
        c[oy:oy+bs.shape[0],ox:ox+bs.shape[1]]=bs
        for dy in range(-5,6):
            for dx in range(-5,6):
                bb=np.roll(np.roll(c,dy,0),dx,1)
                if not bb.any(): continue
                d1=da[bb>0]; d2=dt(bb)[a>0] if False else None
                s=np.percentile(d1,97)
                if s<best: best=s; bestbb=bb
    if bestbb is None: return 1e9
    d2=dt(bestbb)[a>0]
    return max(best,np.percentile(d2,97))
def raw(id):
    _,p,c,s=id.split(':'); sub=s[-1] if s[-1] in 'ab' else ''; s=s.rstrip('ab')
    return imread(str(cache.get('bxgb','char_patch',f'p{int(p):04d}c{int(c):02d}s{s}{sub}')),0)
db=sqlite3.connect(f'{W}/output/glyph.db'); ex={}
cache=ImageCache()
for ch,iid in db.execute("""SELECT g.char,e.instance_id FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id
      JOIN instances i ON i.instance_id=e.instance_id WHERE i.label_status='human'"""):
    try: ex.setdefault(ch,[]).append((iid,prep(raw(iid.replace('v2:','')))))
    except Exception: pass
def score(a,ch,self_id):
    return min((chamfer(a,b) for iid,b in ex.get(ch,[])[:6] if not iid.endswith(self_id)),default=None)
d=json.load(open('/tmp/claude-1001/-home-sheldon-overview/90d8a186-f57b-45f0-8e3b-a9e61b986736/scratchpad/disc1.json'))
res=[]
# 负例：真值=cur，诱饵=iron；需 cur 也有人裁实例
for id,iron,cur,cov,w,iid in d['neg']:
    if cur not in ex: continue
    a=prep(raw(id)); st,sw=score(a,cur,id),score(a,iron,id)
    if st is None or sw is None: continue
    res.append(('neg',id,cur,iron,round(float(st),2),round(float(sw),2)))
# 正例：真值=ch，诱饵=人裁库 kNN 里最像的异字
hm=GlyphMatcher(k=10)
for ch,v in ex.items():
    for iid,b in v: pass
from open_guji_cv.clustering.normalize import normalize_patch as NP
for ch,iid,png in db.execute("""SELECT g.char,e.instance_id,i.patch_png FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id
      JOIN instances i ON i.instance_id=e.instance_id WHERE i.label_status='human'"""):
    im=cv2.imdecode(np.frombuffer(png,np.uint8),0); hm.add(iid,ch,NP(im,stroke_width=3))
for id,ch,cov,w,iid in d['pos']:
    if cov<0.99: continue
    r=raw(id); m=hm.match(NP(r,stroke_width=3),exclude_id='v2:'+id)
    decoy=next((c for c,v in m.candidates if c!=ch),None)
    if not decoy: continue
    a=prep(r); st,sw=score(a,ch,id),score(a,decoy,id)
    if st is None or sw is None: continue
    res.append(('pos',id,ch,decoy,round(float(st),2),round(float(sw),2)))
json.dump(res,open('/tmp/claude-1001/-home-sheldon-overview/90d8a186-f57b-45f0-8e3b-a9e61b986736/scratchpad/disc3.json','w'),ensure_ascii=False)
for kind in ('neg','pos'):
    rs=[r for r in res if r[0]==kind]
    right=sum(r[4]<r[5] for r in rs); tie=sum(r[4]==r[5] for r in rs)
    print(kind,len(rs),'选对',right,'平',tie,'选错',len(rs)-right-tie)
print([r for r in res if r[0]=='neg' and r[4]>=r[5]])
