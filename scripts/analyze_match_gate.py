# -*- coding: utf-8 -*-
"""5a 置信闸离线分析（A23，2026-11-06）：在 `eval_match_bench.py --rows` 的逐查询结果上，
比较「生产 same 档」「全局闸（首位分 ≥ t 且与第二名分差 ≥ d）」「按形近表分类的两套闸」。

只读分析，不改生产。按页奇偶二折：一折拟合、另一折测试。精度按「答错＋novel 误放」合并算
（novel = 库里没有这个字，接受就是错）。形近类 = 首位字在 `confusable.partners()` 表里。

    python scripts/eval_match_bench.py --book <分片>:<db> --rows /tmp/rows ...
    python scripts/analyze_match_gate.py     # 读 /tmp/out/rows.<分片>.jsonl
"""
import sys,json,zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from eval_match_bench import fold_row
from open_guji_cv.clustering.confusable import partners
P=partners()
BK={'siku':'004-siku-v2-human','shiji':'005-shiji-human','qtw':'006-qtw-human'}
def load(b):
    rows=[json.loads(l) for l in open(f'/tmp/out/rows.{BK[b]}.jsonl')]
    out=[]
    for r in rows:
        if r['variant']!='orig' or r['sc_flag']: continue
        r=fold_row(r); c=r['cand']
        if c: c1,s1=c[0]; s2=c[1][1] if len(c)>1 else 0.0
        else: c1,s1,s2=None,0.0,0.0
        conf=bool(c1 and (c1 in P and (P[c1]&{x for x,_ in c} or True)))
        r.update(c1=c1,s1=s1,s2=s2,m=s1-s2,conf=conf,ok=(c1==r['gold']))
        out.append(r)
    return out

T=[.85,.90,.92,.94,.95,.96,.97,.98,.99,.996,1.01]
D=[0,.01,.02,.03,.04,.05,.07,.10]
def pg(r): return zlib.crc32(':'.join(r['id'].split(':')[1:3]).encode())%2
def ev(R,rule):
    A=[r for r in R if r['answerable']];N=[r for r in R if not r['answerable']]
    ac=[r for r in A if rule(r)];ok=sum(r['ok'] for r in ac);fa=sum(1 for r in N if rule(r))
    n=len(ac)+fa
    return dict(n=n,ok=ok,prec=ok/n if n else None,wrong=len(ac)-ok,fa=fa,nN=len(N),nA=len(A),recall=ok/len(A) if A else 0)
def fit(R,pmin):
    best=None
    for t in T:
        for d in D:
            e=ev(R,lambda r:r['s1']>=t and r['m']>=d)
            if e['n'] and e['prec']>=pmin and (best is None or e['ok']>best[0]): best=(e['ok'],t,d)
    return best
def mk(g): return (lambda r: g is not None and r['s1']>=g[1] and r['m']>=g[2])
def prod(r): return r['verdict']=='same'
def ms(e): return f"R={e['recall']:.3f} P={e['prec']:.4f}({e['wrong']}错+{e['fa']}误放)" if e['prec'] is not None else 'R=0'
for pmin in (.999,.995):
    print('#### 目标 combined precision >=',pmin,'（折：按页奇偶互相拟合/测试）')
    for b in BK:
        R=load(b);print('==',b)
        e=ev(R,prod);print('  生产 same        ',ms(e))
        tot={'glob':[0,0,0],'two':[0,0,0]}
        for k in (0,1):
            tr=[r for r in R if pg(r)!=k];te=[r for r in R if pg(r)==k]
            g=fit(tr,pmin);gc=fit([r for r in tr if r['conf']],pmin);go=fit([r for r in tr if not r['conf']],pmin)
            eg=ev(te,mk(g));et=ev(te,lambda r:(mk(gc) if r['conf'] else mk(go))(r))
            print(f'  折{k} 全局闸 {g and g[1:]} → 测试 {ms(eg)}   | 分类闸 形近{gc and gc[1:]} 其余{go and go[1:]} → {ms(et)}')
