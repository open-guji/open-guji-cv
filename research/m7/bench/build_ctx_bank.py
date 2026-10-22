"""文意组字形第二路建库（M7，2026-10-22）：模板＝数据集人裁格＋vol04–10 已放行格（每册每字 ≤ PER 格，放行字当标签，固定种子），
字块都是线上同款 char_patch（`materialize_patches.py`），建库前先 `ids_whole.clean_patch` 去碎墨、宽高比不合的不收（与线上判法同一处理）。
门槛评测见 `ctx_glyph2.py`（按册留一：人裁 0 错，且已放行格异议 ≤0.2%；再取 ≥0.4 的地板、留一成余量）。

用法：python build_ctx_bank.py <dataset char-groups 根> <人裁字块目录> <released.json> <已放行字块目录> <组,…|all>
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from bench import load  # noqa: E402

from open_guji_cv.groups import ids_online as O, ids_whole  # noqa: E402
from open_guji_cv.groups.registry import FLOW_GROUPS  # noqa: E402

PER = 20
ROOT = Path(__file__).resolve().parents[3]
#: 组 → 只收哪些字的模板（缺省＝组员全部）。xz 只做 象／𧰼 族内形判。
ONLY = {"xz": "象𧰼"}
#: 组 → 每册每字收几格已放行格（缺省 PER）。xz 不收：已放行「象」里混着约 1.5% 的 𧰼，会把 𧰼 往象拉。
PER_G = {"xz": 0}


def cells_for(g, root, labcrops, rel, relcrops):
    sp = O.SPECS[g]
    mem = set(ONLY.get(g, "".join(FLOW_GROUPS[g].members)))
    out, seen = [], set()
    for f, gr, b, i in load(root, labcrops, mem, only=True):
        seen.add(i)
        if ids_whole.aspect_ok(gr, tuple(sp.aspect)):
            out.append((f, ids_whole.clean_patch(gr) if sp.clean else gr, b, i))
    rng = random.Random(1022)
    pool = defaultdict(list)
    for ch in sorted(mem):
        for c in rel.get(ch, []):
            p = relcrops / (c["id"].replace(":", "_") + ".png")
            if c["id"] not in seen and p.exists():
                pool[(c["id"].split(":")[0], ch)].append((c["id"], p))
    for (b, ch), xs in sorted(pool.items()):
        xs.sort()
        rng.shuffle(xs)
        for i, p in xs[:PER_G.get(g, PER)]:
            gr = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if gr is not None and ids_whole.aspect_ok(gr, tuple(sp.aspect)):
                out.append((ch, ids_whole.clean_patch(gr) if sp.clean else gr, b, i))
    return out


def main():
    root, labcrops, relp, relcrops, gs = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5]
    rel = json.loads(relp.read_text())
    gids = [g for g in O.SPECS if O.SPECS[g].clean] if gs == "all" else gs.split(",")
    for g in gids:
        sp = O.SPECS[g]
        cells = cells_for(g, root, labcrops, rel, relcrops)
        d = ids_whole.build(g, cells, sp.size, {"labels": "dataset char-groups labels/unified.jsonl 人裁（kind=shape）＋殿本 vol04–10 已放行格（放行字当标签，每册每字 ≤%d）；字块＝线上 char_patch，clean_patch 后" % PER})
        O.write_bank(d, ROOT / FLOW_GROUPS[g].config_dir / "ids_bank.json")
        print(g, {k: len(v) for k, v in d["templates"].items()})


if __name__ == "__main__":
    main()
