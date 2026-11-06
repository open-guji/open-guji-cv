# 流式扫殆知阁全套：不落盘，只记各 PUA 码的用量（text 里的 PUA 码、pua_map 映射、glyphs 占位）
import json, sys, urllib.request, urllib.error, collections, os, time
from concurrent.futures import ThreadPoolExecutor
URL="https://sikuquanshu.daizhige.net/data/{:04d}.jsonl"
OUT="/home/user/work/scan"
def ispua(c):
    o=ord(c); return 0xE000<=o<=0xF8FF or 0xF0000<=o<=0x10FFFD
def norm(v):
    import ast
    if isinstance(v,str) and v[:1] in "[{":
        try: return ast.literal_eval(v)
        except Exception: return v
    return v
import subprocess
def _curl(url):
    p=subprocess.Popen(["curl","-sS","-f","-m","600",url],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    first=p.stdout.readline()
    if not first:
        err=p.stderr.read().decode()
        p.wait()
        if "404" in err: raise FileNotFoundError(url)
        raise RuntimeError(err)
    def gen():
        yield first
        for l in p.stdout: yield l
        if p.wait()!=0: raise RuntimeError("curl failed")
    return gen()
def scan(i):
    out=f"{OUT}/{i:04d}.json"
    if os.path.exists(out): return i,'cached'
    for attempt in range(5):
        try:
            resp=_curl(URL.format(i))
            break
        except FileNotFoundError:
            return i,'404'
        except RuntimeError:
            time.sleep(3*(attempt+1))
        except Exception:
            time.sleep(3*(attempt+1))
    else: return i,'fail'
    cnt=collections.Counter(); mapped=collections.defaultdict(collections.Counter); samp={}
    bookname=None; nrec=0; nbytes=0
    for line in resp:
        nbytes+=len(line)
        if not line.strip(): continue
        r=json.loads(line); nrec+=1
        if bookname is None: bookname=(norm(r.get('book')) or {}).get('name') if isinstance(norm(r.get('book')),dict) else None
        pm=norm(r.get('pua_map')) or {}
        gl=norm(r.get('glyphs')) or {}
        txt=r.get('text') or ''
        for cols in [norm(r.get('cols')) or []]:
            pass
        # 码位以 cols 中的字为准（text 也可）；这里用 text
        for ch in txt:
            if ispua(ch):
                k=f"U+{ord(ch):04X}"
                cnt[k]+=1
                if isinstance(pm,dict) and k in pm: mapped[k][pm[k]]+=1
                if k not in samp:
                    p=txt.index(ch); samp[k]=[r.get('id'),txt[max(0,p-10):p+11]]
        # 缅甸字母占位（U+1000–109F）
        for ch in txt:
            if 0x1000<=ord(ch)<=0x109F: cnt['MY']+=1
    json.dump(dict(file=f"{i:04d}",book=bookname,records=nrec,bytes=nbytes,cnt=cnt,mapped={k:dict(v) for k,v in mapped.items()},samp=samp),open(out,'w'),ensure_ascii=False)
    return i,'ok'
if __name__=='__main__':
    mx=int(sys.argv[1]) if len(sys.argv)>1 else 1600
    with ThreadPoolExecutor(4) as ex:
        for i,s in ex.map(scan,range(1,mx+1)):
            if s not in('ok','cached'): print(i,s,flush=True)
            elif s=='ok' and i%50==0: print('progress',i,flush=True)
    print('done',flush=True)
