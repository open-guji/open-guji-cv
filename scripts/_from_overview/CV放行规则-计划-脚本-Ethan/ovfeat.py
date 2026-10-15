import json
r=json.load(open('oversplit.json'))
TRUE={'vol01:196:1:10','vol04:14:9:13','vol04:20:9:2','vol04:23:7:20','vol04:196:2:20','vol04:199:5:2','vol05:45:5:17','vol05:46:8:20','vol05:84:3:2','vol05:96:1:2','vol05:108:7:1','vol06:57:7:3','vol06:66:7:4','vol07:129:7:2'}
FP={'vol05:123:9:9'}
SEAL={'vol03:3:5:-1','vol06:3:3:9','vol06:3:3:14','vol07:2:2:14'}
def lab(a): return 'T' if a in TRUE else 'F' if a in FP else 'S' if a in SEAL else 'O'
cache={}
def cell(i):
    v,pg,col,_=i.split(':')[0],i.split(':')[1],0,0
    k=(v,pg)
    if k not in cache:
        cache[k]={c['id']:c for co in json.load(open(f'prod/{v}/cell_shrink/p{int(pg):04d}.json'))['char_index']['columns'] for c in co['chars']}
    return cache[k][i]
rows=[]
for x in r:
    a,b=cell(x['a']),cell(x['b'])
    s=a if a['height']<=b['height'] else b
    t=b if s is a else a
    rows.append((lab(x['a']),x['a'],round(s['height']/x['mh'],2),round(s['width']/s['height'],2),s.get('ink_ratio'),s.get('flags'),round(t['height']/x['mh'],2),a.get('flags'),b.get('flags')))
for w in sorted(rows,key=lambda z:z[0]): print(*w)
print('---apply')
keep=[];ex=[]
for x in r:
    a,b=cell(x['a']),cell(x['b']); s=a if a['height']<=b['height'] else b
    seal=any('seal_region' in (c.get('flags') or []) for c in (a,b))
    bar=s['height']/x['mh']<=0.28 or (s.get('ink_ratio') or 1)<0.16
    (ex if seal or bar else keep).append((lab(x['a']),x['a'],'seal' if seal else 'bar'))
import collections
print('excluded',collections.Counter((l,w) for l,_,w in ex)); print('kept',collections.Counter(l for l,_,_ in keep))
