import os,re,json,sys,collections
TARGETS={("vol05",55),("vol04",80),("vol04",217),("vol07",128),("vol07",130)}
ROOTS={"guji-workspace":sys.argv[1],"open-guji-dataset":sys.argv[2],"open-guji-cv":sys.argv[3]}
idre=re.compile(r"\b(vol0\d):(\d+):(\d+)(?::(\d+)([ab]?))?")
pathre=re.compile(r"(vol0\d)[/_\\-]+p?0*(\d+)[/_.\\-]")
hits=[]
def scan_line(root,rel,ln,line):
    out=[]
    for m in idre.finditer(line):
        b,p=m.group(1),int(m.group(2))
        if (b,p) in TARGETS: out.append(("id",m.group(0)))
    return out
skip_ext={".png",".jpg",".jpeg",".gz",".db",".npz",".pt",".zst",".tar",".pdf",".ttf",".otf",".woff",".woff2",".bin",".pyc",".npy",".safetensors",".webp"}
for name,root in ROOTS.items():
    for dp,dn,fn in os.walk(root):
        dn[:]=[d for d in dn if d not in(".git","node_modules",".venv","data_full","cache")]
        for f in fn:
            ext=os.path.splitext(f)[1].lower()
            if ext in skip_ext: continue
            p=os.path.join(dp,f)
            try:
                if os.path.getsize(p)>200_000_000: continue
                with open(p,encoding="utf-8",errors="ignore") as fh:
                    for i,line in enumerate(fh,1):
                        for kind,val in scan_line(root,p,i,line):
                            hits.append((name,os.path.relpath(p,root),i,kind,val))
                        # book/page 结构化（jsonl）
                        if ext in(".jsonl",".json") and '"page"' in line and '"book"' in line:
                            try: d=json.loads(line)
                            except Exception: continue
                            def chk(o):
                                if isinstance(o,dict):
                                    b=o.get("book"); pg=o.get("page")
                                    try: pg=int(pg)
                                    except Exception: pg=None
                                    if (b,pg) in TARGETS: hits.append((name,os.path.relpath(p,root),i,"struct",f"book={b} page={pg} col={o.get('col')} slot={o.get('slot',o.get('idx'))}"))
                                    for v in o.values(): chk(v)
                                elif isinstance(o,list):
                                    for v in o: chk(v)
                            chk(d)
            except Exception as e: pass
c=collections.Counter((h[0],h[1],h[3]) for h in hits)
for k,v in sorted(c.items()): print(v,k)
json.dump(hits,open("/tmp/claude-0/sbx/idhits.json","w"),ensure_ascii=False)
print("total",len(hits))
