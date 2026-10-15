import json,re,csv,collections,os
S="/tmp/claude-0/sbx"
# (book,page) -> (新产物目录, 旧col→新col 规则)
CFG={("vol05",55):("ov",{"shift":+1,"retire":{9}}),
     ("vol04",217):("ov8",{"pair":(2,3)}),
     ("vol04",80):("ov8",{"pair":(5,6)}),
     ("vol07",128):("ov8",{"pair":(5,6)}),
     ("vol07",130):("ov8",{"pair":(2,3)})}
def load(root,b,p):
    d=json.load(open(f"{S}/{root}/{b}/cell_shrink/p{p:04d}.json"))["char_index"]
    out={}
    for col in d["columns"]:
        for c in col.get("chars",[]):
            bb=c["bbox_page"] or c["bbox_col"]
            out[(col["col"],c["slot"],c["sub"] or "")]=(c,bb)
    return out
def yov(a,b):
    lo=max(a[1],b[1]);hi=min(a[3],b[3]); h=min(a[3]-a[1],b[3]-b[1])
    return max(0,hi-lo)/h if h>0 else 0
maps={}
for (b,p),(root,rule) in CFG.items():
    old=load("products",b,p); new=load(root,b,p)
    m={}
    for (c,s,sub),(rec,bb) in old.items():
        if "retire" in rule and c in rule["retire"]:
            m[(c,s,sub)]=("retired","旧左缘窄条（被裁半列），新产物里没有这一列");continue
        if "shift" in rule: tc=c+rule["shift"]
        elif "pair" in rule:
            a,bq=rule["pair"]
            tc=c if c<a else (a if c in (a,bq) else c-1)
        # 候选：目标列同 slot；否则按 y 重叠最大
        cands=[(k,v) for k,v in new.items() if k[0]==tc and (k[2]==sub or not sub or True)]
        best=None;bo=0
        for k,(nrec,nbb) in cands:
            if k[2]!=sub and not (sub=="" or k[2]==""): continue
            o=yov(bb,nbb)
            if o>bo: bo,best=o,k
        if best and bo>=0.5:
            nid=f"{b}:{p}:{best[0]}:{best[1]}{best[2]}"
            note="同 slot" if best[1]==s else f"slot 变 {s}→{best[1]}"
            if "pair" in rule and c in rule["pair"]: note+="；半列碎片并入合并列"
            m[(c,s,sub)]=("ok",nid,note)
        else:
            m[(c,s,sub)]=("nomatch","新产物里按 y 位置找不到对应格（重切后该格消失或变形）")
    maps[(b,p)]=m
idre=re.compile(r"\b(vol0\d):(\d+):(\d+)(?::(\d+)([ab]?))?")
hits=json.load(open(f"{S}/idhits.json"))
rows=[]
for repo,rel,ln,kind,val in hits:
    if kind!="id": continue
    m=idre.fullmatch(val); b,p=m.group(1),int(m.group(2))
    if (b,p) not in CFG: continue
    col=int(m.group(3)); slot=m.group(4); sub=m.group(5) or ""
    if slot is None: old=val; new="（页/列级引用，无格号）"; st="n/a"; note=""
    else:
        r=maps[(b,p)].get((col,int(slot),sub))
        if r is None:
            r2=maps[(b,p)].get((col,int(slot),""))
            r=r2 if r2 else ("nomatch","旧产物里没有这一格（可能是空格/未出实例）")
        old=val
        if r[0]=="ok": new=r[1]; st="ok"; note=r[2]
        elif r[0]=="retired": new="（退役）"; st="retired"; note=r[1]
        else: new="（无对应）"; st="nomatch"; note=r[1]
    rows.append((b,p,repo,rel,ln,old,new,st,note))
json.dump({f"{b}:{p}":{f"{c}:{s}{sub}":v for (c,s,sub),v in m.items()} for (b,p),m in maps.items()},open(f"{S}/idmap.json","w"),ensure_ascii=False)
json.dump(rows,open(f"{S}/idrows.json","w"),ensure_ascii=False)
c=collections.Counter((r[0],r[1],r[7]) for r in rows)
for k,v in sorted(c.items()): print(k,v)
print("rows",len(rows),"unique old ids",len({r[5] for r in rows}))
for b,p in CFG: 
    m=maps[(b,p)]; st=collections.Counter(v[0] for v in m.values()); print(b,p,"全页旧格",len(m),dict(st))
