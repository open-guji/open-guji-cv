"""相左旗口径：机器放行格(channel≠human)上，分类器 |logit|≥τ 且与放行字相左 → 旗。
τ 只在 dev(vol02/03，留一册打分)上定：取「仍能抓到 dev 全部强真值放行错」的最大 τ，向下取 0.5 的倍数。
val(vol04) 只在定好 τ 后报一次。区间一律 Clopper-Pearson 95%。
用法: python flag_eval.py <dataset>/char-groups   (读 ry/clf_scores.json，不重训)"""
import json, sys, pathlib
from scipy.stats import beta

def cp(k, n, a=0.05):
    if n == 0: return (0.0, 1.0)
    return (0.0 if k == 0 else beta.ppf(a / 2, k, n - k + 1), 1.0 if k == n else beta.ppf(1 - a / 2, k + 1, n - k))

def fmt(k, n):
    lo, hi = cp(k, n); return f'{k}/{n}={k/max(n,1):.0%} [{lo:.0%},{hi:.0%}]'

root = pathlib.Path(sys.argv[1]); Z = json.load(open(root / 'ry/clf_scores.json'))
R = [json.loads(l) for l in open(root / 'ry/items.jsonl')]
R = [r for r in R if r['core'] and r['id'] in Z and r['split'] != 'extra']
strong = lambda r: r['gold_tier'] in ('A_human', 'B_vision') and r['gold'] in ('日', '曰')
def machine(b): return [r for r in R if r['book'] in b and r['admit'] and r['channel'] != 'human' and r['char'] in ('日', '曰')]
pred = lambda r: Z[r['id']]['pred']
def flags(rs, tau): return [r for r in rs if abs(Z[r['id']]['z']) >= tau and pred(r) != r['char']]

dev = machine(('vol02', 'vol03'))
errs = [r for r in dev if strong(r) and r['gold'] != r['char']]
print('dev 强真值放行错:', [(r['id'], round(abs(Z[r['id']]['z']), 2)) for r in errs])
tau = int(min(abs(Z[r['id']]['z']) for r in errs) * 2) / 2
print('τ_flag =', tau)
for t in (0.5, 1, 1.5, 2):
    f = flags(dev, t); st = [r for r in f if strong(r)]
    print(f'dev τ={t}: 机器放行{len(dev)} 旗{len(f)}({len(f)/len(dev):.1%}) 其中强真值 抓错{sum(r["gold"]!=r["char"] for r in st)} 误拦{sum(r["gold"]==r["char"] for r in st)}')
# 分类器给字准确率区间（强真值，dev，τ_cls）
for t in (1, 2):
    g = [r for r in R if r['book'] in ('vol02', 'vol03') and strong(r) and abs(Z[r['id']]['z']) >= t]
    ok = sum(pred(r) == r['gold'] for r in g); n = sum(1 for r in R if r['book'] in ('vol02','vol03') and strong(r))
    print(f'dev 分类器 τ={t}: 给字率 {fmt(len(g), n)}  准确率 {fmt(ok, len(g))}')
    d = [r for r in g if r['gold'] == '日']; print(f'   日的召回(给字且判日) {fmt(sum(pred(r)=="日" for r in d), sum(1 for r in R if r["book"] in ("vol02","vol03") and strong(r) and r["gold"]=="日"))}')
val = machine(('vol04')) if False else machine(('vol04',))
f = flags(val, tau); st = [r for r in f if strong(r)]
print(f'val τ={tau}: 机器放行{len(val)} 旗{len(f)}({len(f)/len(val):.1%}) 强真值抓错{sum(r["gold"]!=r["char"] for r in st)}/{sum(1 for r in val if strong(r) and r["gold"]!=r["char"])} 误拦{sum(r["gold"]==r["char"] for r in st)}')
vs = [r for r in R if r['book'] == 'vol04' and strong(r)]
for t in (1, 2):
    g = [r for r in vs if abs(Z[r['id']]['z']) >= t]; ok = sum(pred(r) == r['gold'] for r in g)
    print(f'val 分类器 τ={t}: 给字率 {fmt(len(g), len(vs))}  准确率 {fmt(ok, len(g))}')
print('机器放行错率区间(强真值格上, 偏难例, 下界): dev', fmt(len(errs), sum(1 for r in dev if strong(r))), ' val', fmt(sum(1 for r in val if strong(r) and r['gold']!=r['char']), sum(1 for r in val if strong(r))))
