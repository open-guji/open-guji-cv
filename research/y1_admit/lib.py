import json, glob, os, re, collections
WS = glob.glob('/home/user/guji-workspace/96mid*')[0]

def load_step(prod, book, step):
    out = {}
    for f in sorted(glob.glob(f'{prod}/{book}/{step}/p*.json')):
        d = json.load(open(f, encoding='utf-8'))
        d = next(iter(d.values()))
        if 'columns' in d:
            for c in d['columns']:
                for r in c.get('chars') or []:
                    out[r['id']] = r
        elif 'chars' in d:
            for r in d['chars']:
                out[r['id']] = r
    return out

def labels(book):
    L = {}
    for l in open(f'{WS}/reports/{book}/看图结论.jsonl', encoding='utf-8'):
        d = json.loads(l); L[d['cell']] = d
    return L

def merged(prod, book, src='<快照 products 根>'):
    """prod: 重放 seed_admit 产物根；上游步取快照"""
    sa = load_step(prod, book, 'seed_admit')
    gm = load_step(src, book, 'glyph_match')
    cd = load_step(src, book, 'context_decide')
    ci = load_step(src, book, 'cell_shrink')
    al = load_step(src, book, 'align_ref')
    return sa, gm, cd, ci, al
