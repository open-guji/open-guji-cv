import json,os
def load_chars(ws,book,page,W):
    """读 cell_shrink 产物 → [(x0,y0,x1,y1) 左上原点, col, slot, sub, cell_type, flags]"""
    f=f'{ws}/products/{book}/cell_shrink/p{page:04d}.json'
    if not os.path.exists(f): return None
    d=json.load(open(f))['char_index']; out=[]
    for c in d.get('columns',[]):
        for ch in c.get('chars',[]):
            b=ch.get('bbox_page')
            if not b or ch.get('cell_type')=='empty': continue
            x0,y0,x1,y1=b
            out.append(dict(box=[W-1-x1,y0,W-1-x0,y1],col=c['col'],slot=ch.get('slot'),sub=ch.get('sub'),
                            kind=ch.get('cell_type'),k3=ch.get('step3_kind'),flags=ch.get('flags',[]),col_ok=c.get('ok')))
    return out
def gate_status(ws,book,page):
    r={}
    for st in ('border_detect_gate','column_gate','row_segment_gate'):
        f=f'{ws}/products/{book}/{st}/p{page:04d}.json'
        if os.path.exists(f): r[st]=json.load(open(f))
    return r
