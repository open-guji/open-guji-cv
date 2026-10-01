import sys, numpy as np, pickle, time
from open_guji_cv.clustering.glyph_db import GlyphDB
from open_guji_cv.clustering.seeding import load_matcher_from_db
t=time.time()
m,_=load_matcher_from_db(GlyphDB(sys.argv[1]),norm_stroke=int(sys.argv[3]) if len(sys.argv)>3 else None)
print(len(m), time.time()-t)
np.savez_compressed(sys.argv[2], ids=np.array(m._ids), chars=np.array(m._chars), P=np.stack(m._patches), F=np.stack(m._feats))
