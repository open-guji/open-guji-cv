"""E0 数据准备：真值 / 按天切分 / 待判格候选 / 整理本逐天片段 → step6/data/*.json
真值 = 终稿 wiki（逐格）。候选 = shadow/signals_labeled.jsonl（1,135 个人裁格的真实多源候选）。
**不读人裁事件**，也不把 human_* 特征、label 给模型。"""
import json, re, sys, difflib, collections, os
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, H)
from parse_bxgb_wiki import parse_book, WS
W, KIND, _ = parse_book()
keys = list(W); txt = ''.join(W[k] for k in keys)
assert len(txt) == len(keys)
NUM = '[一二三四五六七八九十廿卅]'; GZ = '[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]'
DATE = re.compile(rf'(?:(?:乾道{NUM}年{GZ})?(?:{NUM}+|正|閏{NUM}*)月)?{NUM}{{1,3}}日{GZ}')
starts = [0] + [m.start() for m in DATE.finditer(txt) if m.start() > 0]
# 年号并入当天：往前回退到「乾道」
starts = sorted(set(txt.rfind('乾道', 0, s + 1) if txt[max(0, s-7):s].find('乾道') >= 0 else s for s in starts))
days = []
for i, s in enumerate(starts):
    e = starts[i + 1] if i + 1 < len(starts) else len(txt)
    days.append({'day': i, 'i0': s, 'i1': e, 'keys': keys[s:e], 'text': txt[s:e]})
# 整理本：全书字流对齐后按天取片段（保留标点原文）
raw = open(WS + '/corpus/beixingrilu_jiaoduiben.txt', encoding='utf-8').read()
lines = [l for l in raw.split('\n') if not re.fullmatch(r'\s*\d+\s*', l)]
ref = ''.join(lines)
PUNC = r'[，。、；：「」『』《》〈〉？！（）()\s·【】…—．,.:;!?“”‘’\[\]〔〕0-9①-⑳]'
idx = [j for j, ch in enumerate(ref) if not re.fullmatch(PUNC, ch)]
refc = ''.join(ref[j] for j in idx)
sm = difflib.SequenceMatcher(None, txt, refc, autojunk=False)
m = [None] * (len(txt) + 1)
for tag, i1, i2, j1, j2 in sm.get_opcodes():
    for k in range(i2 - i1):
        m[i1 + k] = j1 + min(k, max(j2 - j1 - 1, 0)) if j2 > j1 else j1
m[len(txt)] = len(refc)
def refspan(a, b):
    ja = m[a] if m[a] is not None else 0
    jb = m[b] if b < len(txt) and m[b] is not None else len(refc)
    ra = idx[ja] if ja < len(idx) else len(ref); rb = idx[jb] if jb < len(idx) else len(ref)
    return ref[ra:rb]
for d in days: d['ref'] = refspan(d['i0'], d['i1'])
# 候选（去掉 label / human_* 特征）
C = collections.defaultdict(list)
for line in open(WS + '/reports/bxgb/shadow/signals_labeled.jsonl', encoding='utf-8'):
    r = json.loads(line)
    src = []
    if r['lib_in']: src.append('库' + ('首选' if r['lib_top1'] else ''))
    if not r['ocr_missing'] and r['ocr_rank'] > 0 and r['ocr_rank'] <= 5: src.append(f"OCR第{r['ocr_rank']}")
    if r['rare_score'] > 0: src.append('生僻字模型')
    if r['ref_eq']: src.append('整理本')
    if any(x['c'] == r['cand'] for x in C[r['id']]):          # 同字多行（多源各一行）合并来源
        x = next(x for x in C[r['id']] if x['c'] == r['cand']); x['src'] = list(dict.fromkeys(x['src'] + src)); continue
    C[r['id']].append({'c': r['cand'], 'src': src, 'lib_cov': round(r['lib_cov'], 4), 'ocr_p': r['ocr_p'], 'rare': r['rare_score'], 'ref_eq': r['ref_eq'], 'ref_sem': r['ref_sem']})
cells = {}
kpos = {k: i for i, k in enumerate(keys)}
for k, cs in C.items():
    if k not in kpos: continue          # not_a_char / 夹注拆法不同的跳过
    cells[k] = {'key': k, 'truth': W[k], 'cands': cs, 'truth_in': any(c['c'] == W[k] for c in cs), 'pos': kpos[k]}
day_of = {}
for d in days:
    for k in d['keys']: day_of[k] = d['day']
for k in cells: cells[k]['day'] = day_of[k]
os.makedirs(H + '/data', exist_ok=True)
json.dump(days, open(H + '/data/days.json', 'w'), ensure_ascii=False)
json.dump(cells, open(H + '/data/cells_human1135.json', 'w'), ensure_ascii=False)
json.dump({'keys': keys, 'text': txt}, open(H + '/data/truth.json', 'w'), ensure_ascii=False)
# dev/test 按天交替切分：提示词只在 dev 上迭代，test 冻结到最后才跑
ds = sorted({c['day'] for c in cells.values()})
json.dump({'dev': [d for i, d in enumerate(ds) if i % 2 == 0], 'test': [d for i, d in enumerate(ds) if i % 2 == 1],
           'smoke': [2, 4, 8, 14, 23, 31, 62, 69, 79, 85, 123, 127, 144]}, open(H + '/data/splits.json', 'w'))
L = [len(d['text']) for d in days]
print('days', len(days), 'len min/med/max', min(L), sorted(L)[len(L)//2], max(L))
print('cells', len(cells), 'truth_in', sum(c['truth_in'] for c in cells.values()))
per = collections.Counter(c['day'] for c in cells.values())
print('pending/day med', sorted(per.values())[len(per)//2], 'max', max(per.values()))
print(days[5]['text'][:80]); print(days[5]['ref'][:100])
print(days[-1]['text'][-60:]); print(days[-1]['ref'][-80:])
