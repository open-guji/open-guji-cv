# -*- coding: utf-8 -*-
"""数据驱动的形近度（A23 2026-11-06）：库里每个字（折叠后）的刻例 HOG 特征取质心，字与字质心的
最大余弦 = 该字的「最近异字相似度」rival。用法：
    python scripts/analyze_match_rival.py <glyph.db> <out.json>      # {字: [rival, 最近异字, 刻例数]}
再用 analyze_match_gate.py 的框架按 rival 分档拟合分差闸（结论见 ai-team 5a比对基准 第六节）。
rival 与首位字的错误率单调相关：殿本 <0.80 时 0.978、≥0.95 时 0.943；史記 0.998→0.943。
"""
import sys,json,numpy as np
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parent))
from eval_match_bench import build_matcher
from eval_fold import fold
db,out=sys.argv[1],sys.argv[2]
m,_=build_matcher(db);full=getattr(m,'_full',m)
L=np.asarray(full.library_matrix(),dtype=np.float32)
ids,chars=full._ids,full._chars
keep=[i for i,x in enumerate(ids) if not str(x).startswith('font:')]
by={}
for i in keep: by.setdefault(fold(chars[i]),[]).append(i)
cs=sorted(by);C=np.stack([L[by[c]].mean(0) for c in cs]);C/=np.linalg.norm(C,axis=1,keepdims=True)+1e-9
S=C@C.T;np.fill_diagonal(S,-1)
rj={c:[float(S[k].max()),cs[int(S[k].argmax())],len(by[c])] for k,c in enumerate(cs)}
json.dump(rj,open(out,'w'),ensure_ascii=False)
v=np.array([x[0] for x in rj.values()]);print(len(cs),np.percentile(v,[10,50,90,99]).round(3))
