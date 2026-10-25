"""回放结果对细读真值（用法：python eval_truth.py 回放.jsonl labels.jsonl [x] [-v]）：每格最终状态与字。真值＝细读（verdicts）；没细读的放行格＝放行字（1888 格已逐格扫过）。"""
import json,sys,collections
rows=[json.loads(l) for l in open(sys.argv[1])]
V={}
for l in open(sys.argv[2]):
    v=json.loads(l); v.setdefault('char', v.get('form')); V[v['id']]=v
LANE_BLOCK=set(sys.argv[3].split(',')) if len(sys.argv)>3 and sys.argv[3]!='x' else {'group_flow_disagree','group_flow_conflict','group_flow_ref_dissent','group_flow_coord_dissent'}
c=collections.Counter(); errs=[]; rev=[]
for r in rows:
    g=((r['new'] or {}).get('gid') or (r['orig'] or {}).get('gid'))
    if g not in ('ry','rm'): continue
    for which in ('orig','new'):
        d=r[which] or {}
        if which=='orig':
            st='admit' if d.get('admit') else ('later' if r.get('later') else 'review')
            ch=d.get('char') if d.get('admit') else (r.get('later') or {}).get('char')
            if not d: st,ch=('later',r['later']['char']) if r.get('later') else ('none',None)
        else:
            if d.get('admit'): st,ch='admit',d['char']
            elif r.get('later') and not ({'group_flow_'+(d.get('why') or '')} | set(d.get('doubts') or [])) & (LANE_BLOCK|{'group_flow_ctx_contra'}) and d.get('dec')!='demote':
                st,ch='later',r['later']['char']
            else: st,ch='review',None
        v=V.get(r['id'])
        truth=v['char'] if v else ((r['orig'] or {}).get('char') if (r['orig'] or {}).get('admit') else (r.get('later') or {}).get('char'))
        if st in ('admit','later'):
            ok = truth is None or ch==truth or (truth=='其他' and ch not in '日曰目')
            c[(which,st,'ok' if ok else 'ERR')]+=1
            if not ok and which=='new': errs.append((r['id'],ch,truth,d.get('mode'),d.get('dec'),d.get('why'),r.get('ref'),r.get('coord')))
        else:
            c[(which,st)]+=1
            if which=='new': rev.append((r['id'],truth,d.get('mode'),d.get('why'),r.get('ref'),r.get('coord'),[ (t['solver'],t['char'],t['why'],t.get('strong')) for t in d.get('trail',[])]))
for k,v in sorted(c.items()): print(v,k)
print('--errors'); [print(e) for e in errs]
if '-v' in sys.argv[-1:]:
    print('--review'); [print(e) for e in rev]
