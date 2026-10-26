"""象／𧰼 刻形判别评测（2026-10-26，A24 全册任务 08）：人裁表（--labels）格，按册留出，字形单判 vs 字形＋整理本一致才给。
用法：GUJI_WORKSPACE=<工作区> python eval_xz.py <原图根> <数据目录> <产物根> --labels=<人裁表>
字形单判过不了 0 错（人裁刻形本身差在一竖、二值图常糊），所以线上配 `lift_ref_agree`：字形与整理本同字才补放。"""
import dataclasses
import glob
import json
import pickle
import sys
from collections import Counter
from pathlib import Path

from build_shape_pair import PLAN, char_patch_fn, gather, labels_extra, loo
from open_guji_cv.groups import ids_online as O


def refs(prod: Path) -> dict:
    out = {}
    for f in glob.glob(str(prod / "vol*" / "align_ref" / "p*.json")):
        d = json.load(open(f, encoding="utf-8"))["align_ref"]
        coord = {c["id"]: c.get("ref_char") for c in d.get("coord") or ()}
        al = {c["id"]: c.get("align_char") for c in d["chars"]}   # 现役对位缺格时用坐标对位字（同线上 `lift_ref_agree`）
        for k in set(al) | set(coord):
            ch = al.get(k) or coord.get(k)
            if ch in ("象", "𧰼", "彖"):
                out[k] = ch
    return out


if __name__ == "__main__":
    imgs, data, prod = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    lab = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--labels="))
    cache = Path("/tmp/xz_cells.pkl")
    if cache.exists():
        cells = pickle.load(open(cache, "rb"))
    else:
        cells = gather([prod], imgs, data, "", labels_extra(Path(lab)), set(), "xz", char_patch_fn())
        pickle.dump(cells, open(cache, "wb"))
    ref = refs(prod)
    print("格", Counter(c[0] for c in cells), "有整理本", sum(c[3] in ref for c in cells))
    base = O.SPECS["xz"]
    for region in [(0.0, 0.5, 0.125, 0.625), (0.1, 0.6, 0.15, 0.55), (0.0, 0.6, 0.0, 0.7), (0.0, 1.0, 0.0, 1.0)]:
        for lam in (1.0, 3.0):
            sp = dataclasses.replace(base, region=region, lam=lam, min_class=20)
            res = loo(cells, sp)
            agree = [(f, ch, m, k) for f, ch, m, k in res if ch and ref.get(k) == ch]
            wrong = sorted(((m, f, ch, k) for f, ch, m, k in agree if ch != f), reverse=True)
            thr = round(wrong[0][0] * 1.1 + 0.005, 2) if wrong else 0.0
            give = [r for r in agree if r[2] >= thr]
            print(region, lam, f"一致 {len(agree)}，错 {len(wrong)}，门槛 {thr:.2f} 给 {dict(Counter(r[1] for r in give))}",
                  [(k, f, "→", ch, round(m, 2)) for m, f, ch, k in wrong[:4]])
