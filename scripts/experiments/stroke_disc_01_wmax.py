# 小笔画判别器实验一：现有 verify 的 cov / wmax 能不能把「铁证冲突」和「铁证一致」分开
import sys,json,random,cv2,numpy as np,sqlite3
sys.path.insert(0,'/home/sheldon/open-guji-cv')
from open_guji_cv.clustering.normalize import normalize_patch
from open_guji_cv.clustering.verify import verify_pair_elastic
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.report.slots import page_slots
from open_guji_cv.utils.image_io import imread
W=sys.argv[1]; NS=3
db=sqlite3.connect(f'{W}/output/glyph.db')
ex={}
for ch,iid,png in db.execute("""SELECT g.char,e.instance_id,i.patch_png FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id
      JOIN instances i ON i.instance_id=e.instance_id WHERE i.label_status='human'"""):
    im=cv2.imdecode(np.frombuffer(png,np.uint8),0)
    if im is not None: ex.setdefault(ch,[]).append((iid,normalize_patch(im,stroke_width=NS)))
cache=ImageCache()
def crop(id):
    _,p,c,s=id.split(':'); sub=s[-1] if s[-1] in 'ab' else ''; s=s.rstrip('ab')
    im=imread(str(cache.get('bxgb','char_patch',f'p{int(p):04d}c{int(c):02d}s{s}{sub}')),0)
    return normalize_patch(im,stroke_width=NS)
def best(id,ch):
    a=crop(id); r=None
    for iid,b in ex.get(ch,[]):
        if iid.endswith(id): continue
        v=verify_pair_elastic(a,b)
        if r is None or v.f1>r[0]: r=(v.f1,v.diff_blob_ratio,iid)
    return r
aud=json.load(open(f'{W}/reports/bxgb/iron_audit.json'))
neg=[(r['id'],r['iron'],r['cur']) for r in aud['rows'] if r['kind']=='冲突']
# 正例：现字有人裁实例（非自身）的格，随机抽
st=ProductStore(); pool=[]
for p in range(3,57):
    for s in page_slots(st,'bxgb',p):
        if s.is_text and s.char in ex and s.channel!='human' and not s.sub: pool.append((s.id,s.char))
random.seed(1); pos=random.sample(pool,700)
out={'neg':[],'pos':[]}
for id,ch,cur in neg:
    r=best(id,ch); out['neg'].append((id,ch,cur)+tuple(r) if r else None)
for id,ch in pos:
    r=best(id,ch)
    if r: out['pos'].append((id,ch)+tuple(r))
json.dump(out,open(sys.argv[2],'w'),ensure_ascii=False)
print(len(out['neg']),len(out['pos']))
