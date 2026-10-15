# 用法：python3 chk_boxes.py <产物根的上级目录，内含 tcA/ tcB/> A,45,5:19 B,45,5:19 ...  （A/B＝从哪边取格；只读 cell_shrink 的 bbox_page，自己算 IoU／重叠系数，不用 Eden 的脚本）
import json,sys
S=sys.argv[1]
def load(root,pg):
    d=next(iter(json.load(open(f"{root}/vol05/cell_shrink/p{pg:04d}.json")).values()))
    o={}
    for c in d['columns']:
        for r in c.get('chars') or []:
            b=r.get('bbox_page')
            if b: o[r['id']]=b
    return o
def inter(a,b):
    w=min(a[2],b[2])-max(a[0],b[0]); h=min(a[3],b[3])-max(a[1],b[1])
    return max(w,0)*max(h,0)
def ar(a): return (a[2]-a[0])*(a[3]-a[1])
def iou(a,b):
    i=inter(a,b); return i/(ar(a)+ar(b)-i)
def oc(a,b): return inter(a,b)/min(ar(a),ar(b))
def near(M,box,k=3):
    r=sorted(((iou(box,b),oc(box,b),i) for i,b in M.items()),reverse=True)[:k]
    return "; ".join(f"{i.split(':',2)[2]} iou={u:.2f} oc={o:.2f}" for u,o,i in r)
cache={}
def get(pg):
    if pg not in cache: cache[pg]=(load(S+"/tcA",pg),load(S+"/tcB",pg))
    return cache[pg]
for tag,pg,col_id in [(a.split(',')[0],int(a.split(',')[1]),a.split(',')[2]) for a in sys.argv[2:]]:
    A,B=get(pg)
    id_=f"vol05:{pg}:{col_id}"
    if tag=="A":  # A 格 → B 里最近
        print(f"[A]{id_} box={A[id_]} → B近邻：{near(B,A[id_])}")
    else:
        print(f"[B]{id_} box={B[id_]} → A近邻：{near(A,B[id_])}")
