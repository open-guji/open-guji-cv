# -*- coding: utf-8 -*-
"""overview#427（C1）：拿 `seed_admit._garble_guard` 在快照产物上重放 context 放行格，量拦截/误拦。

用法：`python research/garble_guard/replay.py <快照>/products/vol04 garb [context_garble_cov=0.85 ...]`
（`garb` = 按 #427 列出的 12 列分「乱码列/其余」报；快照要带 seed_admit、glyph_match、align_ref）。"""
import json, os, sys, glob, collections
from types import SimpleNamespace as NS
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _garble_guard, _rare_run_ids
from open_guji_cv.clustering.variants import VariantMap
root = sys.argv[1]; garb_on = 'garb' in sys.argv[2:]
GARB = {(63,1),(80,5),(80,6),(217,2),(217,3),(127,4),(127,7),(220,3),(220,4),(220,5),(220,6),(220,7)}
p = SeedAdmitParams.model_construct(**{k: v.default for k, v in SeedAdmitParams.model_fields.items()})
for kv in sys.argv[2:]:
    if '=' in kv:
        k, v = kv.split('='); setattr(p, k, type(getattr(p, k))(v))
vmap = VariantMap.load(None)
def load(step, pg):
    f = os.path.join(root, step, f'p{pg:04d}.json')
    return next(iter(json.load(open(f)).values())) if os.path.exists(f) else None
res = collections.defaultdict(list)
for f in sorted(glob.glob(os.path.join(root, 'seed_admit', 'p*.json'))):
    pg = int(os.path.basename(f)[1:5])
    sa, gm, ar = load('seed_admit', pg), load('glyph_match', pg), load('align_ref', pg)
    if not gm: continue
    al = {c['id']: c['align_char'] for c in ar['chars']} if ar and ar.get('anchored') else {}
    co = {c['id']: c.get('ref_char') for c in (ar or {}).get('coord', [])}
    runs = {}
    for cc in gm['columns']:
        recs = [NS(id=r['id'], char=r['char'], candidates=r['candidates']) for r in cc['chars']]
        runs[cc['col']] = _rare_run_ids(recs, p.context_garble_run)
    for cc in sa['columns']:
        for a in cc['chars']:
            if not (a['admit'] and a['channel'] == 'context'): continue
            ev = a['evidence']; r = NS(id=a['id'], cov=ev['cov'])
            ocr = [o['char'] if isinstance(o, dict) else o[0] for o in (ev.get('ocr') or [])]
            hit = _garble_guard(p, r, a['char'], (al.get(a['id']), co.get(a['id']), *ocr), runs.get(cc['col'], frozenset()), vmap)
            g = 'garb' if garb_on and (pg, cc['col']) in GARB else 'other'
            res[(g, hit)].append(a['id'].split(':', 1)[1] + a['char'])
tot = collections.Counter(); 
for (g, h), v in res.items(): tot[g] += len(v)
for g in ('garb', 'other'):
    if not tot[g]: continue
    blk = sum(len(v) for (gg, h), v in res.items() if gg == g and h)
    print(f"[{g}] context 放行 {tot[g]}，拦 {blk}")
    for (gg, h), v in sorted(res.items(), key=lambda x: str(x[0])):
        if gg == g and h: print(f"   {h}: {len(v)}  {' '.join(v)}")
    if g == 'garb': print('   漏:', ' '.join(res[(g, None)]))
