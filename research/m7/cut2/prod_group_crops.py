import json,glob,sys,os
sys.path.insert(0,'/home/user/open-guji-cv')
import numpy as np
from PIL import Image
import cv2
from open_guji_cv.groups.ids_segment import ink_of
G=sys.argv[1]
WS=glob.glob('/home/user/guji-workspace/96mid*/data_full/zongmu')[0]
src=open('/tmp/jiao2/build2.py').read(); exec(src[src.index("def clean"):src.index("sel=[h for h")])
cells=json.load(open(f'/tmp/jiao2/prod_{G}.json'))
out=f'/tmp/grp/{G}'; os.makedirs(out+'/crops',exist_ok=True)
lab=[]; cache={}
for cid,ch,prov in cells:
    v,p,c,s=cid.split(':')[:4]
    if not s.isdigit(): continue
    k=(v,p)
    if k not in cache:
        cache=dict()  # keep one page at a time
        cache[k]=(json.load(open(f'/tmp/prod/{v}/row_segment/p{int(p):04d}.json'))['cells'],Image.open(f'{WS}/{v}/{p}.png').convert('L'))
    d,im=cache[k]; q=None
    for col in d['columns']:
        if col['col']==int(c):
            for ce in col['cells']:
                if ce.get('slot')==int(s) and ce.get('sub') is None: q=ce['quad_page']
    if not q: continue
    xs=[im.width-pt[0] for pt in q]; ys=[pt[1] for pt in q]
    a=clean(np.asarray(im.crop((int(min(xs))-6,int(min(ys))-6,int(max(xs))+6,int(max(ys))+6))))
    Image.fromarray(a).save(f"{out}/crops/{cid.replace(':','_')}.png"); lab.append(dict(id=cid,form=ch,prov=prov))
open(out+'/labels.jsonl','w').write(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in lab)); print(G,len(lab))
