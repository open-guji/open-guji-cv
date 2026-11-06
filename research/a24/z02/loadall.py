import json,glob,os
def rows():
    for f in sorted(glob.glob(os.environ.get('Z02_DIR','/home/user/z02')+'/all/*.jsonl')):
        b=f.split('/')[-1].split('-')[0]
        for l in open(f,encoding='utf-8').read().splitlines():
            if l.strip():
                r=json.loads(l); r['book']=b; yield r
