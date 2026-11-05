import json,glob,sys,collections
sys.path.insert(0,'/home/user/cvdev')
from open_guji_cv.utils.pua_lookup import PuaIndex, resolve_pua_code
files=sorted(glob.glob('/root/.guji-data/main/siku-zongmu/corpus/daizhige/[0-9]*.jsonl'))
idx=PuaIndex.from_source(files)
print('index codes',len(idx.codes),'distinct',len(set(idx.codes.values())))
pairs=collections.defaultdict(collections.Counter); tot=0; unres=0
seen=set()
for d in sorted(glob.glob('/home/user/a24r/out*')):
    for f in glob.glob(d+'/*.jsonl'):
        for l in open(f):
            x=json.loads(l)
            if 'err' in x or not x.get('src') or x['id'] in seen: continue
            o=ord(x['src'])
            if not (0xE000<=o<=0xF8FF or o>=0xF0000): continue
            seen.add(x['id']); tot+=1
            c=resolve_pua_code(idx,x['left'],x['right'])
            if c is None: unres+=1; continue
            pairs[f"{o:X}"][c]+=1
print('cells',tot,'unresolved',unres,'F codes',len(pairs))
one=sum(1 for v in pairs.values() if len(v)==1)
print('F->E unique',one,'of',len(pairs))
for k,v in pairs.items():
    if len(v)>1: print(k,dict(v))
json.dump({k:dict(v) for k,v in pairs.items()},open('/home/user/a24r/F2E.json','w'))
