"""两次回放逐格比：结论或放行字变了的格列出来（带窗口与新留痕），供逐格读。用法：python diff_replay.py 旧.jsonl 新.jsonl"""
import json,sys
def load(p):
    return {json.loads(l)['id']:json.loads(l) for l in open(p)}
A,B=load(sys.argv[1]),load(sys.argv[2])
def st(d):
    n=d.get('new') or {}
    if not n: return ('-',None,[])
    return (n['dec'],n['char'] if n.get('admit') else None,sorted(n.get('doubts') or []))
for k in sorted(set(A)|set(B)):
    a,b=A.get(k,{}),B.get(k,{})
    sa,sb=st(a),st(b)
    if sa[:2]!=sb[:2] or ('group_flow_ctx_contra' in sb[2] and (a or b).get('later')):
        d=b or a
        print(k,'|',sa,'->',sb,'| ref',d.get('ref'),'coord',d.get('coord'),'later',(d.get('later') or {}).get('char'),'orig',(d.get('orig') or {}).get('char'))
        print('    ',d['left'][-14:]+'【】'+d['right'][:12])
        for t in (b.get('new') or {}).get('trail',[]): print('      ',t.get('solver'),t.get('char'),t.get('why'),t.get('via',''),t.get('rules',''),'strong' if t.get('strong') else '')
