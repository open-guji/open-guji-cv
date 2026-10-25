import json,glob,sys,collections
from pathlib import Path
sys.path.insert(0,'/home/user/open-guji-cv')
from open_guji_cv.groups import registry as R
from open_guji_cv.groups.flow import FlowConfig, entry
from open_guji_cv.steps.seed_admit import _flow_groups
G=sys.argv[1].split(',')
vols=sys.argv[2].split(',')
of=collections.defaultdict(list)
for gid,g in R.FLOW_GROUPS.items():
    for ch in g.members: of[ch].append(gid)
cfg=FlowConfig(groups=tuple(_flow_groups()))
class Rec:
  def __init__(s,r): s.id=r['id'];s.char=r['char'];s.admit=r['admit'];s.channel=r.get('channel');s.provenance=r.get('provenance') or ''
out=[]
for v in vols:
  vd=Path('/home/user/prod')/v
  for f in sorted((vd/'seed_admit').glob('p*.json')):
    d=json.load(open(f))['seed_admit']
    gm=json.load(open(vd/'glyph_match'/f.name))['glyph_match']
    cand={c['id']:[tuple(x) for x in c.get('candidates') or []] for col in gm['columns'] for c in col['chars']}
    ar=vd/'align_ref'/f.name; amap={};coord={}
    if ar.exists():
      al=json.load(open(ar))['align_ref']
      amap={c['id']:c.get('align_char') for c in al.get('chars') or []}
      coord={c['id']:c.get('ref_char') for c in al.get('coord') or []}
    for col in d['columns']:
      chs=col['chars']
      for i,c in enumerate(chs):
        if c.get('admit'): continue
        ev=c.get('evidence') or {}
        gr=ev.get('group') or {}
        cs=cand.get(c['id'],[])
        ref=amap.get(c['id'])
        gids=set(of.get(c.get('char') or '',[]))|set(of.get(ref or '',[]))
        for x,cv in cs[:3]: gids|=set(of.get(x,[]))
        if gr.get('id'): gids.add(gr['id'])
        for gid in sorted(gids & set(G)):
          ctx=''.join((amap.get(x['id']) or x.get('char') or '〓') for x in chs[max(0,i-10):i])+'【'+(ref or '∅')+'】'+''.join((amap.get(x['id']) or x.get('char') or '〓') for x in chs[i+1:i+11])
          e=entry(Rec(c),cs,ref,cfg)
          out.append(dict(g=gid,id=c['id'],lib=c.get('char'),ref=ref,coord=coord.get(c['id']),cands=[(a,round(b,3)) for a,b in cs[:4]],entry=e,doubts=c.get('doubts'),group=gr,ctx=ctx))
json.dump(out,open(sys.argv[3],'w'),ensure_ascii=False,indent=0)
print(collections.Counter(o['g'] for o in out))
