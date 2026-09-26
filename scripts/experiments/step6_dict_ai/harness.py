"""Step6 新设计评测框架：按天批量问 → 结构化结论 → 与终稿真值打分。
用法: python3 harness.py --prompt v1 --model glm-5 --days 3,5,20 [--thinking] [--no-ref] [--tag x]"""
import json, os, sys, re, time, hashlib, argparse, urllib.request, concurrent.futures as cf
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
import dictlib, prompts
DAYS = json.load(open(H + '/data/days.json')); CELLS = json.load(open(H + '/data/cells_human1135.json'))
TR = json.load(open(H + '/data/truth.json')); KEYS, TXT = TR['keys'], TR['text']
MARK = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚'
CACHE = H + '/cache'; os.makedirs(CACHE, exist_ok=True)

def call(model, messages, thinking=False, temperature=0.0, max_tokens=8000, seed_tag=''):
    body = {'model': model, 'messages': messages, 'temperature': temperature, 'max_tokens': max_tokens,
            'thinking': {'type': 'enabled' if thinking else 'disabled'}}
    h = hashlib.sha256((json.dumps(body, ensure_ascii=False, sort_keys=True) + seed_tag).encode()).hexdigest()[:24]
    fp = f'{CACHE}/{h}.json'
    if os.path.exists(fp): return json.load(open(fp)) | {'cached': True}
    for att in range(4):
        try:
            t = time.time()
            req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions',
                                         data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
            req.data = json.dumps(body | {'stream': True, 'stream_options': {'include_usage': True}}).encode()
            txt, usage = [], None
            with urllib.request.urlopen(req, timeout=900) as resp:
                for raw in resp:
                    line = raw.decode('utf-8', 'ignore').strip()
                    if not line.startswith('data:') or line.endswith('[DONE]'): continue
                    ch = json.loads(line[5:])
                    if ch.get('usage'): usage = ch['usage']
                    for c in ch.get('choices', []):
                        txt.append((c.get('delta') or {}).get('content') or '')
            d = {'choices': [{'message': {'content': ''.join(txt)}}], 'usage': usage}
            if not ''.join(txt): raise RuntimeError('empty stream')
            out = {'text': d['choices'][0]['message'].get('content', ''), 'usage': d.get('usage'), 'latency': round(time.time() - t, 1),
                   'model': model, 'ts': time.strftime('%FT%T')}
            json.dump(out, open(fp, 'w'), ensure_ascii=False); return out
        except Exception as e:
            err = str(e) + ' ' + (e.read().decode()[:200] if hasattr(e, 'read') else '')
            open(H + '/errors.log', 'a').write(f'{time.strftime("%T")} {model} {err}\n'); time.sleep(5 * 2 ** att)
    return {'text': '', 'error': err}

def parse(text):
    t = text.strip()
    m = re.search(r'```(?:json)?\s*(.*?)```', t, re.S)
    if m: t = m.group(1)
    i, j = t.find('{'), t.rfind('}')
    try: return json.loads(t[i:j + 1])
    except Exception: return None

def score(cell, ans):
    """ans: {'drop':[..],'groups':[{'members':[..],'p':x}],'confidence':..}"""
    cands = [c['c'] for c in cell['cands']]; tr = cell['truth']
    if not ans: return {'ok_parse': 0}
    drop = set(ans.get('drop', [])) & set(cands)
    groups = sorted(ans.get('groups', []), key=lambda g: -float(g.get('p', 0) or 0))
    kept = [m for g in groups for m in g.get('members', [])]
    top = groups[0] if groups else {'members': [], 'p': 0}
    r = {'ok_parse': 1, 'truth_in_cands': tr in cands, 'truth_dropped': tr in drop,
         'truth_kept': tr in kept, 'n_cands': len(cands), 'n_drop': len(drop), 'n_groups': len(groups),
         'top_has_truth': tr in top.get('members', []), 'top_p': float(top.get('p', 0) or 0),
         'top_single': len(top.get('members', [])) == 1, 'conf': ans.get('confidence'),
         'out_of_cands': [m for m in kept if m not in cands]}
    return r

