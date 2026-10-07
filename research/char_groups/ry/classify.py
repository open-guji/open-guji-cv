"""日曰 分类器离线实验（Step6 形态：组名、给的字、把握；拿不准弃权）。只读 ry 测试集，不碰管线。
三路证据：shape(宽高比按册归一) / ctx(外语料前后字搭配 NB) / par(排比：邻近 曰 的数量与距离)，逻辑回归合成。
训练只用 dev(vol02/03)+pool 的真值(含弱)，val=vol04 不参与训练与阈值选取；--val 才报 val。
用法: python classify.py <dataset>/char-groups [--val]"""
import json, sys, pathlib, collections, math
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

CV = pathlib.Path(__file__).resolve().parents[3]
PUNCT = set("，。、；：？！「」『』（）《》〈〉·　 \t<>|#@")

def corpus_counts():
    cnt = {k: collections.defaultdict(lambda: [0, 0]) for k in ('l1', 'r1', 'r2')}
    tot = [0, 0]
    for fn in ('daizhige_ru_yi.txt', 'daizhige_zhaoling.txt'):
        for line in open(CV / 'corpus/external' / fn, encoding='utf-8'):
            if line.startswith('#'): continue
            s = ''.join(c for c in line.strip() if c not in PUNCT)
            for i, c in enumerate(s):
                if c not in '日曰': continue
                j = c == '曰'; tot[j] += 1
                if i: cnt['l1'][s[i - 1]][j] += 1
                if i + 1 < len(s): cnt['r1'][s[i + 1]][j] += 1
                if i + 2 < len(s): cnt['r2'][s[i + 1:i + 3]][j] += 1
    return cnt, tot

def nb(cnt, tot, key, tok, k=1.0):
    a, b = cnt[key].get(tok, [0, 0])
    return math.log((b + k) / (tot[1] + k)) - math.log((a + k) / (tot[0] + k))

def nbr(r, side):
    """紧邻字：整理本优先（'·'为空），否则刻本读序字（'□'为空）"""
    ref, raw = r['ref_' + side], r[side]
    seq = lambda s: s[::-1] if side == 'left' else s
    out = []
    for a, b in zip(seq(ref), seq(raw)):
        out.append(a if a not in '·□' else (b if b != '□' else ''))
    return out  # 由近及远

def feats_row(r, F, med, cnt, tot):
    L, Rr = nbr(r, 'left'), nbr(r, 'right')
    l1 = L[0] if L else ''; r1 = Rr[0] if Rr else ''; r2 = ''.join(Rr[:2]) if len(Rr) >= 2 else ''
    c_l = nb(cnt, tot, 'l1', l1) if l1 else 0.0
    c_r = nb(cnt, tot, 'r1', r1) if r1 else 0.0
    c_r2 = nb(cnt, tot, 'r2', r2) if r2 else 0.0
    def near(seq, ch):
        for d, c in enumerate(seq[:12]):
            if c == ch: return d + 1
        return 99
    dy = min(near(L, '曰'), near(Rr, '曰')); dr = min(near(L, '日'), near(Rr, '日'))
    ny = sum(c == '曰' for c in L[:12] + Rr[:12]); nr = sum(c == '日' for c in L[:12] + Rr[:12])
    ar = F[r['id']]['ar'] - med[r['book']]
    return dict(shape=ar, ctx_l=c_l, ctx_r=c_r, ctx_r2=c_r2, ny=ny, nr=nr,
                par=1.0 if dy <= 12 else 0.0, pard=1.0 if dr <= 12 else 0.0)

SETS = {'shape': ['shape'], 'ctx': ['ctx_l', 'ctx_r', 'ctx_r2'], 'par': ['ny', 'nr', 'par', 'pard'],
        'shape+ctx': ['shape', 'ctx_l', 'ctx_r', 'ctx_r2'], 'all': ['shape', 'ctx_l', 'ctx_r', 'ctx_r2', 'ny', 'nr', 'par', 'pard']}

def main():
    root = pathlib.Path(sys.argv[1]); use_val = '--val' in sys.argv
    R = [json.loads(l) for l in open(root / 'ry/items.jsonl')]
    F = json.load(open(root / 'ry/features.json'))
    R = [r for r in R if r['core'] and r['id'] in F and r['split'] != 'extra']
    med = {b: float(np.median([F[r['id']]['ar'] for r in R if r['book'] == b])) for b in set(r['book'] for r in R)}
    cnt, tot = corpus_counts()
    for r in R: r['f'] = feats_row(r, F, med, cnt, tot)
    lab = [r for r in R if r['gold'] in ('日', '曰')]
    strong = lambda r: r['gold_tier'] in ('A_human', 'B_vision')
    train_books = sorted(set(r['book'] for r in lab) - {'vol04'})
    test_books = ['vol04'] if use_val else ['vol02', 'vol03']
    for name, keys in SETS.items():
        X = lambda rs: np.array([[r['f'][k] for k in keys] for r in rs])
        res = collections.defaultdict(list)
        for hb in test_books:
            tr = [r for r in lab if r['book'] in train_books and r['book'] != hb]
            m = LogisticRegression(C=1, class_weight='balanced', max_iter=2000).fit(X(tr), [r['gold'] == '曰' for r in tr])
            te = [r for r in lab if r['book'] == hb]
            p = m.predict_proba(X(te))[:, 1]
            for r, pp in zip(te, p): res[hb].append((r, pp))
        print(f'== {name}')
        for hb, v in res.items():
            for tier, f in (('强', strong), ('弱', lambda r: not strong(r))):
                s = [(r['gold'] == '曰', pp) for r, pp in v if f(r)]
                if len(set(y for y, _ in s)) == 2:
                    print(f'  {hb} {tier} n={len(s)} 日={sum(1 for y,_ in s if not y)} AUC={roc_auc_score([y for y,_ in s],[pp for _,pp in s]):.3f}')
if __name__ == '__main__': main()

def fit_all(R, F, keys=('shape', 'ctx_l', 'ctx_r', 'ctx_r2'), exclude=('vol04',)):
    lab = [r for r in R if r['gold'] in ('日', '曰') and r['book'] not in exclude]
    m = LogisticRegression(C=1, class_weight='balanced', max_iter=2000)
    m.fit([[r['f'][k] for k in keys] for r in lab], [r['gold'] == '曰' for r in lab])
    return m
