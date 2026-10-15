import os,sys,json,re
import cv2,numpy as np
R='/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本/data_full/zongmu/'
sel=json.load(open('/tmp/s8sandbox/rishi_set.json'))
lab=dict(sel['lab']); src=dict(sel['src'])
seven={'vol05:22:6:16':'曰','vol05:22:9:16':'曰','vol05:120:6:16':'曰','vol05:152:1:15':'曰','vol05:182:8:20':'曰','vol05:54:7:21':'大','vol05:99:2:20':'出'}
cells=list(lab)+list(seven)
os.environ['GUJI_PRODUCTS_DIR']='/tmp/s8sandbox/p208eu'
os.environ['GUJI_WORKSPACE']='/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本'
import open_guji_cv.steps
from open_guji_cv.core.spec import page_key
from open_guji_cv.products.store import ProductStore
st=ProductStore(); cache={}
def feat(k):
    m=re.match(r'(vol\d+):(\d+):(\d+):(-?\d+)([ab])?$',k); b,p,col,slot,sub=m[1],int(m[2]),int(m[3]),int(m[4]),m[5] or ''
    if (b,p) not in cache: cache[(b,p)]=(st.read(b,'cell_shrink',page_key(p),'char_index'),cv2.imread(R+f'{b}/{p}.png',0))
    ci,im=cache[(b,p)]
    if ci is None or im is None: return None
    cc=ci.column(col)
    if cc is None: return None
    t=next((x for x in cc.chars if x.slot==slot and (x.sub or '')==sub),None)
    if t is None: return None
    W=im.shape[1]; x0,y0,x1,y1=t.bbox_page; X0,X1=int(round(W-x1)),int(round(W-x0)); Y0,Y1=int(round(y0)),int(round(y1))
    _,bw=cv2.threshold(im,0,1,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
    cr=bw[max(Y0,0):Y1,max(X0,0):X1]
    if cr.sum()<50: return None
    n0,l0,s0,_=cv2.connectedComponentsWithStats(cr.astype(np.uint8),connectivity=8)
    areas=s0[1:,cv2.CC_STAT_AREA]; keep=[i+1 for i,a in enumerate(areas) if a>=0.12*areas.max()]
    cr=np.isin(l0,keep).astype(np.uint8)
    ys,xs=np.where(cr); tx0,tx1,ty0,ty1=xs.min(),xs.max(),ys.min(),ys.max()
    g=cr[ty0:ty1+1,tx0:tx1+1]; h,w=g.shape
    # horizontal strokes: rows where ink fraction >0.45
    rp=g.mean(1); strong=rp>0.45
    runs=[];i=0
    while i<h:
        if strong[i]:
            j=i
            while j<h and strong[j]: j+=1
            runs.append(((i+j-1)/2/h,(j-i)/h)); i=j
        else: i+=1
    # cavities: enclosed background components
    inv=(1-g).astype(np.uint8); n,lbl,stt,_=cv2.connectedComponentsWithStats(inv,connectivity=4)
    cav=[]
    for q in range(1,n):
        x,y,ww,hh,a=stt[q]
        if x>0 and y>0 and x+ww<w and y+hh<h and a>0.01*w*h: cav.append(a/(w*h))
    # left/right vertical extents: fraction of rows with ink in leftmost/rightmost 12% columns
    lw=max(2,int(0.12*w)); L=(g[:,:lw].sum(1)>0).mean(); Rr=(g[:,-lw:].sum(1)>0).mean()
    # mid-bar: horizontal run nearest middle; its relative length
    midlen=None;midy=None
    if runs:
        mid=min(runs,key=lambda r:abs(r[0]-0.5)); midy=mid[0]
        yy=int(round(mid[0]*h)); row=g[max(0,yy-1):yy+2].max(0); midlen=float(row.mean())
    return dict(w=int(w),h=int(h),wh=round(w/h,3),box_w=X1-X0,box_h=Y1-Y0,box_wh=round((X1-X0)/(Y1-Y0),3),ink=round(float(g.mean()),3),n_bars=len(runs),bar_y=[round(r[0],2) for r in runs],midy=None if midy is None else round(midy,3),midlen=None if midlen is None else round(midlen,3),ncav=len(cav),cav=[round(c,3) for c in cav],Lv=round(float(L),2),Rv=round(float(Rr),2))
out={}
for k in cells:
    try: f=feat(k)
    except Exception as e: f=None
    if f: f['label']=lab.get(k) or seven[k]; f['src']=src.get(k,'seven'); out[k]=f
json.dump(out,open('/tmp/s8sandbox/rishi_feats_cc.json','w'),ensure_ascii=False)
print(len(out),len(cells))
