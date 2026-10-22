import json,sys,glob,os,re
sys.path.insert(0,'/home/user/open-guji-cv')
import numpy as np
from PIL import Image
exec(open('build2.py').read().split("sel=[h for h")[0].split("H=json.load")[0])  # imports only
import cv2
from open_guji_cv.groups.ids_segment import ink_of
src=open('build2.py').read()
exec(src[src.index("def clean"):src.index("sel=[h for h")])
V=json.load(open('v1_raw.json'))
DS='/home/user/open-guji-dataset/char-groups/variant/jiao'
WS=glob.glob('/home/user/guji-workspace/96mid*/data_full/zongmu')[0]
lab={}
for l in open(DS+'/labels.jsonl'):
    r=json.loads(l); lab[r['id']]=r
rej=[]
for cid,v in V.items():
    if v['t']==1: continue   # 机器预点未改动，不算人标
    vol,pg,pos=cid.split(':'); x,y=map(int,re.match(r'x(\d+)y(\d+)',pos).groups())
    if v['v']=='no': rej.append(cid); continue
    if v['v'] not in('jiao','yi'): continue
    form='教' if v['v']=='jiao' else '敎'
    im=Image.open(f'{WS}/{vol}/{pg}.png').convert('L').crop((x-14,y-14,x+138,y+138))
    a=clean(np.asarray(im)); fn=cid.replace(':','_')+'.png'
    Image.fromarray(a).save(f'{DS}/crops/{fn}')
    lab[cid]=dict(id=cid,form=form,by='sheldon',date='2026-10-21',src='教敎补标页v1(模板扫描找格,人点)')
open(DS+'/labels.jsonl','w').write(''.join(json.dumps(v,ensure_ascii=False)+'\n' for v in lab.values()))
open(DS+'/scan_rejects.txt','w').write('\n'.join(rej)+'\n')
import collections; print(collections.Counter(v['form'] for v in lab.values()),len(rej))
