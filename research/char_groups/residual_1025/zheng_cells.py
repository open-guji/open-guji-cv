import json,glob,os
out=[]
for f in sorted(glob.glob('/home/user/prod/vol*/seed_admit/p*.json')):
    for col in json.load(open(f))['seed_admit']['columns']:
        for r in col['chars']:
            g=(r.get('evidence') or {}).get('group') or {}
            if g.get('id')=='zheng':
                ids=[t for t in g.get('solvers') or [] if t.get('solver')=='ids']
                out.append((r['id'],r['char'],r['admit'],g.get('decision'),g.get('why'),ids[0].get('char') if ids else None,round(ids[0].get('margin') or 0,2) if ids else None))
import collections
print(collections.Counter((o[3],o[4]) for o in out))
for o in out:
    if o[3]=='demote': print(*o)
