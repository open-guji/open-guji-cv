import json,sys,collections
from pathlib import Path
import cv2, numpy as np
ws=Path(sys.argv[1]); vol=sys.argv[2]; out=sys.argv[3]
items=[]
for f in sorted((ws/'products'/vol/'cell_shrink').glob('p*.json')):
    pg=int(f.stem[1:]); d=json.loads(f.read_text())['char_index']
    for c in d['columns']:
        n=len(c['chars'])
        for i,r in enumerate(c['chars']):
            for fl in ('ref_blank','ref_char'):
                if fl in r['flags']:
                    items.append((fl,pg,c['col'],r['slot'],r.get('sub'),r['bbox_col'],i,n,r['flags']))
cnt=collections.Counter((it[0], 'end' if it[6] in (0,1) or it[6]>=it[7]-2 else 'mid') for it in items)
print(len(items),cnt)
# 拼图：每个格周围 ±0.6 格裁一块
tiles=[]
for fl,pg,col,slot,sub,(x0,y0,x1,y1),i,n,flags in items:
    img=cv2.imread(str(ws/'cache'/vol/'column_image'/f'p{pg:04d}c{col:02d}.png'),0)
    if img is None: continue
    h,w=img.shape; pad=70
    a,b=max(0,int(y0)-pad),min(h,int(y1)+pad)
    t=cv2.cvtColor(img[a:b,:],cv2.COLOR_GRAY2BGR)
    cv2.rectangle(t,(int(x0),int(y0)-a),(int(x1),int(y1)-a),(0,0,255) if fl=='ref_blank' else (0,160,0),3)
    t=cv2.resize(t,(200,int(200*t.shape[0]/t.shape[1])))
    t=cv2.copyMakeBorder(t[:330],0,max(0,330-t[:330].shape[0]),0,0,cv2.BORDER_CONSTANT,value=(255,255,255))
    cv2.putText(t,f'{pg}:{col}:{slot}{sub or ""}',(2,18),cv2.FONT_HERSHEY_SIMPLEX,0.55,(255,0,0),2)
    tiles.append(t)
rows=[np.hstack(tiles[i:i+10]+[np.full((330,200,3),255,np.uint8)]*(10-len(tiles[i:i+10]))) for i in range(0,len(tiles),10)]
for k in range(0,len(rows),4):
    cv2.imwrite(out.replace('.png',f'_{k//4}.png'),np.vstack(rows[k:k+4]))
print('sheets',(len(rows)+3)//4)