def run(a):
    days = [int(x) for x in a.days.split(',')] if a.days != 'all' else sorted({c['day'] for c in CELLS.values()})
    P = getattr(prompts, a.prompt)
    jobs = []
    for d in days:
        pend = sorted([c for c in CELLS.values() if c['day'] == d], key=lambda c: c['pos'])
        for i in range(0, len(pend), a.batch):
            jobs.append((d, pend[i:i + a.batch], pend))
    def one(job):
        d, ask, allpend = job
        msgs, marks = P.build(DAYS, d, ask, allpend, KEYS, TXT, dictlib, MARK, with_ref=not a.no_ref)
        out = call(a.model, msgs, thinking=a.thinking, temperature=a.temp)
        js = parse(out.get('text', ''))
        res = []
        for mk, cell in marks.items():
            ans = None
            if js:
                for it in js.get('items', []):
                    if str(it.get('pos')) == mk: ans = it
            res.append({'key': cell['key'], 'day': d, 'truth': cell['truth'], 'ans': ans, 's': score(cell, ans),
                        'cands': [c['c'] for c in cell['cands']]})
        return res, out.get('usage'), out.get('error')
    rows, usage, errs = [], [], []
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for res, u, e in ex.map(one, jobs):
            rows += res; usage.append(u); errs.append(e)
    tag = a.tag or f'{a.prompt}_{a.model}{"_think" if a.thinking else ""}{"_noref" if a.no_ref else ""}_b{a.batch}'
    os.makedirs(H + '/runs', exist_ok=True)
    json.dump({'args': vars(a), 'rows': rows}, open(f'{H}/runs/{tag}.json', 'w'), ensure_ascii=False)
    summarize(rows, usage, errs, tag)

def summarize(rows, usage, errs, tag):
    S = [r['s'] for r in rows]; n = len(S)
    ok = [s for s in S if s.get('ok_parse')]
    tin = [s for s in ok if s['truth_in_cands']]
    f = lambda k, L: sum(1 for s in L if s.get(k))
    print(f'== {tag}: {n} 格, 解析成功 {len(ok)}, 真值在候选 {len(tin)}')
    print(f'  真值被排除 {f("truth_dropped", tin)} ({f("truth_dropped", tin)/max(len(tin),1):.2%})；真值未被保留 {len(tin)-f("truth_kept", tin)}')
    print(f'  首组含真值 {f("top_has_truth", tin)} ({f("top_has_truth", tin)/max(len(tin),1):.2%})；首组单字且=真值 {sum(1 for s in tin if s["top_has_truth"] and s["top_single"])}')
    print(f'  平均候选 {sum(s["n_cands"] for s in ok)/max(len(ok),1):.1f}，平均排除 {sum(s["n_drop"] for s in ok)/max(len(ok),1):.1f}，候选外字 {sum(len(s["out_of_cands"]) for s in ok)}')
    for band in [(0.99, 1.01), (0.95, 0.99), (0.8, 0.95), (0, 0.8)]:
        B = [s for s in tin if band[0] <= s['top_p'] < band[1]]
        if B: print(f'  top_p∈[{band[0]},{band[1]}): {len(B)} 格, 首组含真值 {f("top_has_truth", B)/len(B):.1%}')
    tok = [u for u in usage if u]
    print(f'  tokens in {sum(u["prompt_tokens"] for u in tok)} out {sum(u["completion_tokens"] for u in tok)}；调用错误 {sum(1 for e in errs if e)}')

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--prompt', default='v1'); ap.add_argument('--model', default='glm-5')
    ap.add_argument('--days', default='all'); ap.add_argument('--batch', type=int, default=20)
    ap.add_argument('--thinking', action='store_true'); ap.add_argument('--no-ref', action='store_true')
    ap.add_argument('--temp', type=float, default=0.0); ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--tag')
    run(ap.parse_args())
