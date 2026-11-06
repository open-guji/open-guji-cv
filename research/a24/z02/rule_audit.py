"""L1 规则审计：对全册扫描里每个带组证据的格（窗口 20 字），逐条规则看它给的字与整理本字（ref，现役对位）、放行字对不对。
只统计 ref 是组员的格。输出 TSV：组、规则、命中、与整理本同、与整理本异（冲突）、冲突率、冲突样例。"""
import sys, json, collections, re
sys.path.insert(0, __import__('os').path.dirname(__file__))
from loadall import rows
from open_guji_cv.groups.registry import GROUPS
from open_guji_cv.groups.ctx_l1 import CtxL1Backend, TARGET
from open_guji_cv.groups.flow import rules_path
N={'㓂':'寇','冦':'寇','㑹':'會'}
back={}
def rules_of(g):
    if g not in back:
        try:
            p=rules_path(g); ok=p.exists()
        except TypeError: ok=False
        back[g]=CtxL1Backend(p,GROUPS[g].members).rules if ok else []
    return back[g]
st=collections.defaultdict(lambda:[0,0,0,[]])
for r in rows():
    g=r['g']
    if g not in GROUPS: continue
    ref=r.get('ref'); 
    if not ref or ref=='〓': continue
    mem=GROUPS[g].members
    if ref not in mem: continue
    s=r['L'][-20:]+TARGET+r['R'][:20]
    for ru in rules_of(g):
        if ru.char is None: continue
        if ru.pattern.search(s):
            k=(g,ru.id); v=st[k]; v[0]+=1
            if N.get(ref,ref)==N.get(ru.char,ru.char): v[1]+=1
            else:
                v[2]+=1
                if len(v[3])<6: v[3].append(f"{r['book'][:2]}{r['vol'][3:]}:{r['id']} {r['L'][-4:]}[{r['char']}]{r['R'][:4]} ref{ref} rule{ru.char}")
with open('rule_audit.tsv','w') as f:
    f.write('组\t规则\t命中\t与整理本同\t冲突\t冲突率\t样例\n')
    for k,v in sorted(st.items(),key=lambda x:(-x[1][2],x[0])):
        f.write(f"{k[0]}\t{k[1]}\t{v[0]}\t{v[1]}\t{v[2]}\t{v[2]/v[0]:.2f}\t{' | '.join(v[3])}\n")
tot=sum(v[0] for v in st.values()); bad=sum(v[2] for v in st.values()); print(tot,bad,len(st))
