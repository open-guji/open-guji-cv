import sys, json
from pathlib import Path
repo, ws = sys.argv[1], sys.argv[2]; sys.path.insert(0, repo)
from open_guji_cv import steps as _r
from open_guji_cv.core.book import load_book
from open_guji_cv.core.engine import Engine, params_hash
from open_guji_cv.core.pipeline import load_pipeline
from open_guji_cv.core.step import STEPS
o={}
for i in range(1,11):
    b="vol%02d"%i; book=load_book(b,Path(ws)/"books"); eng=Engine(book,load_pipeline("keben_body_v2"))
    s=STEPS["seed_admit"]; o[b]=params_hash(eng.ctx.params_for(s), s.spec.soft_params, s.spec.path_params)[:12]
print(json.dumps(o))
