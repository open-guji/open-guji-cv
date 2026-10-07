"""日曰 大模型文意判（偶试，并发≤3）。只给前后文，挖空目标位，不给字形/现字。结果缓存 ry/llm_cache.jsonl。
muse 本环境没有，改用环境里已接的 GLM（open.bigmodel.cn，代理注入凭证）。
用法: python llm.py <dataset>/char-groups <id列表文件|--strong dev|--strong val> [--model glm-5.2]"""
import json, sys, pathlib, concurrent.futures as cf, urllib.request, re
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import classify as C

def ctx_text(r, n=18):
    L = C.nbr(r, 'left')[:n][::-1]; R = C.nbr(r, 'right')[:n]
    return ''.join(c or '□' for c in L) + '【△】' + ''.join(c or '□' for c in R)

PROMPT = ('下面是清代《四庫全書總目》殿本的一句，【△】处是「日」或「曰」二字之一（刻本字形难分），□表示缺字，个别字可能有误。\n'
          '请只按文意判断【△】应为「日」（日期、白昼、太阳）还是「曰」（言，引语、称谓）。\n句子：{t}\n'
          '只输出JSON：{{"answer":"日"或"曰","confidence":0到1的数}}')

def ask(model, t):
    body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': PROMPT.format(t=t)}],
                       'temperature': 0, 'thinking': {'type': 'disabled'}}).encode()
    req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', body,
                                 {'Content-Type': 'application/json'})
    out = json.load(urllib.request.urlopen(req, timeout=90))['choices'][0]['message']['content']
    m = re.search(r'\{.*\}', out, re.S)
    j = json.loads(m.group(0)); return j['answer'], float(j['confidence'])

def run(root, rows, model='glm-5.2'):
    cache = root / 'ry/llm_cache.jsonl'
    have = {}
    if cache.exists():
        for l in open(cache):
            d = json.loads(l)
            if 'error' not in d: have[(d['id'], d['model'])] = d
    todo = [r for r in rows if (r['id'], model) not in have]
    def job(r):
        try: a, c = ask(model, ctx_text(r))
        except Exception as e: return dict(id=r['id'], model=model, error=str(e)[:200])
        return dict(id=r['id'], model=model, answer=a, conf=c, text=ctx_text(r))
    with cf.ThreadPoolExecutor(1) as ex, open(cache, 'a') as f:
        for d in ex.map(job, todo):
            if 'error' in d:
                print('ERR', d['id'], d['error']); 
                if '1113' in d['error'] or '429' in d['error']: break   # 没余额/限流：不连环撞
                continue
            f.write(json.dumps(d, ensure_ascii=False) + '\n'); f.flush(); have[(d['id'], model)] = d
    return {r['id']: have[(r['id'], model)] for r in rows if (r['id'], model) in have}

if __name__ == '__main__':
    root = pathlib.Path(sys.argv[1]); model = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else 'glm-5.2'
    R = [json.loads(l) for l in open(root / 'ry/items.jsonl')]
    F = json.load(open(root / 'ry/features.json'))
    R = [r for r in R if r['core'] and r['id'] in F and r['split'] != 'extra']
    which = sys.argv[sys.argv.index('--strong') + 1]
    rows = [r for r in R if r['gold_tier'] in ('A_human', 'B_vision') and r['gold'] in ('日', '曰')
            and (r['split'] == which)]
    res = run(root, rows, model)
    ok = n = 0; err = []
    for r in rows:
        if r['id'] not in res: continue
        d = res[r['id']]
        n += 1; ok += d['answer'] == r['gold']
        if d['answer'] != r['gold']: err.append((r['id'], r['gold'], d['answer'], d['conf']))
    print(f'{which} {model}: {ok}/{n}'); [print(e) for e in err]

def export(root, rows, out):
    """导出提示词给只能在自家客户端跑的模型（muse）：一行 {id, prompt}；跑完按 {id, answer, conf} 放进 ry/llm_cache.jsonl（model 填 muse）"""
    with open(out, 'w') as f:
        for r in rows: f.write(json.dumps(dict(id=r['id'], prompt=PROMPT.format(t=ctx_text(r))), ensure_ascii=False) + '\n')
