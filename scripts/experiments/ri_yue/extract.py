"""日/曰 取样 + 量宽高比（R2，2026-10-02）。

只读快照产物（`GUJI_SNAP_ROOT/<vol>/products/<vol>/…`）与工作区原图，
输出 `samples.jsonl`（每个日/曰格一行）+ `crops/`（字块灰度小图，供目视）。

标签三档：
  human — seed_admit channel=="human"
  tri   — match_ref 且 整理本字(align_ref.ref_char)=库首位(glyph_match.candidates[0])
          =5-b 首位(rare_candidates.candidates[0]，缺则记 None) =放行字
  other — 其余放行格（含 context / match_* 等），只当参考
  unadmitted — 未放行但 seed_admit.char 有值（诊断用，不进评测）

量法：Otsu 二值 → 取与裁块边缘不相连的墨连通域并集的紧墨框 → w,h；
相对量 = w/period、h/period，再除以同列同类（正文/夹注）±3 格紧墨框的均值宽/高。
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import defaultdict

import cv2
import numpy as np

from open_guji_cv.core.anchor import crop_patch

SNAP = os.environ["GUJI_SNAP_ROOT"]
WS = glob.glob("/home/user/guji-workspace/96mid1ogzk-*")[0]
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
TARGET = {"日", "曰"}
VOLS = [f"vol{n:02d}" for n in range(2, 11)]


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def tight_box(patch):
    """返回 (w,h,ink_ratio,mid_hbar_touch_right,pad_top,pad_bot,mask_box) 或 None。

    patch：灰度裁块。墨=Otsu 暗部。丢弃贴着裁块四边且又细又长的连通域（界行/邻字残片）。
    """
    if patch is None or patch.size == 0:
        return None
    _, bw = cv2.threshold(patch, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    n, lab, st, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    H, W = bw.shape
    keep = np.zeros_like(bw)
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 6:
            continue
        touch = x <= 0 or y <= 0 or x + w >= W or y + h >= H
        thin_long = (w <= 6 and h >= 0.6 * H) or (h <= 6 and w >= 0.6 * W)
        if touch and thin_long:
            continue
        keep[lab == i] = 255
    ys, xs = np.where(keep > 0)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    return dict(w=int(x1 - x0), h=int(y1 - y0), ink=float((keep > 0).sum()),
                box=(int(x0), int(y0), int(x1), int(y1)), mask=keep[y0:y1, x0:x1])


def second_feats(m):
    """中横是否接到右竖（日/曰的核心差异：曰 中横两头都接竖，日 的中横同样…
    实际上两字都接；这里量 中横右端到右竖的缝：取中间 40%~60% 行带，
    看最右列墨是否连续）。另：上/下留白占比在调用处用 box 算。"""
    h, w = m.shape
    if h < 6 or w < 6:
        return dict(hbar_right=None, ink_density=None)
    band = m[int(h * 0.35):int(h * 0.65)]
    rows = band.sum(axis=1) / 255.0
    # 中横：带内墨最多的那一行；是否伸到最右 15% 区域
    r = int(np.argmax(rows))
    row = band[r] > 0
    right = row[int(w * 0.85):].any()
    left = row[: int(w * 0.15) + 1].any()
    return dict(hbar_right=bool(right), hbar_left=bool(left),
                ink_density=float((m > 0).mean()))


def main():
    os.makedirs(os.path.join(OUT, "crops"), exist_ok=True)
    rows = []
    for vol in VOLS:
        base = os.path.join(SNAP, vol, "products", vol)
        pages = sorted(glob.glob(base + "/seed_admit/p*.json"))
        for pf in pages:
            key = os.path.basename(pf)[:-5]
            page = int(key[1:])
            sa = load(pf)["seed_admit"]
            tg = [(col, ch) for col in sa["columns"] for ch in col["chars"] if ch["char"] in TARGET]
            if not tg:
                continue
            cs = load(f"{base}/cell_shrink/{key}.json")["char_index"]
            cmap = {c["col"]: c for c in cs["columns"]}
            cells = {ch["id"]: ch for c in cs["columns"] for ch in c["chars"]}
            ar = load(f"{base}/align_ref/{key}.json")["align_ref"]
            ref = {c["id"]: c["ref_char"] for c in ar.get("coord", [])}
            gm = {ch["id"]: ch for c in load(f"{base}/glyph_match/{key}.json")["glyph_match"]["columns"]
                  for ch in c["chars"]}
            rc = {ch["id"]: ch for c in load(f"{base}/rare_candidates/{key}.json")["rare_candidates"]["columns"]
                  for ch in c["chars"]}
            img = cv2.imdecode(np.fromfile(f"{WS}/data_full/zongmu/{vol}/{page}.png", np.uint8), 0)
            meas_cache = {}

            def meas(cid):
                if cid in meas_cache:
                    return meas_cache[cid]
                c = cells.get(cid)
                r = None
                if c is not None and c.get("bbox_page") and c["cell_type"] == "char":
                    r = tight_box(crop_patch(img, tuple(c["bbox_page"])))
                meas_cache[cid] = r
                return r

            for col, ch in tg:
                cid = ch["id"]
                c = cells.get(cid)
                if c is None or not c.get("bbox_page"):
                    continue
                colno = int(cid.split(":")[2])
                colcells = [x for x in cmap[colno]["chars"] if x["cell_type"] == "char"]
                same = [x for x in colcells if (x["sub"] is None) == (c["sub"] is None)
                        and (x["step3_kind"] == "jiazhu") == (c["step3_kind"] == "jiazhu")]
                same.sort(key=lambda x: x["bbox_col"][1])
                ys = [(x["bbox_col"][1] + x["bbox_col"][3]) / 2 for x in same]
                period = float(np.median(np.diff(ys))) if len(ys) > 2 else None
                if not period or period < 20:
                    continue
                idx = [i for i, x in enumerate(same) if x["id"] == cid]
                if not idx:
                    continue
                i = idx[0]
                nb = [same[j] for j in range(max(0, i - 3), min(len(same), i + 4)) if j != i]
                nbm = [m for m in (meas(x["id"]) for x in nb) if m]
                me = meas(cid)
                if me is None:
                    continue
                reg = [x for x in colcells if x["sub"] is None and x["step3_kind"] != "jiazhu"]
                maxslot = max((x["slot"] for x in reg), default=0)
                if c["step3_kind"] == "jiazhu" or c["sub"]:
                    kind = "jiazhu"
                elif c["slot"] >= maxslot - 0:
                    kind = "tail"
                else:
                    kind = "body"
                cx0, cy0, cx1, cy1 = c["bbox_page"]
                sf = second_feats(me["mask"])
                h_cell = c["bbox_col"][3] - c["bbox_col"][1]
                gtop = (gm.get(cid, {}).get("candidates") or [[None]])[0][0]
                rtop = ((rc.get(cid, {}).get("candidates")) or [{"char": None}])[0]["char"]
                label = ch["char"]
                chan = ch["channel"]
                if not ch["admit"]:
                    tier = "unadmitted"
                elif chan == "human":
                    tier = "human"
                elif chan == "match_ref" and ref.get(cid) == label == gtop and rtop == label:
                    tier = "tri"
                elif chan == "match_ref" and ref.get(cid) == label == gtop:
                    tier = "dual"  # 缺 5-b 首位一致，只两路
                else:
                    tier = "other"
                nbw = [m["w"] for m in nbm]
                nbh = [m["h"] for m in nbm]
                row = dict(
                    vol=vol, page=page, col=colno, slot=c["slot"], sub=c["sub"], kind=kind, id=cid,
                    label=label, channel=chan, admit=ch["admit"], tier=tier,
                    ref=ref.get(cid), lib_top=gtop, rare_top=rtop, ctx_margin=ch["evidence"].get("ctx_margin"),
                    w=me["w"], h=me["h"], ink=me["ink"], period=period,
                    cell_w=c["width"], cell_h=c["height"],
                    nb_n=len(nbm),
                    nb_w_mean=float(np.mean(nbw)) if nbw else None,
                    nb_h_mean=float(np.mean(nbh)) if nbh else None,
                    nb_w_med=float(np.median(nbw)) if nbw else None,
                    nb_h_med=float(np.median(nbh)) if nbh else None,
                    pad_top=me["box"][1] / max(1, me["box"][1] + me["h"]),
                    **sf,
                )
                rows.append(row)
                # 裁块：紧墨框，目视用（带 4px 边）
                p = crop_patch(img, tuple(c["bbox_page"]))
                if p is not None:
                    cv2.imwrite(os.path.join(OUT, "crops", f"{vol}_p{page}_c{colno}_s{c['slot']}{c['sub'] or ''}_{label}.png"), p)
        print(vol, len(rows), flush=True)
    with open(os.path.join(OUT, "samples.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
