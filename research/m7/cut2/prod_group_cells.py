import json,glob,sys,collections
G=sys.argv[1]; M=set(sys.argv[2])
c=collections.Counter(); cells=[]
for f in sorted(glob.glob('/tmp/prod/vol*/seed_admit/p*.json')):
    v=f.split('/')[3]
    d=json.load(open(f))['seed_admit']
    for col in d['columns']:
        for ch in col['chars']:
            if ch.get('char') in M:
                c[(v,ch['char'],ch.get('provenance'))]+=1; cells.append((ch['id'],ch['char'],ch.get('provenance')))
for k,v in sorted(c.items()): print(k,v)
print(len(cells)); json.dump(cells,open(f'prod_{G}.json','w'),ensure_ascii=False)
