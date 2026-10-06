"""muse 试点输入：本书「库首选 ≠ OCR 首选」格里的（库首选, OCR首选）无序字对 → pairs.jsonl。
任务书：overview 进度/Step6-上下文裁决/任务书-muse试点-异体关系初标.md
与任务书的出入：
  - 只有 bxgb（本容器里 vol02 没有产物快照）；
  - 上下文取**本书自动文本**（图像共识/库首选/OCR首选拼成，无真值无人裁）前后各 8 字，
    不取整理本——整理本没有逐格映射，且 Step6 实验已证它会把模型往它的写法上带。
读 step6_dict_ai/data/cells_fullbook.json（本容器重跑的全书候选快照），不碰正式 products/。"""
import json, os, sys, collections, unicodedata, importlib.util
H = os.path.dirname(os.path.abspath(__file__)); E = os.path.join(H, '..', 'step6_dict_ai')
sys.path.insert(0, E)
import dictlib
N = lambda x: unicodedata.normalize('NFC', x)
F = json.load(open(E + '/data/cells_fullbook.json')); TR = json.load(open(E + '/data/truth.json'))
def tops(c):
    lib = [x['c'] for x in c['cands'] if '库首选' in x['src']]; ocr = [x['c'] for x in c['cands'] if 'OCR第1' in x['src']]
    return (lib[0] if lib else None), (ocr[0] if ocr else None)
auto = []
for k in TR['keys']:
    c = F.get(k)
    if not c: auto.append('▢'); continue
    l, o = tops(c); auto.append(l if l and l == o else (l or o or '▢'))
pos = {k: i for i, k in enumerate(TR['keys'])}
cnt = collections.Counter(); ctx = collections.defaultdict(list)
for k, c in F.items():
    l, o = tops(c)
    if not l or not o or N(l) == N(o): continue
    a, b = sorted([N(l), N(o)]); cnt[(a, b)] += 1
    if len(ctx[(a, b)]) < 3:
        i = pos[k]; ctx[(a, b)].append(''.join(auto[max(0, i - 8):i]) + '【' + '?' + '】' + ''.join(auto[i + 1:i + 9]))
def tags(a, b):
    for x, t in dictlib.V.variants_of(a):
        if x == b: return sorted(t)
    return []
out = [{'a': a, 'b': b, 'cells': n, 'tags': tags(a, b), 'ctx': ctx[(a, b)]} for (a, b), n in cnt.most_common()]
with open(H + '/pairs.jsonl', 'w') as f:
    for r in out: f.write(json.dumps(r, ensure_ascii=False) + '\n')
tg = collections.Counter(t for r in out for t in r['tags'])
print('字对', len(out), '；涉及格', sum(cnt.values()), '；有来源标签的对', sum(1 for r in out if r['tags']), dict(tg.most_common(10)))
print('前 10', [(r['a'] + r['b'], r['cells'], r['tags'][:2]) for r in out[:10]])
print('自动真值池：通假', sum('hydzd-borrowed' in r['tags'] for r in out), '形近', sum('unihan:kSpoofingVariant' in r['tags'] for r in out), '简繁', sum('cjkvi-simplified' in r['tags'] for r in out))
