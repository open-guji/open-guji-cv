"""日曰 字形宽高比分类器的离线评测（只用 ry 测试集）。
按册无监督估阈值（一维二成分 GMM，不看真值），带区弃权。强真值 A+B 上报：给字率/给字准确率/弃权率。
用法: python shape_eval.py <dataset>/char-groups [--band 0.03]"""
import json, sys, collections, numpy as np
from sklearn.mixture import GaussianMixture

def load(root):
    R = [json.loads(l) for l in open(root / 'ry/items.jsonl')]
    F = json.load(open(root / 'ry/features.json'))
    return [r for r in R if r['core'] and r['id'] in F], F

def book_threshold(ars):
    """无监督：两成分 GMM，阈值取两均值的加权中点；退化时回落到全局 0.80"""
    x = np.array(ars).reshape(-1, 1)
    if len(x) < 20: return 0.80, 0.0
    g = GaussianMixture(2, random_state=0, n_init=3).fit(x)
    mu = g.means_.ravel(); o = np.argsort(mu)
    sd = np.sqrt(g.covariances_.ravel())[o]
    lo, hi = mu[o]
    t = (lo * sd[1] + hi * sd[0]) / (sd[0] + sd[1])
    return float(t), float(hi - lo)

def classify(ar, t, band):
    d = ar - t
    if abs(d) < band: return None, abs(d)
    return ('曰' if d > 0 else '日'), abs(d)

def report(rows, name):
    n = len(rows); given = [r for r in rows if r[0] is not None]
    ok = sum(1 for p, g in given if p == g)
    err = [(p, g) for p, g in given if p != g]
    print(f'{name}: n={n} 给字率={len(given)/n:.1%} 准确率={ok}/{len(given)}={ok/max(1,len(given)):.1%} 弃权率={1-len(given)/n:.1%}'
          f' 日→曰错{sum(1 for p,g in err if g=="日")} 曰→日错{sum(1 for p,g in err if g=="曰")}')

if __name__ == '__main__':
    root = __import__('pathlib').Path(sys.argv[1]); band = 0.03
    if '--band' in sys.argv: band = float(sys.argv[sys.argv.index('--band') + 1])
    items, F = load(root)
    by = collections.defaultdict(list)
    for r in items: by[r['book']].append(r)
    for b, rs in sorted(by.items()):
        t, sep = book_threshold([F[r['id']]['ar'] for r in rs])
        strong = [(classify(F[r['id']]['ar'], t, band)[0], r['gold']) for r in rs
                  if r['gold_tier'] in ('A_human', 'B_vision') and r['gold'] in ('日', '曰')]
        weak = [(classify(F[r['id']]['ar'], t, band)[0], r['gold']) for r in rs
                if r['gold_tier'] == 'C_weak' and r['gold'] in ('日', '曰')]
        print(f'-- {b} t={t:.3f} 峰距={sep:.3f} band={band}')
        if strong: report(strong, '  强真值')
        if weak: report(weak, '  弱(循环参考)')
