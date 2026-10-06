# vol02 人裁漂移检查：人裁时存进字形库的图块 vs 同一 id 现在的字块
import sys,json,cv2,numpy as np,sqlite3,glob
sys.path.insert(0,'/home/sheldon/open-guji-cv')
from open_guji_cv.feedback.lookup import human_chars
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.report.slots import page_slots
from open_guji_cv.clustering.normalize import normalize_patch
from open_guji_cv.clustering.verify import verify_pair_elastic
from open_guji_cv.utils.image_io import imread
W=glob.glob('/home/sheldon/guji-workspace/96mid1ogzk-*')[0]; book='vol02'
db=sqlite3.connect(f'{W}/output/glyph.db'); st=ProductStore(); cache=ImageCache()
inst={}
for iid,png,lab in db.execute("select instance_id,patch_png,label from instances where label_status='human' and instance_id like ?",('%'+book+':%',)):
    inst[iid.replace('v2:','')]=(png,lab)
h=human_chars(book); pages={}; out=[]
for k,(sh,rd) in h.items():
    p=int(k.split(':')[1])
    if p not in pages:
        try: pages[p]={s.id:s for s in page_slots(st,book,p)}
        except Exception: pages[p]={}
    s=pages[p].get(k)
    _,pp,c,sl=k.split(':'); sub=sl[-1] if sl[-1] in 'ab' else ''; sl=sl.rstrip('ab')
    path=cache.get(book,'char_patch',f'p{int(pp):04d}c{int(c):02d}s{sl}{sub}')
    rec=dict(id=k,label=sh,cur=None if s is None else s.char,channel=None if s is None else s.channel,has_cell=s is not None,has_patch=path is not None,has_inst=k in inst,cov=None)
    if path is not None and k in inst:
        cur=normalize_patch(imread(str(path),0))
        old=normalize_patch(cv2.imdecode(np.frombuffer(inst[k][0],np.uint8),0))
        v=verify_pair_elastic(cur,old); rec['cov']=round(float(v.f1),4)
    out.append(rec)
json.dump(out,open(sys.argv[1],'w'),ensure_ascii=False)
import collections
def cat(r):
    if not r['has_cell']: return '格已不存在'
    if r['cur'] is None: return '格不出字'
    applied = r['channel']=='human'
    same = r['cur']==r['label']
    if r['cov'] is None: drift='无法核对'
    else: drift='位置漂移' if r['cov']<0.9 else '位置未变'
    return f"{'已采信' if applied else '未采信'}/{'字同' if same else '字异'}/{drift}"
c=collections.Counter(cat(r) for r in out)
for k,v in sorted(c.items()): print(k,v)
