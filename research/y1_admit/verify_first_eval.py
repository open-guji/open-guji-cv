import json,sys,collections
sys.path.insert(0,'.')
from lib import load_step
rows=json.load(open(sys.argv[1])); sa=load_step(sys.argv[2],sys.argv[3],'seed_admit')
n=len(rows); wr=[r for r in rows if r['ref']]
print('标签格',n,'有整理本字',len(wr),'有E刻例',sum(1 for r in wr if r.get('n_rows')))
base_admit=[r for r in rows if sa[r['cell']]['admit']]
print('基线放行',len(base_admit),'其中金标误放行',sum(sa[r['cell']]['char']!=r['truth'] for r in base_admit))
def evalrule(name,f):
    adm=[]; 
    for r in wr:
        ch=f(r)
        if ch: adm.append((r,ch))
    bad=[(r['cell'],ch,r['truth']) for r,ch in adm if ch!=r['truth']]
    newadm=[(r,ch) for r,ch in adm if not sa[r['cell']]['admit']]
    newbad=[(r['cell'],ch,r['truth']) for r,ch in newadm if ch!=r['truth']]
    lost=[r for r in wr if sa[r['cell']]['admit'] and not any(r is a for a,_ in adm)]
    print(f'{name:34s} 放行{len(adm):5d} 误放行{len(bad):3d} | 比基线新增{len(newadm):4d} 其中误{len(newbad):3d} | 基线放而此规则不放{len(lost)}')
    return bad,newbad
def best(r):
    eb=r.get('E_best') or []
    return eb[0] if eb else None
def refcov(r):
    for c,cov,w,v in (r.get('E_best') or []):
        if c==r['ref']: return cov,w,v
    return None
def v_same(r):
    b=best(r)
    return b[0] if b and b[3]=='same' else None
evalrule('V1 E内有字判 same',v_same)
for t in (0.995,0.99,0.985,0.98,0.975,0.97,0.96):
    evalrule(f'V2 ref cov>={t}',lambda r,t=t:(r['ref'] if (refcov(r) and refcov(r)[0]>=t) else None))
for t in (0.99,0.98,0.97):
    for d in (0.0,0.01,0.02):
        evalrule(f'V3 ref cov>={t} 且全库首位不压过>{d}',lambda r,t=t,d=d:(r['ref'] if (refcov(r) and refcov(r)[0]>=t and (r['full_top'] in (r.get('E') or []) or r['full_cov']-refcov(r)[0]<=d)) else None))
# 速度
tc=[r['t_check'] for r in wr if 't_check' in r]; tf=[r['t_full'] for r in wr if 't_full' in r]
import statistics as st
print('耗时(s/格) 核对',round(st.mean(tc),4),'中位',round(st.median(tc),4),' 全库',round(st.mean(tf),4),'中位',round(st.median(tf),4))
