import sys,os,re,json,collections
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from their import *
from rapidfuzz.distance import Levenshtein as L
from rapidfuzz import fuzz
W=os.environ.get("GUJI_WS96","../guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本")
def load_dzg():
    cols=[]
    for line in open(W+'/corpus/siku_daizhige.txt',encoding='utf-8'):
        line=line.rstrip('\n')
        if line.startswith('#'): continue
        s=line.lstrip('　')
        s=re.sub(r'<([^>|]*)\|?([^>]*)>',lambda m:m.group(1)+m.group(2),s)
        if s: cols.append(s)
    return cols
def stream(cols):
    """字流 + 每列结束位置集合"""
    s=[];ends=set();starts=set()
    for c in cols:
        starts.add(len(s)); s.extend(c); ends.add(len(s))
    return ''.join(s),starts,ends
def their_book_cols(ch):
    h,P=load_ch(ch); out=[]
    for p in sorted(P):
        for c in their_cols(P[p]): out.append((p,c))
    return out
def their_cols(r):
    bs=boxes(r); cols=[]
    for b in bs:
        cx=(b['x0']+b['x1'])/2
        if cols and abs(cols[-1]['cx']-cx)<55: cols[-1]['b'].append(b)
        else: cols.append({'cx':cx,'b':[b]})
    return [''.join(b['c'] for b in c['b']) for c in cols]
def eval_cols(cols, dz, dstarts, dends, lo, hi, wild='□'):
    """cols: 被评列字串表；在 dz[lo:hi] 上对齐，统计列边界与 dzg 列边界的吻合"""
    a=''.join(cols); b=dz[lo:hi]
    # 通配：把 □ 换成 b 中不出现的字，算替换
    ops=L.opcodes(a,b)
    amap=[None]*(len(a)+1)  # a 位置 -> b 位置
    for tag,i1,i2,j1,j2 in ops:
        if tag in('equal','replace') and i2-i1==j2-j1:
            for k in range(i2-i1): amap[i1+k]=j1+k
        elif tag=='replace':
            for k in range(i2-i1): amap[i1+k]=j1+min(k,j2-j1-1)
        elif tag=='delete':
            for k in range(i2-i1): amap[i1+k]=j1
    amap[len(a)]=len(b)
    ins=sum(j2-j1 for t,i1,i2,j1,j2 in ops if t=='insert')+sum(max(0,(j2-j1)-(i2-i1)) for t,i1,i2,j1,j2 in ops if t=='replace')
    dele=sum(i2-i1 for t,i1,i2,j1,j2 in ops if t=='delete')+sum(max(0,(i2-i1)-(j2-j1)) for t,i1,i2,j1,j2 in ops if t=='replace')
    sub=sum(min(i2-i1,j2-j1) for t,i1,i2,j1,j2 in ops if t=='replace')
    pos=0; ok=0; res=[]
    for c in cols:
        s,e=pos,pos+len(c); pos=e
        bs,be=amap[s],amap[e] if e<len(amap) else len(b)
        good=(bs is not None and be is not None and (bs+lo) in dstarts and (be+lo) in dends)
        ok+=good; res.append(good)
    return dict(n=len(cols),col_ok=ok,chars=len(a),ins=ins,dele=dele,sub=sub),res
def locate(text, dz, hint):
    """在 dz 中找 text 的开头和结尾（用前/后 120 字做 partial 对齐）"""
    w=min(len(text),120)
    s=fuzz.partial_ratio_alignment(text[:w], dz[hint:hint+len(text)+300000])
    st=hint+s.dest_start
    e=fuzz.partial_ratio_alignment(text[-w:], dz[st:st+int(len(text)*1.3)+5000])
    en=st+e.dest_end
    return st,en,s.score,e.score
