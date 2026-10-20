import gzip, json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, '.'); sys.path.insert(0, 'research/pivot_family')
from pivot_family import load_items
from open_guji_cv.clustering.charset_spec import base_charset
from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates
from open_guji_cv.variants import NEVER_SOURCES, _graph
G = _graph()
rows = [json.loads(l) for l in gzip.open('research/pivot_family/rows.jsonl.gz', 'rt', encoding='utf-8')]
cnn = CnnCandidates(str(DEFAULT_CKPT)); cnn._ensure()
mat, names = cnn._emb_index(tuple(base_charset('unicode-cjk-ab')))
pos = {c: i for i, c in enumerate(names)}
items = load_items(2621); Q = cnn.embed([im for _, _, im in items])
def q8(x):
    s = np.abs(x).max(axis=1, keepdims=True) / 127.0
    return np.round(x / s).astype(np.int8)
M8 = q8(mat).astype(np.float32); Q8 = q8(Q).astype(np.float32)
M16 = mat.astype(np.float16).astype(np.float32)
def f1(c): return [v for v, t in G.variants_of(c) if set(t) - NEVER_SOURCES]
res = {}
for name, M, QQ in (('fp32', mat, Q), ('fp16', M16, Q), ('int8', M8, Q8)):
    t = [0, 0, 0]; same = 0; n = 0; glob10 = 0
    for i, r in enumerate(rows):
        if not r['pivot'] or r['pivot_is_g']:
            continue
        pool = [c for c in [r['pivot']] + f1(r['pivot']) if c in pos]
        s = M[[pos[c] for c in pool]] @ QQ[i]
        order = [pool[j] for j in np.argsort(-s)]
        k = order.index(r['g']) + 1
        n += 1; t[0] += k <= 1; t[1] += k <= 3; t[2] += k <= 5
        same += (k == r['f1_rank'])
    # 全表 top-10 与 fp32 一致率（抽 500 条）
    agree = 0
    for i in range(0, len(rows), max(1, len(rows) // 500)):
        a = set(np.argsort(-(mat @ Q[i]))[:10]); b = set(np.argsort(-(M @ QQ[i]))[:10])
        agree += len(a & b) / 10
    res[name] = dict(n=n, top1=t[0], top3=t[1], top5=t[2], same_rank_as_fp32=same, global_top10_overlap=round(agree / len(range(0, len(rows), max(1, len(rows) // 500))), 4))
print(json.dumps(res, ensure_ascii=False, indent=1))
