"""字形库优先识别的模拟：逐页增量匹配，量覆盖率与错配率。

用 char-clustering 分片的金标标签模拟一个「已验证字形库」：
按页序处理，每个新实例先在当前库里 kNN(HOG) 取候选，
verify_pair_cov 完美匹配(0.992,12)则继承库条目的字；然后该实例带
金标进库（模拟兜底分支最终解决 = 良性循环的上界）。
"""
import json, sys
from pathlib import Path
import cv2, numpy as np
sys.path.insert(0,'/home/user/open-guji-cv')
from open_guji_cv.clustering.features import get_feature
from open_guji_cv.clustering.verify import verify_pair_cov

DS=Path('/home/user/open-guji-dataset/char-clustering/samples')
K=10

def load(shard):
    d=json.load(open(DS/shard/'expected.json'))
    inst=sorted(d['instances'], key=lambda x:(int(x['page']),x['instance_id']))
    pats=np.zeros((len(inst),64,64),np.uint8)
    for i,x in enumerate(inst):
        img=cv2.imread(str(DS/shard/x['crop']),cv2.IMREAD_GRAYSCALE)
        pats[i]=(img>127).astype(np.uint8)
    feats=get_feature('hog').extract(pats)
    return inst,pats,feats

def run(inst,pats,feats,seed_n=0,seed_data=None,tag=''):
    """seed_data=(inst,pats,feats) 作为初始库（跨册冷启动用）。"""
    db_idx=[]; db_chars=[]
    db_feats=[]
    if seed_data:
        si,sp,sf=seed_data
        for i,x in enumerate(si):
            db_idx.append(('seed',i)); db_chars.append(x['char']); db_feats.append(sf[i])
    matched=0; correct=0; results=[]
    for i,x in enumerate(inst):
        pred=None
        if len(db_chars)>=1:
            F=np.asarray(db_feats)
            sims=F@feats[i]
            top=np.argsort(-sims)[:K]
            best=None
            for j in top:
                src,jj=db_idx[j]
                p2 = seed_data[1][jj] if src=='seed' else pats[jj]
                v=verify_pair_cov(pats[i],p2)
                if v.verdict=='same' and (best is None or v.f1>best[0]):
                    best=(v.f1,db_chars[j])
            if best: pred=best[1]
        if pred is not None:
            matched+=1
            if pred==x['char']: correct+=1
            results.append((x['instance_id'],x['char'],pred))
        db_idx.append(('cur',i)); db_chars.append(x['char']); db_feats.append(feats[i])
        if (i+1)%1000==0:
            print(f"  [{tag}] {i+1}/{len(inst)} 覆盖 {matched/(i+1):.1%} 精度 {correct/max(1,matched):.4f}", flush=True)
    n=len(inst)
    wrong=[(a,g,p) for a,g,p in results if g!=p]
    print(f"[{tag}] 总覆盖 {matched}/{n}={matched/n:.1%}  匹配精度 {correct}/{matched}={correct/max(1,matched):.4f}")
    # 后半段覆盖率（库热起来之后）
    half=n//2
    m2=c2=0; seen=0
    # 重跑统计后半段太贵，用累计差近似：直接重算后半在结果里的占比
    idset={x['instance_id'] for x in inst[half:]}
    mh=sum(1 for a,g,p in results if a in idset)
    ch=sum(1 for a,g,p in results if a in idset and g==p)
    print(f"[{tag}] 后半段覆盖 {mh}/{n-half}={mh/(n-half):.1%}  精度 {ch}/{max(1,mh)}={ch/max(1,mh):.4f}")
    if wrong[:8]: print(f"[{tag}] 错配样例:", [(g,p) for _,g,p in wrong[:8]])
    return results

if __name__=='__main__':
    i2,p2,f2=load('002-vol02-body')
    run(i2,p2,f2,tag='vol02 册内增量')
    i1,p1,f1=load('001-vol01-body')
    run(i1,p1,f1,tag='vol01 册内增量')
    # 跨册冷启动：vol01 全量当库，vol02 当查询
    run(i2,p2,f2,seed_data=(i1,p1,f1),tag='vol02 | 库=vol01（跨册冷启动）')
