"""Step6 新设计评测框架：按天批量问 → 结构化结论 → 与终稿真值打分。
用法: python3 harness.py --prompt v1 --model glm-5 --days 3,5,20 [--thinking] [--no-ref] [--tag x]"""
import json, os, sys, re, time, hashlib, argparse, urllib.request, concurrent.futures as cf
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H)
import dictlib, prompts
DAYS = json.load(open(H + '/data/days.json')); CELLS = json.load(open(H + '/data/cells_human1135.json'))
TR = json.load(open(H + '/data/truth.json')); KEYS, TXT = TR['keys'], TR['text']
MARK = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚'
CACHE = H + '/cache'; CV_ROOT = os.path.abspath(os.path.join(H, '../../..')); os.makedirs(CACHE, exist_ok=True)

# 美元/百万 token（输入, 输出）；只用于预算闸，账单以控制台为准
PRICE = {'claude-haiku-4-5': (1.0, 5.0), 'claude-sonnet-5': (2.0, 10.0), 'claude-opus-5': (5.0, 25.0)}
SPENT = {'usd': 0.0}

def call(model, messages, thinking=False, temperature=0.0, max_tokens=8000, seed_tag='', effort=None):
    if model.startswith('cc:'):
        return call_cc(model[3:], messages)
    if model.startswith('claude-'):
        return call_claude(model, messages, thinking, max_tokens, effort)
    if model.startswith('qwen'):
        return call_glm(model, messages, thinking, temperature, max_tokens, seed_tag,
                        url='https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', key=_key('DASHSCOPE_API_KEY'))
    return call_glm(model, messages, thinking, temperature, max_tokens, seed_tag)

def _key(name):
    """环境变量优先，其次 overview/.secret/api-keys.cfg（与 clustering/llm_context.py 同一查找顺序）"""
    if os.environ.get(name): return os.environ[name]
    p = os.environ.get('GUJI_API_KEYS_CFG') or os.path.join(CV_ROOT, '..', 'overview', '.secret', 'api-keys.cfg')
    for line in open(p, encoding='utf-8'):
        if line.strip().startswith(name + '='): return line.split('=', 1)[1].strip()
    sys.exit(f'找不到 {name}')

def call_cc(model, messages):
    """走本机 Claude Code CLI（订阅额度，不用 API key）：`claude -p`，换掉系统提示、关掉工具与设置。
    model = haiku / sonnet / opus。没有温度参数，思考用 CLI 默认。"""
    import subprocess
    sysmsg, user = messages[0]['content'], messages[1]['content']
    h = hashlib.sha256(json.dumps(['cc', model, sysmsg, user], ensure_ascii=False).encode()).hexdigest()[:24]
    fp = f'{CACHE}/{h}.json'
    if os.path.exists(fp): return json.load(open(fp)) | {'cached': True}
    t = time.time()
    for att in range(3):
        p = subprocess.run(['claude', '-p', '--model', model, '--system-prompt', sysmsg, '--tools', '',
                            '--setting-sources', '', '--output-format', 'json', '--no-session-persistence'],
                           input=user, capture_output=True, text=True, timeout=900, cwd='/tmp')
        try:
            d = json.loads(p.stdout)
            if d.get('is_error'): raise RuntimeError(d.get('result'))
            break
        except Exception as e:
            err = f'{e} {p.stderr[:200]}'
            open(H + '/errors.log', 'a').write(f'{time.strftime("%T")} cc:{model} {err}\n'); time.sleep(10 * 2 ** att)
    else:
        return {'text': '', 'error': err}
    u = d.get('usage', {})
    out = {'text': d.get('result', ''), 'usage': {'prompt_tokens': u.get('input_tokens', 0) + u.get('cache_read_input_tokens', 0) + u.get('cache_creation_input_tokens', 0),
           'completion_tokens': u.get('output_tokens', 0)}, 'usd_equiv': d.get('total_cost_usd'), 'models': list(d.get('modelUsage', {})),
           'latency': round(time.time() - t, 1), 'model': 'cc:' + model, 'ts': time.strftime('%FT%T')}
    json.dump(out, open(fp, 'w'), ensure_ascii=False); return out

