import json,sys,collections
G={'sb','ly','dian','em','can','mb','wj','rr','zheng'}
def load(f):
    d={}
    for l in open(f):
        try: r=json.loads(l)
        except: continue
        n=r['new']; o=r['orig']
        g=(n and n['gid']) or (o and o['gid'])
        if g in G: d[r['id']]=r
    return d
A,B=load(sys.argv[1]),load(sys.argv[2])
vols=sorted({k.split(':')[0] for k in B})
st=lambda r:(r['new']['char'],r['new']['admit'],r['new']['dec']) if r['new'] else (None,None,None)
cnt=collections.Counter(); ch=[]
for k in sorted(set(A)|set(B)):
    if k.split(':')[0] not in vols: continue
    a,b=A.get(k),B.get(k)
    sa,sb=(st(a) if a else None),(st(b) if b else None)
    g=((b or a)['new'] or (b or a)['orig'])['gid']
    for s,t in ((sa,'A'),(sb,'B')):
        if s and s[1] is False: cnt[(g,t,'review')]+=1
    if sa!=sb:
        r=b or a
        ch.append((g,k,sa,'→',sb,'ref',r['ref'],r['coord'],r['left'][-8:]+'【】'+r['right'][:8], [ (t['solver'],t['char']) for t in (b['new']['trail'] if b and b['new'] else [])]))
print(vols)
for g in sorted(G): print(g, 'A送审',cnt[(g,'A','review')],'B送审',cnt[(g,'B','review')])
for x in ch: print(*x)
