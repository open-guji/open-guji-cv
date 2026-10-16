"""自动真值校准集 calib.jsonl：本书字对里三类标签太少（通假 18、形近 4、简繁 19），从 variants.json 每类补到 40 对。
期望：hydzd-borrowed→通假、unihan:kSpoofingVariant→形近易混、cjkvi-simplified→简繁（任务书 §对照 3）。
只取两字都在 CJK 基本区、且该对只带这一类标签（避免一对同时是异体又是简繁之类的歧义）。固定种子。"""
import json, os, sys, random
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(H, '..', 'step6_dict_ai'))
import dictlib
V = json.load(open(os.path.join(H, '..', '..', '..', 'config', 'variants', 'variants.json')))
book = [json.loads(l) for l in open(H + '/pairs.jsonl')]
want = {'hydzd-borrowed': '通假', 'unihan:kSpoofingVariant': '形近易混', 'cjkvi-simplified': '简繁'}
basic = lambda c: '一' <= c <= '鿿'
random.seed(20260927); out = []
for tag, rel in want.items():
    have = [dict(r, expect=rel, calib_src='本书') for r in book if tag in r['tags']]
    pool = [(a, b) for a, d in V['pairs'].items() for b, t in d.items() if t == [tag] and basic(a) and basic(b)]
    random.shuffle(pool)
    seen = {(r['a'], r['b']) for r in have}
    for a, b in pool:
        if len(have) >= 40: break
        if (a, b) not in seen: have.append({'a': a, 'b': b, 'cells': 0, 'tags': [tag], 'ctx': [], 'expect': rel, 'calib_src': 'variants.json'})
    out += have[:40]
with open(H + '/calib.jsonl', 'w') as f:
    for r in out: f.write(json.dumps(r, ensure_ascii=False) + '\n')
import collections; print('校准集', len(out), collections.Counter(r['expect'] for r in out), collections.Counter(r['calib_src'] for r in out))
