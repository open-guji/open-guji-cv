"""Z02 全册扫描：每册 ★main 包里所有带 evidence.group 的格（不限待审），记组、模式、决定、放行字、整理本字、各解法给字；
另记 js/yr 等组的左右字。输出 $Z02_DIR/all/<book>-<vol>.jsonl（缺省 /home/user/z02）；工作区 /home/user/ws/{siku,sj,qtw}（workspace.yaml＋.central.json，GUJI_DATA_HOME/GUJI_DATA_TOKEN 已设）。"""
import json, os, subprocess, sys, shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, __import__('os').path.dirname(__file__))
from guji_manager.review.reasons import align_for_seed, _load_layer
from guji_manager._cv import connect
Z=Path(os.environ.get('Z02_DIR','/home/user/z02'))   # 工作目录：all/ 放结果，tmp2/ 放临时包
OUT=Z/'all'; TMP=Z/'tmp2'
WS={"siku":("siku-zongmu","/home/user/ws/siku"),"sj":("988g3f0wsu","/home/user/ws/sj"),"qtw":("995ejelvk0","/home/user/ws/qtw")}
G="/home/user/venv/bin/guji"
def run(*a): return subprocess.run(a,capture_output=True,text=True)
def one(job):
    k,v=job; ws,wsdir=WS[k]; res=OUT/f"{k}-{v}.jsonl"
    if res.exists(): return
    L=[l.split("\t") for l in run(G,"products","pack","list",v,"-w",wsdir).stdout.splitlines() if l.lstrip().startswith("★")]
    if not L: res.write_text(""); return
    lab=L[0][0].split("/")[-1].strip(); tmp=TMP/f"{k}-{v}"; shutil.rmtree(tmp,ignore_errors=True)
    run(G,"products","pack","fetch",v,"-w",wsdir,"--label",lab,"--to",str(tmp))
    root=tmp if (tmp/v/"seed_admit").is_dir() else tmp.parent
    if not (root/v/"seed_admit").is_dir(): res.write_text(""); return
    rows=[]
    for f in sorted((root/v/"seed_admit").glob("p*.json")):
        seed=_load_layer(f,"seed_admit") or {}
        align=align_for_seed(seed,_load_layer(root/v/"align_ref"/f.name,"align_ref")) or {}
        ref={c["id"]:c.get("align_char") for c in align.get("chars",[])}
        coord={c["id"]:c["ref_char"] for c in align.get("coord") or [] if c.get("ref_char")}
        seq=[ch for col in seed.get("columns",[]) for ch in col.get("chars",[]) if "excluded" not in (ch.get("doubts") or [])]
        txt=[(ch.get("char") if ch.get("admit") else None) or ref.get(ch["id"]) or coord.get(ch["id"]) or "□" for ch in seq]
        for i,ch in enumerate(seq):
            g=(ch.get("evidence") or {}).get("group")
            if not g: continue
            rows.append(dict(vol=v,id=ch["id"].split(":",1)[1],g=g.get("id"),mode=g.get("mode"),dec=g.get("decision"),why=g.get("why"),
                admit=bool(ch.get("admit")),char=ch.get("char"),ref=ref.get(ch["id"]),coord=coord.get(ch["id"]),
                sol=[(s["solver"],s.get("char"),s.get("margin")) for s in g.get("solvers",[])],
                L="".join(txt[max(0,i-20):i]),R="".join(txt[i+1:i+21])))
    res.write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in rows))
    shutil.rmtree(tmp,ignore_errors=True)
if __name__=="__main__":
    OUT.mkdir(exist_ok=True); TMP.mkdir(exist_ok=True)
    jobs=[]
    with connect() as con:
        cur=con.cursor()
        for k,(ws,_) in WS.items():
            cur.execute("select book from books where ws=%s order by book",(ws,)); jobs+=[(k,b) for (b,) in cur.fetchall()]
    def go(j):
        try: one(j)
        except Exception as e: print("ERR",j,repr(e),flush=True)
        print(j,flush=True)
    with ThreadPoolExecutor(5) as ex: list(ex.map(go,jobs))
