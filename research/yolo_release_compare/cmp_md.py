import sys,os,difflib,collections,json
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from their import *; from ours_md import *
def their_cols(r):
    """their 页 → 列（阅读顺序），每列为字串（大+小），以 x 聚列（大字列宽 ~95，夹注两小行合并到同一大列）"""
    bs=boxes(r)
    cols=[]
    for b in bs:
        cx=(b['x0']+b['x1'])/2
        if cols and abs(cols[-1]['cx']-cx)<55: cols[-1]['b'].append(b)
        else: cols.append({'cx':cx,'b':[b]})
    # 同一物理列可能被夹注拆成多段（大→小→大），按 cx 合并相邻同列
    merged=[]
    for c in cols:
        if merged and abs(merged[-1]['cx']-c['cx'])<55: merged[-1]['b']+=c['b']
        else: merged.append(c)
    return [''.join(b['c'] for b in c['b']) for c in merged]
def run(md, chs, out):
    O=parse_md(md)
    T=[]
    for ch in chs:
        h,P=load_ch(ch)
        for p in sorted(P): T.append((ch,p,P[p]))
    ttext=[r['c'] for _,_,r in T]
    j=0; res=[]
    for k in sorted(O):
        cols=[norm_col(l) for l in O[k]]
        otext=''.join(''.join(c) for c,_ in cols).replace('□','')
        if len(otext)<5: continue
        best=None
        for jj in range(max(0,j-3),min(len(T),j+6)):
            sc=difflib.SequenceMatcher(None,otext,ttext[jj],autojunk=False).ratio()
            if best is None or sc>best[0]: best=(sc,jj)
        sc,jj=best; j=jj+1
        ch,p,r=T[jj]; tc=their_cols(r)
        res.append(dict(our=k,ch=ch,p=p,score=sc,ours=[''.join(c) for c,_ in cols],theirs=tc))
    json.dump(res,open(out,'w'),ensure_ascii=False)
    return res
if __name__=='__main__':
    md,chs,out=sys.argv[1],[int(x) for x in sys.argv[2].split(',')],sys.argv[3]
    res=run(md,chs,out)
    print('pages matched',len(res),'low score',[ (x['our'],round(x['score'],2)) for x in res if x['score']<0.8][:20])
