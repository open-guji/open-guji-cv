import json,csv,collections,os,re
S="/tmp/claude-0/sbx"
ROOT={"guji-workspace":[d for d in os.popen("ls -d /home/user/guji-workspace/96mid*").read().split()][0],
      "open-guji-dataset":"/home/user/open-guji/open-guji-dataset","open-guji-cv":"/home/user/open-guji-cv"}
rows=json.load(open(f"{S}/idrows.json"))
def writer(repo,rel,ln):
    p=os.path.join(ROOT[repo],rel); ext=os.path.splitext(rel)[1]
    if ext not in(".jsonl",): 
        if rel.endswith("rare_x_confirmed.json"): return "用户独立人裁（S-variant-pairs-1011）"
        return "脚本生成（可重建）" if repo=="guji-workspace" and rel.startswith("reports/") else "文件级（见分类）"
    try:
        line=open(p,encoding="utf-8").read().split("\n")[ln-1]; d=json.loads(line)
    except Exception: return "?"
    bits=[]
    for k in("actor","reviewer","label_origin"):
        v=d.get(k)
        if v: bits.append(f"{k}={v}")
    for src in (d.get("payload") or {}, d.get("expected") or {}):
        if src.get("judge"): bits.append(f"judge={src['judge']}")
    for k in ("batch",): 
        if d.get(k): bits.append(f"batch={d[k]}")
    return "; ".join(bits) or "（记录里无写入者字段）"
out=[]
for b,p,repo,rel,ln,old,new,st,note in rows:
    out.append([f"{b}",p,repo,rel,ln,old,new,st,note,writer(repo,rel,ln)])
out.sort(key=lambda r:(r[0],r[1],r[2],r[3],r[4]))
d="/home/user/overview/项目进展/CV字符切分/计划/"
with open(d+"p55与窄对合并-id映射.csv","w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f); w.writerow(["册","页","仓","文件","行","旧id","新id","状态","说明","谁写的"]); w.writerows(out)
# 汇总
agg=collections.defaultdict(lambda: collections.Counter())
uniq=collections.defaultdict(set)
for r in out:
    agg[(r[2],r[3])][(r[0],r[1])]+=1; uniq[(r[2],r[3])].add(r[5])
for k in sorted(agg): print(k, dict(agg[k]), "uniq",len(uniq[k]))
st=collections.Counter(r[8].split("；")[0] for r in out if r[7]=="ok"); print(st)
wr=collections.Counter(r[9] for r in out); print(wr.most_common(8))
