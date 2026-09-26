"""全书评测集 data/cells_fullbook.json：与 cells_human1135.json 同格式（cands 带来源标签、truth、pos、day、human）。
候选：5a 库候选（首位=库首选）+ 5c OCR 前 5 + 5b 生僻字前 3 + 5d 整理本对齐字。真值=终稿。
human 标记该格是否在 1,135 人裁难例里（全书实验要分开报：人裁格是难例，其余是「管线当初有把握」的格）。"""
import json, gzip, os, unicodedata, collections
H = os.path.dirname(os.path.abspath(__file__))
N = lambda x: unicodedata.normalize('NFC', x)
TR = json.load(open(H + '/data/truth.json')); kpos = {k: i for i, k in enumerate(TR['keys'])}
W = dict(zip(TR['keys'], TR['text']))
DAYS = json.load(open(H + '/data/days.json')); day_of = {k: d['day'] for d in DAYS for k in d['keys']}
HUM = set(json.load(open(H + '/data/cells_human1135.json')))
out = {}
with gzip.open(H + '/data/cells_bxgb_fullbook.jsonl.gz', 'rt') as f:
    for line in f:
        r = json.loads(line); k = r['key']
        if k not in kpos or r.get('cell_type') != 'char': continue
        m = {}
        def add(ch, tag):
            if not isinstance(ch, str) or not ch: return
            ch = N(ch); m.setdefault(ch, []); tag not in m[ch] and m[ch].append(tag)
        a = r.get('s5a') or {}
        if a.get('verdict') == 'same' and a.get('char'): add(a['char'], '库首选')
        for i, (ch, _) in enumerate(a.get('candidates') or []): add(ch, '库首选' if i == 0 and a.get('verdict') != 'same' else '库')
        for i, (ch, _) in enumerate(((r.get('s5c_ocr') or {}).get('topk') or [])[:5]): add(ch, f'OCR第{i + 1}')
        for x in (r.get('s5b_rare') or [])[:3]: add(x.get('char'), '生僻字模型')
        add((r.get('s5d') or {}).get('align_char'), '整理本')
        cands = [{'c': ch, 'src': src, 'ref_eq': int('整理本' in src)} for ch, src in m.items()]
        out[k] = {'key': k, 'truth': W[k], 'cands': cands, 'truth_in': any(N(W[k]) == c['c'] for c in cands),
                  'pos': kpos[k], 'day': day_of.get(k), 'human': k in HUM, 'lib_verdict': a.get('verdict')}
json.dump(out, open(H + '/data/cells_fullbook.json', 'w'), ensure_ascii=False)
def img(c):
    lib = [x['c'] for x in c['cands'] if '库首选' in x['src']]; ocr = [x['c'] for x in c['cands'] if 'OCR第1' in x['src']]
    return lib[0] if lib and ocr and lib[0] == ocr[0] else None
for name, sel in [('全书', lambda c: True), ('非人裁', lambda c: not c['human']), ('人裁难例', lambda c: c['human'])]:
    S = [c for c in out.values() if sel(c)]
    I = [c for c in S if img(c)]; bad = [c for c in I if img(c) != N(c['truth'])]
    print(f"{name}: {len(S)} 格；真值在候选 {sum(c['truth_in'] for c in S)/len(S):.2%}；图像共识 {len(I)}（{len(I)/len(S):.0%}），其中错 {len(bad)}（{len(bad)/max(len(I),1):.3%}）")
S = [c for c in out.values() if not c['human'] and img(c) and img(c) != N(c['truth'])]
print('非人裁格里图像共识错的字对（共识/真值）', collections.Counter(f"{img(c)}/{c['truth']}" for c in S).most_common(25))
