import json,collections,glob
from fontTools.ttLib import TTFont
R='research/y1_admit/'
V=json.load(open('config/variants/variants.json'))['pairs']
fonts={}
for p in ['fonts/jigmo/Jigmo.ttf','fonts/jigmo/Jigmo2.ttf','fonts/jigmo/Jigmo3.ttf','fonts/iming/I.Ming-8.10.ttf']:
    fonts[p.split('/')[1]+p[-6:-4]]=set(TTFont(p,lazy=True).getBestCmap())
def cov(c): return [k for k,s in fonts.items() if ord(c) in s]
def rel(a,b): return b in V.get(a,{}) or a in V.get(b,{})
rows=[]
for v in ('04','05'):
    P={}
    for l in open(R+f'pending_vol{v}.jsonl'):
        d=json.loads(l);P[d['id']]=d
    for l in open(R+f'gold_vol{v}.jsonl'):
        g=json.loads(l)
        if g['v']!='wrong' or not g.get('char'): continue
        p=P[g['cell']];cand=[c for c,_ in p['lib_top']]
        ch=g['char']
        if len(ch)!=1: continue
        inl=ch in cand
        rows.append(dict(vol=v,cell=g['cell'],shown=g['shown'],char=ch,src=g.get('src'),conf=g.get('conf'),inlib_top=inl,variant=rel(g['shown'],ch),font=cov(ch),cls=p['cls'],cov=p['cov']))
json.dump(rows,open('research/R_fill/miss_cells.json','w'),ensure_ascii=False)
for v in ('04','05'):
    r=[x for x in rows if x['vol']==v]
    out=[x for x in r if not x['inlib_top']]
    print(v,'wrong',len(r),'char不在库top4',len(out),'其中异体边',sum(x['variant'] for x in out),'字体可补',sum(bool(x['font']) for x in out),'无字体',[x['char'] for x in out if not x['font']])
    print(' conf',collections.Counter(x['conf'] or x['src'] for x in out))
    print(' 非异体:',[(x['shown'],x['char']) for x in out if not x['variant']][:30])
