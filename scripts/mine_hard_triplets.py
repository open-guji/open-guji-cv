# -*- coding: utf-8 -*-
"""从字形库挖新的匹配三元组（hard / nearmiss），直接补进 glyph-match/triplets。

    PYTHONPATH=. python scripts/mine_hard_triplets.py --db <glyph.db> [--apply]

## 为什么要扩这个集

`glyph_match_stack.md` 记「hard 38 条、1 条 = 2.6 个百分点」，已经卡住 5-a 调参。
实测 2026-09-17：集子后来扩到 hard 65 条（另有 control 53、nearmiss 57），
**hard rank_acc 只有 0.4923**——失败很分散（33 条错例里 12＋ 种字对：
已/巳 3、季/李 2、而/面 2、論/諭 2、妥/安 2…），不是某个字对的问题，
而是判据在「差一笔或一笔挪位」这类上普遍不行。所以要的是**更多同类样本**，
而不是更多同一个字对。

## 挖法：同字最像的 vs 形近异字最像的

对每个有 ≥2 刻例的字，取一个 anchor，再取：

- `same`：**同字、且不同页**的刻例里与 anchor 最像的那个
  （⚠️ 必须跨页——同页同刻工的两个字太像，判对了也说明不了问题）；
- `other`：**异字**刻例里与 anchor 最像的那个，且要过 `NEAR_GATE`
  （不够像的异字对谁都排得对，收进来是注水）。

按当前算法排序对不对分两档（与 `add_labelconf_triplets.py` 同一口径）：

- **`hard`**：现在就排反了（`f1(other) >= f1(same)`）——当下的失败，是靶子；
- **`nearmiss`**：排序对，但 `f1(other)` 仍在 `NEAR_GATE` 以上——闸开不下去
  就是被这些顶着。它们**不得回退**。

## 两条纪律

1. **标签来源只认真刻例**（`sources.kind='woodblock'`）。字体渲染模板不是刻例，
   拿它当 anchor 等于考模板自己。
2. **不收 `same`/`other` 同字的组**。三元组的性质是「同字比形近异字更匹配」，
   同字组永远判不对、白占失败名额——2026-09-17 在旧集里实测揪出 1 条
   （row00118「彖 vs 彖」，建集当天 `build_cov_other` 就已经更高），
   `eval_match_triplets.py` 现在也会把这类拦下来。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402

from open_guji_cv.clustering.exclusions import excluded_ids  # noqa: E402
from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.verify import verify_pair_elastic  # noqa: E402

#: `other` 至少要这么像才算「难」。低于它的异字对谁都排得对，收进来是注水。
#: 0.93 是照着旧集 hard 的分布取的（现有 65 条 hard 的 other f1 中位 ≈0.96，
#: 最低 0.933）。
NEAR_GATE = 0.93


def _load(db: Path) -> tuple[dict, dict]:
    """→ ({iid: (label, page)}, {iid: 归一化图})。只取真刻例。"""
    con = sqlite3.connect(str(db))
    cur = con.cursor()
    cur.execute("""select i.instance_id, i.label, i.page, i.patch_png
                   from instances i join sources s on i.source_id = s.source_id
                   where s.kind = 'woodblock'
                     and i.label is not null and i.label != ''
                     and i.patch_png is not null""")
    meta, imgs = {}, {}
    for iid, label, page, blob in cur.fetchall():
        img = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None or img.size == 0:
            continue
        meta[iid] = (label, str(page))
        imgs[iid] = normalize_patch(img)
    con.close()
    return meta, imgs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="字形库 glyph.db")
    ap.add_argument("--dataset", default="../open-guji-dataset/glyph-match/triplets")
    ap.add_argument("--max-anchors", type=int, default=400,
                    help="最多挖多少个 anchor（每个最多出一组）")
    ap.add_argument("--near-gate", type=float, default=NEAR_GATE)
    ap.add_argument("--no-variants", action="store_true",
                    help="不收 other 是 anchor 异体字的组。异体字在**字形层**是不同字形"
                         "（仓里纪律：绝不按语义表合并），所以默认收；但实测挖到的"
                         "隸/𨽾 f1 高达 0.9994，那更像是同一个字形被标了两种码位，"
                         "而不是「算法分不开」。要一份纯粹的形近异字集就开它")
    ap.add_argument("--hard-only", action="store_true",
                    help="只收 hard（排反的）。随机取 anchor 时 hard 只占约 1/6，"
                         "要补靶子就开它——扫完全部字种，只留排反的那些")
    ap.add_argument("--apply", action="store_true", help="写回数据集（默认只看）")
    a = ap.parse_args()

    meta, imgs = _load(Path(a.db))
    print(f"真刻例 {len(meta)} 个 / {len({m[0] for m in meta.values()})} 字种")

    by_char: dict[str, list[str]] = defaultdict(list)
    for iid, (label, _) in meta.items():
        by_char[label].append(iid)
    cand_chars = [c for c, v in by_char.items() if len(v) >= 2]
    print(f"≥2 刻例的字种 {len(cand_chars)}")

    ex = excluded_ids()
    ds = Path(a.dataset)
    tri = json.loads((ds / "expected.json").read_text(encoding="utf-8"))
    have = {(t["anchor"], t["same"], t["other"]) for t in tri}
    have_anchor = {t["anchor"] for t in tri}

    # 先把所有图堆成一个矩阵，用 HOG 粗排找「最像的异字」——逐对 elastic 太慢
    from open_guji_cv.clustering.features import get_feature
    feat = get_feature("hog")
    iids = [i for i in meta if i not in ex]
    M = feat.extract(np.stack([imgs[i] for i in iids]).astype(np.uint8))
    M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    pos = {iid: k for k, iid in enumerate(iids)}
    print(f"HOG 粗排索引 {M.shape}")

    add, skip = [], Counter()
    rng = np.random.default_rng(0)
    order = list(cand_chars)
    rng.shuffle(order)
    for ch in order:
        if len(add) >= a.max_anchors:
            break
        # --hard-only：多数字种会被「排序本来就对」筛掉，得多扫一些才凑得够
        pool = [i for i in by_char[ch] if i in pos]
        if len(pool) < 2:
            skip["同字刻例不足"] += 1
            continue
        anchor = pool[0]
        if anchor in have_anchor:
            skip["anchor 已在集内"] += 1
            continue

        # same：同字**不同页**里最像的
        ap_, apage = meta[anchor]
        same_pool = [i for i in pool[1:] if meta[i][1] != apage]
        if not same_pool:
            skip["同字都在同一页"] += 1
            continue
        q = M[pos[anchor]]
        s_sims = M[[pos[i] for i in same_pool]] @ q
        same = same_pool[int(np.argmax(s_sims))]

        # other：异字里最像的（HOG 粗排取 top 若干，再用 elastic 精验挑最高）
        sims = M @ q
        cand = np.argsort(-sims)[:60]
        others = [iids[k] for k in cand
                  if meta[iids[k]][0] != ch][:8]
        if not others:
            skip["找不到异字对手"] += 1
            continue
        best_o, best_f = "", -1.0
        for o in others:
            f = float(verify_pair_elastic(imgs[anchor], imgs[o]).f1)
            if f > best_f:
                best_o, best_f = o, f
        if best_f < a.near_gate:
            skip[f"对手不够像(<{a.near_gate})"] += 1
            continue

        f_same = float(verify_pair_elastic(imgs[anchor], imgs[same]).f1)
        key = (anchor, same, best_o)
        if key in have:
            skip["已在集内"] += 1
            continue
        if a.no_variants:
            from open_guji_cv.variants import are_variants
            if are_variants(ch, meta[best_o][0]):
                skip["对手是异体字（--no-variants）"] += 1
                continue
        subset = "hard" if best_f >= f_same else "nearmiss"
        if a.hard_only and subset != "hard":
            skip["排序本来就对（--hard-only）"] += 1
            continue
        add.append({
            "subset": subset, "anchor": anchor, "same": same, "other": best_o,
            "char": ch, "other_char": meta[best_o][0],
            "build_cov_same": round(f_same, 4), "build_cov_other": round(best_f, 4),
            "schema_version": 1, "label_origin": "mined",
            "seed": f"mine_hard_triplets_{date.today().isoformat()}",
        })

    n_hard = sum(1 for t in add if t["subset"] == "hard")
    print(f"\n挖到 {len(add)} 组：hard {n_hard} / nearmiss {len(add) - n_hard}")
    print("跳过原因:", skip.most_common())
    for t in add[:40]:
        print(f'  {t["subset"]:<9} {t["anchor"]:<16} 「{t["char"]}」{t["build_cov_same"]} '
              f'vs 「{t["other_char"]}」{t["build_cov_other"]}')

    if not a.apply:
        print("\n（未写回；加 --apply 才落盘）")
        return 0

    # 图块要一起落进 patches/，评测脚本按 iid 读那里
    pdir = ds / "patches"
    pdir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(a.db)
    cur = con.cursor()
    n_img = 0
    for t in add:
        for iid in (t["anchor"], t["same"], t["other"]):
            f = pdir / (iid.replace(":", "_") + ".png")
            if f.exists():
                continue
            cur.execute("select patch_png from instances where instance_id=?", (iid,))
            row = cur.fetchone()
            if row and row[0]:
                f.write_bytes(row[0])
                n_img += 1
    con.close()
    (ds / "expected.json").write_text(
        json.dumps(tri + add, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n写回 {len(add)} 组（{len(tri)} → {len(tri) + len(add)}），落图 {n_img} 张")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
