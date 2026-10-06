"""「N曰」排比/列举语境试验（overview#441）。
新特征（邻字取 classify.nbr：整理本优先，±30 字内再截窗）：
  dig    前一字是数字（一二…十百…）
  e_n    ±24 字内「数字+曰」模式出现次数（本格不计）——列举「一曰…二曰…」
  e_y    ±24 字内「曰」个数
  mo     左 8 字内「月」个数（日期语境）
  e_int  dig * log(1+e_n)   前字是数字且周围有列举 → 偏曰
开发集：dev(vol02/03) 强+弱真值 + 第 2 批 20 格 A 档人裁(pool)；训练不含 vol04。val 只在 --val 时跑一次。
20 格用 5 折留出（该折的格不进训练），dev 用留一册。
用法: python enum_exp.py <dataset>/char-groups [--val]"""
import json, sys, pathlib, math, random
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import eval_clf as E, classify as C

DIG = set('一二三四五六七八九十百千廿卅初幾')
def enum_feats(r):
    L, R = C.nbr(r, 'left')[:24][::-1], C.nbr(r, 'right')[:24]   # L 为读序（远→近），R 近→远
    seq = L + ['*'] + R; k = len(L)
    e_n = sum(1 for i, c in enumerate(seq) if c == '曰' and i != k and i > 0 and seq[i - 1] in DIG)
    e_y = sum(1 for c in seq if c == '曰')
    mo = sum(1 for c in L[-8:] if c == '月')
    l1 = L[-1] if L else ''
    dig = 1.0 if l1 in DIG else 0.0
    return dict(dig=dig, e_n=e_n, e_y=e_y, mo=mo, e_int=dig * math.log1p(e_n), e_ly=math.log1p(e_y))

BASE = ['shape', 'ctx_l', 'ctx_r', 'ctx_r2']
SETS = {'base': BASE, '+enum': BASE + ['e_int', 'e_ly', 'mo'], '+enum_full': BASE + ['dig', 'e_int', 'e_ly', 'mo']}

def fit(tr, keys):
    return LogisticRegression(C=1, class_weight='balanced', max_iter=3000).fit(
        [[r['f'][k] for k in keys] for r in tr], [r['gold'] == '曰' for r in tr])
def z(m, rs, keys): return m.decision_function([[r['f'][k] for k in keys] for r in rs])

if __name__ == '__main__':
    root = pathlib.Path(sys.argv[1]); use_val = '--val' in sys.argv
    R, F = E.prep(root)
    V = {json.loads(l)['id']: json.loads(l)['verdict'] for l in open(root / 'review/ry_flag_verdicts.jsonl')}
    for r in R:
        r['f'].update(enum_feats(r))
        if r['id'] in V and V[r['id']] in ('日', '曰'): r['gold'], r['gold_tier'] = V[r['id']], 'A_human'
    lab = [r for r in R if r['gold'] in ('日', '曰') and r['book'] != 'vol04']
    cards = [r for r in lab if r['id'] in V]
    strong = lambda r: r['gold_tier'] in ('A_human', 'B_vision')
    rng = random.Random(7); ids = [r['id'] for r in cards]; rng.shuffle(ids)
    fold = {i: n % 5 for n, i in enumerate(ids)}
    for name, keys in SETS.items():
        # 20 格：5 折
        zc = {}
        for f in range(5):
            te = [r for r in cards if fold[r['id']] == f]; tr = [r for r in lab if r['id'] not in {t['id'] for t in te}]
            for r, zz in zip(te, z(fit(tr, keys), te, keys)): zc[r['id']] = zz
        wrong_ri = [r['id'] for r in cards if r['gold'] == '曰' and zc[r['id']] < 0]          # 判日但真曰
        flags = [r for r in cards if abs(zc[r['id']]) >= 1 and (('曰' if zc[r['id']] > 0 else '日') != r['char'])]
        print(f'== {name}\n 20格(5折): 真曰判日 {len(wrong_ri)}/18；τ=1 旗 {len(flags)}，其中真错 {sum(r["gold"]!=r["char"] for r in flags)}；AUC={roc_auc_score([r["gold"]=="曰" for r in cards],[zc[r["id"]] for r in cards]):.3f}')
        # dev：留一册，评强/弱
        for hb in ('vol02', 'vol03'):
            tr = [r for r in lab if r['book'] != hb]; te = [r for r in lab if r['book'] == hb]
            zz = dict(zip([r['id'] for r in te], z(fit(tr, keys), te, keys)))
            for tier, f_ in (('强', strong), ('弱', lambda r: not strong(r))):
                s = [r for r in te if f_(r)]
                if len({r['gold'] for r in s}) == 2:
                    a = roc_auc_score([r['gold'] == '曰' for r in s], [zz[r['id']] for r in s])
                    row = f'  {hb}{tier} n={len(s)} AUC={a:.3f}'
                    for t in (0, 1, 2):
                        g = [r for r in s if abs(zz[r['id']]) >= t]; ok = sum((zz[r['id']] > 0) == (r['gold'] == '曰') for r in g)
                        row += f' | τ={t} 给{len(g)/len(s):.0%} 准{ok}/{len(g)}'
                    print(row)
        if use_val:
            m = fit(lab, keys); te = [r for r in R if r['book'] == 'vol04' and strong(r) and r['gold'] in ('日', '曰')]
            zz = z(m, te, keys); row = f' val(vol04强) n={len(te)}'
            for t in (0, 1, 2):
                g = [(r, q) for r, q in zip(te, zz) if abs(q) >= t]; ok = sum((q > 0) == (r['gold'] == '曰') for r, q in g)
                row += f' | τ={t} 给{len(g)}/{len(te)} 准{ok}/{len(g)}'
            print(row)
