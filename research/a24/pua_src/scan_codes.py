import json,gzip,difflib,os,sys,subprocess,shutil,collections,zipfile,io,glob
WS='/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本'
GUJI='/home/user/open-guji/open-guji-cv/.venv/bin/guji'
env=dict(os.environ,GUJI_DATA_TOKEN=os.environ['GUJI_DATA_TOKEN_READ'],GUJI_CORPUS_DRIFT='warn')
pm=json.load(gzip.open('/home/user/ai-team/domain/CV/图源迁移/siku-qiefen-v2/results/pagemap_all.json.gz','rt'))
Z=zipfile.ZipFile('/home/user/qdl/q.zip')
def isp(s): o=ord(s); return 0xF0000<=o<=0xFFFFF or 0xE000<=o<=0xF8FF
def tdata(book):
    return {json.loads(l)['p']:json.loads(l) for l in gzip.open(io.BytesIO(Z.read(f'96mid1ogzk/{book}/text.jsonl.gz')),'rt')}
def run(v):
    out=f'/home/user/a24r/scan/{v}.jsonl'
    if os.path.exists(out): return
    lab=subprocess.run([GUJI,'products','pack','list',v,'-w',WS],capture_output=True,text=True,env=env).stdout
    ls=[x for x in lab.splitlines() if x.startswith('★')]
    if not ls: open(out,'w').close();return
    l=ls[0].split('\t')[0].split('/')[-1]
    tmp=f'/home/user/prod2/{v}.tmp'
    subprocess.run([GUJI,'products','pack','fetch',v,'-w',WS,'--label',l,'--to',tmp],capture_output=True,env=env)
    P=f'{tmp}/{v}'
    if not os.path.isdir(P): P=tmp
    T={};res=[]
    for f in sorted(glob.glob(f'{P}/seed_admit/p*.json')):
        p=int(os.path.basename(f)[1:5])
        try:
            sa=json.load(open(f))['seed_admit'];cells=[c for col in sa['columns'] for c in col['chars']]
            rec=[a for a in pm[v] if a['our']==p]
            if not rec: continue
            g=rec[0]['their']
            if g[0] not in T: T[g[0]]=tdata(g[0])
            ours=''.join((c.get('char') or '□') for c in cells)
            best=None
            for dp in range(-3,4):
                if g[1]+dp in T[g[0]]:
                    r=difflib.SequenceMatcher(None,ours,T[g[0]][g[1]+dp]['c'],autojunk=False).ratio()
                    if best is None or r>best[0]: best=(r,g[1]+dp)
            if best is None or best[0]<0.5: continue
            Tt=T[g[0]][best[1]]['c']
            if not any(isp(ch) for ch in Tt): continue
            sm=difflib.SequenceMatcher(None,ours,Tt,autojunk=False)
            gm=None
            for tag,a0,a1,b0,b1 in sm.get_opcodes():
                if tag!='equal' and (a1-a0)==(b1-b0):
                    for q in range(a1-a0):
                        ch=Tt[b0+q]
                        if isp(ch):
                            k=a0+q;c=cells[k]
                            if gm is None: gm={c2['id']:c2 for col in json.load(open(f'{P}/glyph_match/p{p:04d}.json'))['glyph_match']['columns'] for c2 in col['chars']}
                            ev=c.get('evidence') or {}
                            anch=sum(1 for d in (-2,-1,1,2) if 0<=k+d<len(ours) and 0<=b0+q+d<len(Tt) and ours[k+d]==Tt[b0+q+d])
                            res.append(dict(id=c['id'],code='%X'%ord(ch),cur=c.get('char'),admit=c.get('admit'),channel=c.get('channel'),prov=c.get('provenance'),
                                cov=ev.get('cov'),cands=[x for x in (gm.get(c['id'],{}).get('candidates') or [])[:3]],anch=anch,their=[g[0],best[1]]))
        except Exception as e: res.append(dict(err=repr(e)[:100],page=p))
    shutil.rmtree(tmp,ignore_errors=True)
    with open(out,'w') as fo:
        for r in res: fo.write(json.dumps(r,ensure_ascii=False)+'\n')
if __name__=='__main__':
    from concurrent.futures import ThreadPoolExecutor
    vs=[f'vol{n:02d}' for n in range(1,100)]
    with ThreadPoolExecutor(5) as ex: list(ex.map(run,vs))
    print('done')
