import random, sys, tempfile, json
sys.path.insert(0, "/home/user/open-guji-cv")
from fontTools.ttLib import TTFont
from open_guji_cv.clustering.font_candidates import _font_files
from open_guji_cv.clustering.synth import render_char

SEED = 20261013
N = 200
RANGES = [(0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x2A6DF)]
out_dir = tempfile.mkdtemp(prefix="a1a_render_")   # 临时目录，不留图
rows = []
for fp in _font_files():
    f = TTFont(fp, lazy=True, fontNumber=0)
    cmap = f.getBestCmap() or {}
    f.close()
    cjk_cov = {cp for cp in cmap if any(lo <= cp <= hi for lo, hi in RANGES)}
    pop = sorted(cjk_cov)
    rng = random.Random(SEED)
    pick = rng.sample(pop, min(N, len(pop)))
    ok = fail = exc = 0
    for cp in pick:
        ch = chr(cp)
        try:
            im = render_char(ch, fp, size=64)
            if im is not None and im.any():
                ok += 1
            else:
                fail += 1
        except Exception:
            exc += 1
    rows.append({"font": fp, "cmap_cjk_ext": len(cjk_cov), "sampled": len(pick),
                 "render_ok": ok, "render_empty": fail, "render_exc": exc})
    print(json.dumps(rows[-1], ensure_ascii=False))
print("tmp dir (not kept):", out_dir)
