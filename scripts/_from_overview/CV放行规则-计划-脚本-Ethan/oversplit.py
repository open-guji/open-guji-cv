import json,glob,gzip,os,statistics as st,sys
SCR='/tmp/claude-0/-home-user/305d9756-1fb1-5e8c-9f22-55adc401d02a/scratchpad'
TB='/home/user/guji-workspace/exports/cell_table'
res=[]
for v in ['vol01','vol02','vol03','vol04','vol05','vol06','vol07']:
    adm={}
    for l in gzip.open(f'{TB}/{v}_base.jsonl.gz','rt'):
        r=json.loads(l)
        if not r.get('header'): adm[r['id']]=r
    for f in sorted(glob.glob(f'{SCR}/prod/{v}/cell_shrink/p*.json')):
        pg=int(os.path.basename(f)[1:5])
        ci=json.load(open(f))['char_index']
        allc=[c for col in ci['columns'] for c in col['chars']]
        body=[c for c in allc if c['cell_type']=='char' and c.get('step3_kind')=='char' and not c.get('sub')]
        if len(body)<20: continue
        mh=st.median(c['height'] for c in body); mw=st.median(c['width'] for c in body)
        for col in ci['columns']:
            cs=sorted(col['chars'],key=lambda c:c['idx'])
            for a,b in zip(cs,cs[1:]):
                if b['idx']!=a['idx']+1: continue
                if a.get('sub') or b.get('sub') or a.get('step3_kind')!='char' or b.get('step3_kind')!='char': continue
                ha,hb=a['height'],b['height']
                if not (0.8*mh<=ha+hb<=1.25*mh): continue
                if max(ha,hb)>0.75*mh: continue
                if min(a['width'],b['width'])<0.6*mw: continue
                if min(ha,hb)<0.15*mh: continue
                ra,rb=adm.get(a['id']),adm.get(b['id'])
                res.append(dict(v=v,a=a['id'],b=b['id'],ha=ha,hb=hb,mh=mh,
                    adm_a=ra and ra['admit'],ch_a=ra and ra['char'],chan_a=ra and ra['channel'],
                    adm_b=rb and rb['admit'],ch_b=rb and rb['char'],chan_b=rb and rb['channel']))
json.dump(res,open(f'{SCR}/oversplit.json','w'),ensure_ascii=False)
import collections
print(len(res),collections.Counter(r['v'] for r in res))
print('either admitted:',sum(1 for r in res if r['adm_a'] or r['adm_b']))
for r in res:
    if r['a']=='vol05:108:7:1': print(r)
