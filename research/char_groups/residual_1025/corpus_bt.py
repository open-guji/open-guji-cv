"""L1 规则对整部整理本（光盘版）回测：每个组员字出现处按前后 20 字跑规则，与整理本字比。"""
import sys,collections,json,re
sys.path.insert(0,'/home/user/open-guji-cv')
from open_guji_cv.groups.ctx_l1 import CtxL1Backend
from open_guji_cv.groups.registry import FLOW_GROUPS as GR
groups=sys.argv[1].split(','); rulesdir=sys.argv[2] if len(sys.argv)>2 else '/home/user/open-guji-cv/config/groups'
T=open('/root/.guji-data/main/siku-zongmu/corpus/zongmu_wenyuange_wikisource.txt',encoding='utf-8').read().replace('\n','')
for g in groups:
  B=CtxL1Backend(f'{rulesdir}/{g}/rules.yaml',GR[g].members); mem=GR[g].members
  c=collections.Counter(); rc=collections.Counter(); bad=[]
  for i,ch in enumerate(T):
    if ch not in mem: continue
    p,why,ids=B.decide(T[max(0,i-20):i],T[i+1:i+21])
    if p is None: c['abstain']+=1; continue
    ok=p==ch; c['ok' if ok else 'bad']+=1
    for r in ids: rc[(r,ok)]+=1
    if not ok: bad.append((ids,ch,'→',p,T[i-10:i]+'【'+ch+'】'+T[i+1:i+11]))
  print('==',g,dict(c))
  for (r,ok),n in sorted(rc.items()): 
    if not ok: print('  bad',r,n,'ok',rc[(r,True)])
  for b in bad: print('  ',*b)
