"""日曰 分类器评测：shape+ctx 逻辑回归，|logit|<τ 弃权。按册报强真值(A/B分开)的 给字率/给字准确率/弃权率，弱真值另列。
dev 册：留一册训练(其余 dev+pool，不含 val)；--val：训练用全部 dev+pool，只跑 vol04，τ 取 --tau（须先在 dev 定好）。
用法: python eval_clf.py <dataset>/char-groups [--val --tau 2.0] [--dump out.json]"""
import json, sys, pathlib, collections, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import classify as C
KEYS = ['shape', 'ctx_l', 'ctx_r', 'ctx_r2']

def prep(root):
    R = [json.loads(l) for l in open(root / 'ry/items.jsonl')]
    F = json.load(open(root / 'ry/features.json'))
    R = [r for r in R if r['core'] and r['id'] in F and r['split'] != 'extra']
    med = {b: float(np.median([F[r['id']]['ar'] for r in R if r['book'] == b])) for b in set(r['book'] for r in R)}
    cnt, tot = C.corpus_counts()
    for r in R: r['f'] = C.feats_row(r, F, med, cnt, tot)
    return R, F

def logits(R, test_books, exclude):
    out = {}
    for hb in test_books:
        m = C.fit_all(R, None, KEYS, exclude=set(exclude) | {hb})
        te = [r for r in R if r['book'] == hb]
        z = m.decision_function([[r['f'][k] for k in KEYS] for r in te])
        for r, zz in zip(te, z): out[r['id']] = float(zz)
    return out

def row(rs, Z, tau):
    n = len(rs); g = [(('曰' if Z[r['id']] > 0 else '日'), r['gold']) for r in rs if abs(Z[r['id']]) >= tau]
    ok = sum(p == t for p, t in g)
    return n, len(g), ok, sum(1 for p, t in g if p != t and t == '日'), sum(1 for p, t in g if p != t and t == '曰')

def table(R, Z, books, taus):
    for tau in taus:
        print(f'--- τ={tau}')
        for b in books:
            for name, f in (('A人裁', lambda r: r['gold_tier'] == 'A_human'), ('B看图', lambda r: r['gold_tier'] == 'B_vision'),
                            ('强A+B', lambda r: r['gold_tier'] in ('A_human', 'B_vision')), ('弱C', lambda r: r['gold_tier'] == 'C_weak')):
                rs = [r for r in R if r['book'] == b and f(r) and r['gold'] in ('日', '曰')]
                if not rs: continue
                n, g, ok, e1, e2 = row(rs, Z, tau)
                print(f'{b} {name:5} n={n:3d} 给字率={g/n:5.1%} 准确率={ok}/{g}={ok/max(g,1):5.1%} 弃权率={1-g/n:5.1%} 错:日→曰{e1} 曰→日{e2}')

if __name__ == '__main__':
    root = pathlib.Path(sys.argv[1]); R, F = prep(root)
    if '--val' in sys.argv:
        tau = float(sys.argv[sys.argv.index('--tau') + 1])
        Z = logits(R, ['vol04'], ['vol04']); table(R, Z, ['vol04'], [tau])
    else:
        Z = logits(R, ['vol02', 'vol03'], ['vol04']); table(R, Z, ['vol02', 'vol03'], [0, 1, 2, 3])
    if '--dump' in sys.argv: json.dump(Z, open(sys.argv[sys.argv.index('--dump') + 1], 'w'))
