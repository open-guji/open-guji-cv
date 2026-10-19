import json
def yolo_columns(r, drop_mid=True, conf_min=0.0):
    """YOLO 原生结果 → 物理列（右→左），每列 [char dict...]。版面框按水平重叠(>0.4×较窄宽)并查集归列。"""
    ts=sorted(r['type'],key=lambda b:b[7])
    n=len(ts); par=list(range(n))
    def f(i):
        while par[i]!=i: par[i]=par[par[i]]; i=par[i]
        return i
    for i in range(n):
        for j in range(i+1,n):
            a,b=ts[i],ts[j]
            ov=min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0])
            if ov>0.4*min(a[2],b[2]): par[f(i)]=f(j)
    groups={}
    for i in range(n): groups.setdefault(f(i),[]).append(i)
    cols=[]
    for g in groups.values():
        cls=[ts[i][4] for i in g]
        if drop_mid and all(c in('midText','midSubText') for c in cls): continue
        x0=min(ts[i][0] for i in g); x1=max(ts[i][0]+ts[i][2] for i in g)
        cols.append(dict(tids=set(i+1 for i in g),x0=x0,x1=x1,chars=[]))
    # 只含夹注的相邻两组（两半列）合并：间距小且合宽像一列
    cols.sort(key=lambda c:-(c['x0']+c['x1'])/2)
    for c in r['chars']:
        if c['conf']<conf_min: continue
        for col in cols:
            if c['col'] in col['tids']: col['chars'].append(c); break
    return cols
def their_colcounts(r_release, boxes_fn):
    bs=boxes_fn(r_release); cols=[]
    for b in bs:
        cx=(b['x0']+b['x1'])/2
        if cols and abs(cols[-1]['cx']-cx)<55: cols[-1]['n']+=1
        else: cols.append({'cx':cx,'n':1})
    return [c['n'] for c in cols]
def ours_colcounts(chars, ncols=9):
    cnt=[0]*ncols
    for c in chars:
        if 1<=c['col']<=ncols: cnt[c['col']-1]+=1
    return cnt
def compare_counts(pred, truth):
    """按列位置比较（右起对齐）；返回 (正确列数, 列总数)。列数不同则多出/缺的列都算错。"""
    n=max(len(pred),len(truth)); ok=0
    for i in range(n):
        a=pred[i] if i<len(pred) else None; b=truth[i] if i<len(truth) else None
        ok+= (a==b and a is not None)
    return ok,len(truth)
def drop_edge_strips(cols, W):
    """去掉页边的窄条（版心/书耳被当 text）：宽 <0.7×中位列宽 且贴页边 5% 以内"""
    if not cols: return cols
    import statistics
    mw=statistics.median([c['x1']-c['x0'] for c in cols])
    out=[]
    for i,c in enumerate(cols):
        edge=(c['x1']>W*0.95) or (c['x0']<W*0.05)
        if edge and (c['x1']-c['x0'])<0.7*mw and i in (0,len(cols)-1): continue
        out.append(c)
    return out
def clean_chars(cols, area_frac=0.25, nms=0.5):
    """轻清理：面积 < area_frac×页中位面积 的碎框丢掉；跨条重复框（IoU>nms）只留置信高的"""
    import statistics
    allc=[c for col in cols for c in col['chars']]
    if not allc: return cols
    ma=statistics.median([c['xywh'][2]*c['xywh'][3] for c in allc])
    keep=[c for c in allc if c['xywh'][2]*c['xywh'][3]>=area_frac*ma]
    keep.sort(key=lambda c:-c['conf']); final=[]
    def iou(a,b):
        ax0,ay0,aw,ah=a; bx0,by0,bw,bh=b
        iw=min(ax0+aw,bx0+bw)-max(ax0,bx0); ih=min(ay0+ah,by0+bh)-max(ay0,by0)
        if iw<=0 or ih<=0: return 0
        i=iw*ih; return i/(aw*ah+bw*bh-i)
    for c in keep:
        if all(iou(c['xywh'],d['xywh'])<=nms for d in final): final.append(c)
    ids=set(id(c) for c in final)
    for col in cols: col['chars']=[c for c in col['chars'] if id(c) in ids]
    return cols
def yolo_eval_cols(r, clean=True):
    cols=drop_edge_strips(yolo_columns(r,conf_min=0.4 if clean else 0.0),r['hw'][1]) if clean else yolo_columns(r,drop_mid=False)
    if clean: cols=clean_chars(cols)
    return cols
