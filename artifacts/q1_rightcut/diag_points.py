import sys, json, cv2, numpy as np
sys.path.insert(0,'scripts')
from _v2_step4 import V2Book
from open_guji_cv.clustering import extractor as X
gold=json.load(open('../open-guji-dataset/char-segmentation/right-cut/expected_v2.json'))['columns']
books={}
for e in gold:
    v=books.setdefault(e['book'],V2Book(e['book']))
    pg=int(e['page']); col=e['col']
    img=v.col_img(pg,col); H,W=img.shape[:2]
    cells=v.cells(pg); cc=[c for c in cells.columns if c.col==col][0]
    x0,x1=cc.content_x
    pc=v.chars(pg); chars=[c for c in [k for k in pc.columns if k.col==col][0].chars if not c.sub and c.cell_type=='char']
    for cr in e['crossings']:
        y=cr['y']; ext=cr['extent']
        host=[r for r in chars if r.bbox_col[1]-2<=y<=r.bbox_col[3]+2]
        hb=[tuple(round(v_) for v_ in r.bbox_col) for r in host]
        # 穿边组件（任意 y 带，取 y±40 横带，全宽）
        ya,yb=max(0,y-40),min(H,y+40)
        zone=(img[ya:yb]<X.BINARY_THRESHOLD_PATCH).astype(np.uint8)
        n,lab,st,_=cv2.connectedComponentsWithStats(zone,8)
        comps=[(int(st[k,0]),int(st[k,0]+st[k,2]),int(st[k,1]+ya),int(st[k,3]),int(st[k,4])) for k in range(1,n) if st[k,0]<=x1-3 and st[k,0]+st[k,2]>=x1+3]
        print(f"{e['book']}/{pg}:{col} y={y} ext={ext} W={W} H={H} content_x=({x0:.0f},{x1:.0f}) ext-x1={ext-x1:.0f} ext>=W-? W-ext={W-ext} host={hb}")
        print("   crossing comps (x0,x1,y0,h,area):",comps)
        # overlay
        vis=cv2.cvtColor(img,cv2.COLOR_GRAY2BGR)
        cv2.line(vis,(int(x1),0),(int(x1),H),(0,0,255),1); cv2.line(vis,(int(x0),0),(int(x0),H),(0,160,0),1)
        for b in hb: cv2.rectangle(vis,(b[0],b[1]),(b[2],b[3]),(255,0,0),1)
        cv2.circle(vis,(ext,y),4,(0,200,255),-1)
        crop=vis[max(0,y-120):min(H,y+120), :]
        crop=cv2.resize(crop,None,fx=3,fy=3,interpolation=cv2.INTER_NEAREST)
        cv2.imwrite(f"artifacts/q1_rightcut/diag_{e['book']}_{pg}_c{col}_y{y}.png",crop)
