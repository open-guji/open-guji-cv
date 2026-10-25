import json,sys,collections
G=set(sys.argv[2].split(',')) if len(sys.argv)>2 else {'sb','ly','dian','em','can','mb','wj','rr'}
c=collections.Counter(); ch=[]
for l in open(sys.argv[1]):
  r=json.loads(l); o=r['orig']; n=r['new']
  og=o and o['gid']; ng=n and n['gid']
  g=ng or og
  if g not in G: continue
  oa = o['admit'] if o else None
  na = n['admit'] if n else None
  c[(g,'orig_admit' if oa else ('orig_review' if o else 'orig_none'),'new_admit' if na else ('new_review' if n else 'new_none'))]+=1
  if o and n and (o['admit']!=n['admit'] or (o['admit'] and o['char']!=n['char'])):
    ch.append((g,r['id'],o['char'],o['admit'],o['dec'],'→',n['char'],n['admit'],n['dec'],n['why'],r['ref'],r['coord'],r['left'][-8:]+'【】'+r['right'][:8]))
for k,v in sorted(c.items()): print(k,v)
for x in ch: print(*x)
