import json,collections,sys
rows=[json.loads(l) for l in open(sys.argv[1])]
G=set(sys.argv[2].split(',')) if len(sys.argv)>2 else {'ry','rm'}
def fin(r,which):
    d=r[which] or {}
    if not d: return ('later' if r.get('later') else None)
    if d['dec'] in ('review','demote'):
        return 'later' if r.get('later') else 'review'
    return 'admit'
c=collections.Counter(); chg=[]
for r in rows:
    g=((r['new'] or {}).get('gid') or (r['orig'] or {}).get('gid'))
    if g not in G: continue
    a,b=fin(r,'orig'),fin(r,'new')
    c[(g,a,b)]+=1
for k,v in sorted(c.items()): print(v,k)
