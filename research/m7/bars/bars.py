import numpy as np, cv2
def load(path):
    g=cv2.imread(path,0); return g
def ink(g):
    _,b=cv2.threshold(g,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU); return b>0
def main_cc(b):
    k=cv2.dilate(b.astype(np.uint8),np.ones((5,5),np.uint8))
    n,lab,st,_=cv2.connectedComponentsWithStats(k)
    if n<2: return None
    # biggest by area*height preference
    i=1+int(np.argmax(st[1:,cv2.CC_STAT_AREA]))
    m=(lab==i)&b
    ys,xs=np.where(m); 
    return m[ys.min():ys.max()+1, xs.min():xs.max()+1]
def runs(row,gap=2):
    best=0;cur=0;gp=0;start=None;bs=None;be=None
    xs=np.where(row)[0]
    if len(xs)==0: return 0,0,0
    s=xs[0];p=xs[0];res=(0,s,s)
    for x in xs[1:]:
        if x-p-1>gap:
            if p-s+1>res[0]: res=(p-s+1,s,p)
            s=x
        p=x
    if p-s+1>res[0]: res=(p-s+1,s,p)
    return res
def profile(m):
    return np.array([runs(r)[0] for r in m])
def bars(m):
    """返回横画带 [(y0,y1,len)]。横画：行内最长连续墨长 > max(0.3W, 2.2*茎宽)"""
    H,W=m.shape
    L=profile(m)
    stem=np.median(m.sum(0)[m.sum(0)>0.5*H]) if (m.sum(0)>0.5*H).any() else 0
    colsum=m.sum(0); 
    thr=max(0.3*W, 0)
    on=L>thr
    out=[];y=0
    while y<H:
        if on[y]:
            y0=y
            while y<H and on[y]: y+=1
            out.append((y0,y-1,int(L[y0:y].max())))
        else: y+=1
    return out,L
