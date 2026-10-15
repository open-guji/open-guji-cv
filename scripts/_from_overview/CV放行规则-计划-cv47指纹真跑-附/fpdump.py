import sys,json,os
wt=sys.argv[1]; out=sys.argv[2]
sys.path.insert(0,wt)
import open_guji_cv, open_guji_cv.steps  # noqa
assert open_guji_cv.__file__.startswith(wt),open_guji_cv.__file__
from open_guji_cv.core.book import load_book
from open_guji_cv.core.engine import Engine, code_hash, params_hash, book_dep_values, self_hash
from open_guji_cv.core.pipeline import load_pipeline
from open_guji_cv.core.step import STEPS
res={}
pl=load_pipeline("keben_body_v2")
for b in ("vol01","vol02","vol03","vol04","vol05","vol06","vol07"):
    book=load_book(b)
    eng=Engine(book,pl,log=lambda s:None)
    ids=list(pl.steps)
    # 挂在步骤出口的闸（不在 pipeline 列表里，但各有自己的指纹）
    gates=[]
    for sid in ids:
        g=STEPS[sid].spec.gate
        if g is not None: gates.append(g.id)
    enabled=set(eng._enabled(ids))
    d={}
    for sid in ids+gates:
        st=STEPS[sid]; sp=st.spec; p=eng.ctx.params_for(st)
        d[sid]={"kind":"gate" if sid in gates else "step","enabled":sid in enabled or sid in gates,
                "version":sp.version,"code":code_hash(st),"params":params_hash(p,sp.soft_params,sp.path_params),
                "self":self_hash(st,book,p),"book_deps":json.dumps(book_dep_values(st,book),sort_keys=True,ensure_ascii=False)}
    res[b]=d
res["_pipeline_steps"]=list(pl.steps)
json.dump(res,open(out,"w"),ensure_ascii=False,indent=1)
print(wt,"books",len(res)-1,"steps",len(res["vol04"]))
