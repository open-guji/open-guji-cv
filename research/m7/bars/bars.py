import numpy as np, cv2
def load(path):
    g=cv2.imread(path,0); return g
def ink(g):
    _,b=cv2.threshold(g,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU); return b>0
def main_cc(b):
    k=cv2.dilate(b.astype(np.uint8),np.ones((5,25),np.uint8))
    n,lab,st,_=cv2.connectedComponentsWithStats(k)
    if n<2: return None
    # biggest by area*height preference
    i=1+int(np.argmax(st[1:,cv2.CC_STAT_AREA]))
    m=(lab==i)&b
    ys,xs=np.where(m); 
    return m[ys.min():ys.max()+1, xs.min():xs.max()+1]
def runs(row,gap=14):
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
def profile(m,gap=14):
    return np.array([runs(r,gap)[0] for r in m])
def bars(m,gap=14):
    """返回横画带 [(y0,y1,len)]。横画：行内最长连续墨长 > max(0.3W, 2.2*茎宽)"""
    H,W=m.shape
    L=profile(m,gap)
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

def band_ext(m,b):
    """横画带的全幅：带内墨的最左到最右（横画被竖或版面断口断成几截也算进来）"""
    cols=np.where(m[b[0]:b[1]+1].any(0))[0]
    return int(cols.max()-cols.min()+1)
def ratio(path,gap=8):
    """下横/上横；>1 土、未，<1 士、末；取不到两横返回 None"""
    m=main_cc(ink(load(path)))
    if m is None: return None
    b,_=bars(m,gap)
    if len(b)<2: return None
    t=sorted(sorted(b,key=lambda z:-z[2])[:2],key=lambda z:z[0])
    e=[band_ext(m,x) for x in t]
    return e[1]/e[0]
