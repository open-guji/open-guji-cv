"""相左旗精度：并入用户 10-06 第 2 批 20 格人裁（review/ry_flag_verdicts.jsonl，A 档）后的重估。
机器放行格(channel≠human)上，|logit|≥τ 且与放行字相左 = 旗；强真值(A+B，含新增)上数 抓到的放行错 / 误拦。区间 Clopper-Pearson 95%。
pool 册在 τ=1 下的旗被这 20 格穷举了（候选就是 τ=1 的全部旗），所以 pool 的旗精度是全量不是抽样。"""
import json, sys, pathlib
from scipy.stats import beta
root = pathlib.Path(sys.argv[1])
def cp(k, n):
    if n == 0: return 0, 1
    return (0 if k == 0 else beta.ppf(.025, k, n - k + 1), 1 if k == n else beta.ppf(.975, k + 1, n - k))
f = lambda k, n: f'{k}/{n}={k/max(n,1):.0%} [{cp(k,n)[0]:.0%},{cp(k,n)[1]:.0%}]'
Z = json.load(open(root / 'ry/clf_scores.json'))
V = {json.loads(l)['id']: json.loads(l)['verdict'] for l in open(root / 'review/ry_flag_verdicts.jsonl')}
R = [json.loads(l) for l in open(root / 'ry/items.jsonl')]
R = [r for r in R if r['core'] and r['id'] in Z and r['split'] != 'extra']
for r in R:
    if r['id'] in V and V[r['id']] in ('日', '曰'): r['gold'], r['gold_tier'] = V[r['id']], 'A_human'
strong = lambda r: r['gold_tier'] in ('A_human', 'B_vision') and r['gold'] in ('日', '曰')
M = [r for r in R if r['admit'] and r['channel'] != 'human' and r['char'] in ('日', '曰')]
grp = {'dev(vol02/03)': ('vol02', 'vol03'), 'val(vol04)': ('vol04',), 'pool(vol05-10)': ('vol05', 'vol06', 'vol07', 'vol08', 'vol09', 'vol10')}
print('机器放行强真值上的放行错:', [(r['id'], r['char'], r['gold']) for r in M if strong(r) and r['gold'] != r['char']])
for tau in (1, 1.5, 2, 3):
    print(f'--- τ={tau}')
    tot = [0, 0, 0]
    for g, bs in grp.items():
        A = [r for r in M if r['book'] in bs]
        fl = [r for r in A if abs(Z[r['id']]['z']) >= tau and Z[r['id']]['pred'] != r['char']]
        st = [r for r in fl if strong(r)]; hit = sum(r['gold'] != r['char'] for r in st)
        print(f'  {g}: 机器放行{len(A)} 旗{len(fl)}({len(fl)/len(A):.1%}) 其中有强真值{len(st)} 真错{hit} 误拦{len(st)-hit}')
        tot[0] += len(st); tot[1] += hit
    print('  合计 旗精度(强真值上，pool 为全量)', f(tot[1], tot[0]))
nA = sum(1 for r in M if r['book'] in grp['pool(vol05-10)']); print('pool 机器放行', nA)
