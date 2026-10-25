import json,sys,csv,collections
sys.path.insert(0,'/home/user/open-guji-cv')
exec(open('/home/user/r9/sheet.py').read().split('def main')[0])
import cv2
from open_guji_cv.core.anchor import crop_patch
from open_guji_cv.groups.flow import FlowConfig, decide
class R: pass
def patch(cid):
    v,p=cid.split(':')[0],int(cid.split(':')[1])
    sh=json.load(open(f'/home/user/prod/{v}/cell_shrink/p{p:04d}.json'))['char_index']['columns']
    b={c['id']:c['bbox_page'] for col in sh for c in col['chars']}.get(cid)
    I=img(v,p)
    return crop_patch(I,tuple(b)) if b is not None else None
cfg=FlowConfig(groups=('zheng',))
def run(cid,cur):
    r=R(); r.id=cid; r.char=cur
    ch,why,trail=decide('zheng',r,[],None,cfg,patch_fn=patch,review=True)
    t=[x for x in trail if x['solver']=='ids'][0]
    return t.get('char'),t.get('margin'),t.get('form')
mode=sys.argv[1]
if mode=='labels':
    import os
    for l in open('/home/user/open-guji-dataset/char-groups/labels/unified.jsonl'):
        r=json.loads(l)
        if r['form'] in ('徵','徴') and r['kind']=='shape' and os.path.exists('/home/user/prod/'+r['id'].split(':')[0]):
            try: print(r['id'],r['form'],*run(r['id'],r['form']))
            except Exception as e: print(r['id'],'ERR',e)
else:
    for r in csv.DictReader(open(sys.argv[2]),delimiter='\t'):
        if r['键']=='zheng': print(r['格'],r['整理本'],r['库前二'],*run(r['格'],r['整理本']))
