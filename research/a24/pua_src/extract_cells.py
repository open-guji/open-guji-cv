import csv,json,gzip,difflib,os,sys,subprocess,shutil,collections,zipfile
sys.path.insert(0,'/home/user/open-guji-cv')
from open_guji_cv.utils.jiazhu_order import sort_by_reading
from types import SimpleNamespace as NS
WS='/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本'
GUJI='/home/user/open-guji/open-guji-cv/.venv/bin/guji'
env=dict(os.environ,GUJI_DATA_TOKEN=os.environ['GUJI_DATA_TOKEN_READ'],GUJI_CORPUS_DRIFT='warn')
pm=json.load(gzip.open('/home/user/ai-team/domain/CV/图源迁移/siku-qiefen-v2/results/pagemap_all.json.gz','rt'))
Z=zipfile.ZipFile('/home/user/qdl/q.zip')
OUTDIR=os.environ.get('OUTDIR','/home/user/a24r/out')
os.makedirs(OUTDIR,exist_ok=True)
if os.environ.get('CELLS'):   # 一列格号的 tsv（首行表头，首列格号）：只抽这些格
    ids=[l.split('\t')[0] for l in open(os.environ['CELLS'])][1:]
else:
    ids=[x['格号'] for x in csv.DictReader(open('/home/user/ai-team/domain/CV/质检/待审清单-2026-11-02-r2/分类v2-明细.tsv'),delimiter='\t') if x['子类'].startswith('整理本缺字')]
byvol=collections.defaultdict(list)
for i in ids: byvol[i.split(':')[0]].append(i)
def tdata(book):
    n=f'96mid1ogzk/{book}/text.jsonl.gz'
    import io
    return {json.loads(l)['p']:json.loads(l) for l in gzip.open(io.BytesIO(Z.read(n)),'rt')}
def run(v):
    out=f'{OUTDIR}/{v}.jsonl'
    if os.path.exists(out): return
    lab=subprocess.run([GUJI,'products','pack','list',v,'-w',WS],capture_output=True,text=True,env=env).stdout
    l=[x for x in lab.splitlines() if x.startswith('★')][0].split('\t')[0].split('/')[-1]
    tmp=f'/home/user/prod2/{v}.tmp'
    subprocess.run([GUJI,'products','pack','fetch',v,'-w',WS,'--label',l,'--to',tmp],capture_output=True,env=env)
    P=f'{tmp}/{v}'
    if not os.path.isdir(P): P=tmp
    L=lambda k,p: json.load(open(f'{P}/{k}/p{p:04d}.json'))
    T={}
    res=[]
    for cid in byvol[v]:
        p=int(cid.split(':')[1])
        try:
            sa=L('seed_admit',p)['seed_admit']
            cells=[c for col in sa['columns'] for c in col['chars']]
            ids=[c['id'] for c in cells]
            if cid not in ids: res.append(dict(id=cid,err='no_cell_in_main',label=l));continue
            gm={c['id']:c for col in L('glyph_match',p)['glyph_match']['columns'] for c in col['chars']}
            try: ar={c['id']:c['align_char'] for c in L('align_ref',p)['align_ref']['chars']}
            except Exception: ar={}
            g=[a for a in pm[v] if a['our']==p][0]['their']
            if g[0] not in T: T[g[0]]=tdata(g[0])
            ours=''.join((c.get('char') or '□') for c in cells)
            best=None
            for dp in range(-3,4):
                if g[1]+dp in T[g[0]]:
                    r=difflib.SequenceMatcher(None,ours,T[g[0]][g[1]+dp]['c'],autojunk=False).ratio()
                    if best is None or r>best[0]: best=(r,g[1]+dp)
            Tt=T[g[0]][best[1]]['c'];k=ids.index(cid)
            sm=difflib.SequenceMatcher(None,ours,Tt,autojunk=False)
            src=None;anch=0
            for tag,a0,a1,b0,b1 in sm.get_opcodes():
                if a0<=k<a1 and (tag=='equal' or (a1-a0)==(b1-b0)):
                    j=b0+k-a0;src=Tt[j]
                    anch=sum(1 for d in (-2,-1,1,2) if 0<=k+d<len(ours) and 0<=j+d<len(Tt) and ours[k+d]==Tt[j+d])
            # ctx windows like _clf_ctx
            recs=[NS(id=c['id'],col=int(c['id'].split(':')[2]) if c['id'].split(':')[2].isdigit() else 0,slot=c.get('slot'),sub=c.get('sub'),char=c.get('char'),admit=c.get('admit'),doubts=c.get('doubts'))
                  for c in cells]
            bycol=collections.defaultdict(list)
            for r_ in recs: bycol[r_.col].append(r_)
            seq=[r_ for col in sorted(bycol) for r_ in sort_by_reading(bycol[col]) if not (r_.doubts and 'excluded' in r_.doubts)]
            i=[q for q,r_ in enumerate(seq) if r_.id==cid][0]
            def ctx(step):
                o=[];j2=i+step
                while 0<=j2<len(seq) and len(o)<20:
                    o.append((seq[j2].char if seq[j2].admit else None) or ar.get(seq[j2].id) or '□');j2+=step
                return ''.join(reversed(o)) if step<0 else ''.join(o)
            cur=cells[k];gc=gm.get(cid,{})
            res.append(dict(id=cid,label=l,their=[g[0],best[1]],pagematch=round(best[0],3),src=src,anch=anch,
              cur=cur.get('char'),admit=cur.get('admit'),channel=cur.get('channel'),doubts=cur.get('doubts'),
              cands=[[a,b] for a,b in (gc.get('candidates') or [])[:5]],ref=ar.get(cid,''),left=ctx(-1),right=ctx(1),
              neigh=ours[max(0,k-3):k]+'|'+ours[k+1:k+4]))
        except Exception as e:
            res.append(dict(id=cid,err=repr(e)[:120],label=l))
    shutil.rmtree(tmp,ignore_errors=True)
    with open(out,'w') as f:
        for r in res: f.write(json.dumps(r,ensure_ascii=False)+'\n')
if __name__=='__main__':
    from concurrent.futures import ThreadPoolExecutor
    vs=sorted(byvol)
    with ThreadPoolExecutor(5) as ex: list(ex.map(run,vs))
    print('done')
