import sys,json,numpy as np,cv2
from open_guji_cv.clustering.near_shape import NearShapeConfig, diff_map, _prep, _shift_to
from open_guji_cv.clustering.match import _shape_font_template
S=sys.argv[1]; d=np.load(f'{S}/siku.npz'); prov=json.load(open(f'{S}/prov.json'))
ids=[str(i) for i in d['ids']]; ch=list(d['chars']); P=d['P']; cfg=NearShapeConfig()
def conc(M,q=0.12):
    v=np.sort(M.ravel())[::-1]; return v[:int(len(v)*q)].sum()/(v.sum()+1e-9)
def g(x): x=x/(x.max()+1e-9); return cv2.cvtColor(cv2.resize((255-255*x).astype(np.uint8),(160,160),interpolation=cv2.INTER_NEAREST),cv2.COLOR_GRAY2BGR)
def hm(x): return cv2.applyColorMap(cv2.resize((255*x/(x.max()+1e-9)).astype(np.uint8),(160,160),interpolation=cv2.INTER_NEAREST),cv2.COLORMAP_JET)
rows=[];stats=[]
for a,b in [('𫎇','蒙'),('大','太'),('論','諭'),('日','目'),('人','入'),('曾','會'),('回','囘')]:
    A=[P[j] for j,i in enumerate(ids) if ch[j]==a and 'human' in prov.get(i,[])][:40]
    B=[P[j] for j,i in enumerate(ids) if ch[j]==b and 'human' in prov.get(i,[])][:40]
    ma,mb,F,W=diff_map(A,B,cfg)
    # 前人做法：单例两两（字体渲染，没有就用各自第一条刻例）对齐后残差
    fa,fb=_shape_font_template(a),_shape_font_template(b)
    src='font'
    if fa is None or fb is None: fa,fb,src=A[0],B[0],'exemplar'
    pa=_prep(fa,cfg.sigma); pb=_shift_to(_prep(fb,cfg.sigma),pa,cfg.align); R=(pa-pb)**2
    # 单例刻例对也算一个
    ea=_prep(A[0],cfg.sigma); eb=_shift_to(_prep(B[0],cfg.sigma),ea,cfg.align); R2=(ea-eb)**2
    stats.append(dict(pair=a+b,nA=len(A),nB=len(B),fisher_top12=round(float(conc(F)),3),font_resid_top12=round(float(conc(R)),3),ex_resid_top12=round(float(conc(R2)),3),resid_src=src))
    ov=g((ma+mb)/2); mk=cv2.resize((W>0).astype(np.uint8),(160,160),interpolation=cv2.INTER_NEAREST)>0
    ov[mk]=(0.45*ov[mk]+0.55*np.array([0,0,255])).astype(np.uint8)
    row=np.hstack([g(ma),g(mb),hm(F),ov,hm(R),hm(R2)])
    rows.append(cv2.copyMakeBorder(row,4,4,4,4,cv2.BORDER_CONSTANT,value=(255,255,255)))
cv2.imwrite(sys.argv[2],np.vstack(rows))
print(json.dumps(stats,ensure_ascii=False,indent=0))
json.dump(stats,open(sys.argv[3],'w'),ensure_ascii=False,indent=1)