def call_claude(model, messages, thinking, max_tokens, effort):
    import anthropic
    sysmsg = messages[0]['content']; user = messages[1]['content']
    kw = {'model': model, 'max_tokens': max_tokens,
          'system': [{'type': 'text', 'text': sysmsg, 'cache_control': {'type': 'ephemeral'}}],
          'messages': [{'role': 'user', 'content': user}]}
    if model.startswith('claude-haiku'):
        if thinking: kw['thinking'] = {'type': 'enabled', 'budget_tokens': 4000}; kw['max_tokens'] = max(max_tokens, 12000)
    else:
        kw['thinking'] = {'type': 'adaptive'} if thinking else {'type': 'disabled'}
        if effort: kw['output_config'] = {'effort': effort}
    h = hashlib.sha256(json.dumps(kw, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
    fp = f'{CACHE}/{h}.json'
    if os.path.exists(fp): return json.load(open(fp)) | {'cached': True}
    client = anthropic.Anthropic(max_retries=4)
    t = time.time()
    try:
        with client.messages.stream(**kw) as st:
            msg = st.get_final_message()
    except anthropic.APIStatusError as e:
        open(H + '/errors.log', 'a').write(f'{time.strftime("%T")} {model} {e.status_code} {str(e)[:200]}\n'); return {'text': '', 'error': str(e)}
    except anthropic.APIConnectionError as e:
        open(H + '/errors.log', 'a').write(f'{time.strftime("%T")} {model} conn {e}\n'); return {'text': '', 'error': str(e)}
    text = ''.join(b.text for b in msg.content if b.type == 'text')
    u = msg.usage
    usage = {'prompt_tokens': u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0),
             'completion_tokens': u.output_tokens, 'cache_read': u.cache_read_input_tokens or 0}
    pi, po = PRICE.get(model, (5.0, 25.0))
    usd = (u.input_tokens + 1.25 * (u.cache_creation_input_tokens or 0) + 0.1 * (u.cache_read_input_tokens or 0)) * pi / 1e6 + u.output_tokens * po / 1e6
    out = {'text': text, 'usage': usage, 'usd': round(usd, 5), 'stop': msg.stop_reason, 'latency': round(time.time() - t, 1), 'model': model, 'ts': time.strftime('%FT%T')}
    json.dump(out, open(fp, 'w'), ensure_ascii=False); return out

def call_glm(model, messages, thinking=False, temperature=0.0, max_tokens=8000, seed_tag='',
             url='https://open.bigmodel.cn/api/paas/v4/chat/completions', key=None):
    body = {'model': model, 'messages': messages, 'temperature': temperature, 'max_tokens': max_tokens}
    if model.startswith('glm'): body['thinking'] = {'type': 'enabled' if thinking else 'disabled'}
    elif thinking: body['enable_thinking'] = True
    h = hashlib.sha256((json.dumps(body, ensure_ascii=False, sort_keys=True) + seed_tag).encode()).hexdigest()[:24]
    fp = f'{CACHE}/{h}.json'
    if os.path.exists(fp): return json.load(open(fp)) | {'cached': True}
    for att in range(4):
        try:
            t = time.time()
            hd = {'Content-Type': 'application/json'} | ({'Authorization': 'Bearer ' + key} if key else {})
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=hd)
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
    if a.max_cells:
        kept, n = [], 0
        for j in jobs:
            if n >= a.max_cells: break
            kept.append(j); n += len(j[1])
        jobs = kept
    if a.export:   # 给只能在自家客户端跑的模型（如 muse）：导出提示词，跑完用 --answers 导回
        with open(a.export, 'w') as f:
            for d, ask, allpend in jobs:
                msgs, marks = P.build(DAYS, d, ask, allpend, KEYS, TXT, dictlib, MARK, with_ref=not a.no_ref)
                jid = f"{a.prompt}:{d}:{ask[0]['key']}"
                f.write(json.dumps({'job_id': jid, 'system': msgs[0]['content'], 'user': msgs[1]['content']}, ensure_ascii=False) + '\n')
        print('导出', len(jobs), '个提示词 →', a.export, '；回填格式：每行 {"job_id":..., "text": 模型原样输出}'); return
    if a.model.startswith('claude-') and not a.answers and not os.environ.get('ANTHROPIC_API_KEY'):
        sys.exit('没有 ANTHROPIC_API_KEY：在云端环境设置里加这个环境变量，新开会话生效')
    ANS = {}
    if a.answers:
        for line in open(a.answers): r = json.loads(line); ANS[r['job_id']] = r
    def one(job):
        d, ask, allpend = job
        msgs, marks = P.build(DAYS, d, ask, allpend, KEYS, TXT, dictlib, MARK, with_ref=not a.no_ref)
        if a.answers:
            out = ANS.get(f"{a.prompt}:{d}:{ask[0]['key']}", {'text': '', 'error': 'no answer'})
        elif SPENT['usd'] >= a.budget:
            out = {'text': '', 'error': 'budget'}
        else:
            out = call(a.model, msgs, thinking=a.thinking, temperature=a.temp, effort=a.effort)
            SPENT['usd'] += out.get('usd', 0) if not out.get('cached') else 0
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
    print(f'  本次新花费约 ${SPENT["usd"]:.3f}（预算 ${a.budget}）')
    tag = a.tag or f'{a.prompt}_{"answers" if a.answers else a.model}{"_" + a.effort if a.effort else ""}{"_think" if a.thinking else ""}{"_noref" if a.no_ref else ""}_b{a.batch}'
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
    ap.add_argument('--tag'); ap.add_argument('--effort')
    ap.add_argument('--budget', type=float, default=2.0, help='本次新调用美元上限，超了剩下的不再调用')
    ap.add_argument('--max-cells', type=int, default=0, help='最多问多少格（按批截断）')
    ap.add_argument('--export', help='只导出提示词 JSONL，不调用'); ap.add_argument('--answers', help='从 JSONL 导回答案打分')
    run(ap.parse_args())
