# -*- coding: utf-8 -*-
"""负结果实验（Q2 道 2026-09-30）：match_pairs 用软融合分数 cov-α·wmax/100 替代「cov≥闸 且 wmax≤12」。
    GUJI_WORKSPACE=<书目录> PYTHONPATH=. python scripts/exp_pairs_soft_margin_cv.py dump.npz
dump 由 `eval_match_pairs.py --dump` 产出。按页 crc32 分两折，一折定 (α,闸)、另一折验 precision≥0.999。
结论见 HANDOFF_Q2.md：全量 recall 可升到 0.26，但留出折 fp 7~10（precision<0.999），基线硬规则两折都守住。
"""
import sys, json, zlib, numpy as np
sys.path.insert(0,'.')
from open_guji_cv.clustering.exclusions import excluded_ids
z=np.load(sys.argv[1],allow_pickle=True); pairs=list(z['pairs']); cov=z['cov']; wmax=z['wmax']
ds='../open-guji-dataset/glyph-match/pairs'
meta={r['instance_id']:r['char'] for r in json.load(open(ds+'/expected.json'))['instances']}
ex=excluded_ids()
keep=np.array([p['origin']=='knn' and p['a'] not in ex and p['b'] not in ex for p in pairs])
same=np.array([meta[p['a']]==meta[p['b']] for p in pairs])
idx=np.where(keep)[0]; c,w,s=cov[idx],wmax[idx],same[idx]
pg=lambda i:'_'.join(i.split('_')[:2])
fold=np.array([zlib.crc32((pg(pairs[i]['a'])+pg(pairs[i]['b'])).encode())%2 for i in idx])
print('fold sizes',[(fold==k).sum() for k in (0,1)], 'same',[(s&(fold==k)).sum() for k in (0,1)])
gs=np.round(np.arange(0.95,1.0005,0.0005),4)
def rule(alpha,hard):   # pass if cov-alpha*w/100>=g and w<=hard
    return c-alpha*w/100.0, w<=hard
def fit(mask,alpha,hard):
    sc,hk=rule(alpha,hard); best=None
    for g in np.round(np.arange(0.90,1.0005,0.0005),4):
        ok=(sc>=g)&hk&mask; tp=(ok&s).sum(); fp=(ok&~s).sum()
        if tp+fp and tp/(tp+fp)>=0.999:
            r=tp/(s&mask).sum()
            if best is None or r>best[1]: best=(g,r,tp,fp)
    return best
def ev(mask,alpha,hard,g):
    sc,hk=rule(alpha,hard); ok=(sc>=g)&hk&mask; tp=(ok&s).sum(); fp=(ok&~s).sum()
    return tp/(s&mask).sum(), tp, fp
for alpha in [0, 0.1, 0.2, 0.3, 0.4, 0.5, 1]:
  for hard in [12]:
    out=[]
    for k in (0,1):
        tr=fold==k; te=fold==1-k
        b=fit(tr,alpha,hard)
        r,tp,fp=ev(te,alpha,hard,b[0]); out.append((b[0],round(b[1],4),round(r,4),tp,fp))
    full=fit(np.ones(len(c),bool),alpha,hard)
    print(f'alpha={alpha} hard={hard} full g={full[0]} R={full[1]:.4f} fp={full[3]} | CV',out)
