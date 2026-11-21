# -*- coding: utf-8 -*-
"""把 collect 出的 cards.jsonl + crops 按字头分页（每页约 110 格），避免一页格太多卡顿。路径写死在 /tmp/work，用时改。"""
import sys,json,base64,collections,cv2,numpy as np
sys.path.insert(0,'/home/user/open-guji-cv/scripts'); sys.path.insert(0,'/home/user/open-guji-cv')
import build_newchar_review as B
cards=[json.loads(l) for l in open('/tmp/work/out2/cards.jsonl')]
pre=json.load(open('/tmp/work/pre_r1.json'))
imgs={}
for c in cards:
    f=f"/tmp/work/out2/crops/{c['id'].replace(':','_')}.png"
    try: raw=open(f,'rb').read()
    except: continue
    im=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_GRAYSCALE)
    if im is None: continue
    h,w=im.shape;s=B.IMG_H/h
    im=cv2.resize(im,(max(1,round(w*s)),B.IMG_H),interpolation=cv2.INTER_AREA)
    im=(im//16*16+8).astype('uint8');ok,buf=cv2.imencode('.png',im)
    imgs[c['id']]="data:image/png;base64,"+base64.b64encode(buf.tobytes()).decode()
# groups in the same order as page: kind:grp, by size desc
g=collections.OrderedDict()
for c in cards: g.setdefault(c['kind']+':'+c['grp'],[]).append(c)
gl=sorted(g.values(),key=lambda x:(-len(x),x[0]['grp']))
chunks=[[]]
for grp in gl:
    if sum(len(x) for x in chunks[-1])+len(grp)>110 and chunks[-1]: chunks.append([])
    chunks[-1].append(grp)
print(len(chunks),[sum(len(x) for x in c) for c in chunks])
for i,ch in enumerate(chunks,1):
    cs=[c for grp in ch for c in grp]
    ids={c['id'] for c in cs}
    html=B.build_html_grouped(cs,{k:v for k,v in imgs.items() if k in ids},{k:v for k,v in pre.items() if k in ids})
    html=html.replace('<title>新字确认</title>',f'<title>补库确认 第{i}页</title>',1)
    open(f'/tmp/work/page{i}.html','w').write(html)
    json.dump(cs,open(f'/tmp/work/page{i}.cards.json','w'),ensure_ascii=False)
    print(i,len(html)//1024,'KB')
