# -*- coding: utf-8 -*-
"""probe2 的分歧拼图：每类分歧抽样，左 CV 框（蓝）、右 YOLO 原生框（红），供目视裁。

    python sheets.py <probe2_raw.json> <原图目录> <guji-page 目录> <输出目录>
"""
import json, os, random, sys
from collections import Counter
import cv2, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from open_guji_cv.formats import guji_page as gp

RAW, IMG, GPD, OUT = sys.argv[1:5]
d = json.load(open(RAW))
random.seed(7)
imgs, pages = {}, {}


def im(p):
    if p not in imgs:
        imgs[p] = cv2.imread(f"{IMG}/{p}.png")
        pages[p] = gp.load(f"{GPD}/p{p:04d}.json")
    return imgs[p]


def tile(p, region, cvb, yob, label, scale=0.5):
    img = im(p)
    H, W = img.shape[:2]
    x, y, w, h = region
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    a, b = img[y0:y1, x0:x1].copy(), img[y0:y1, x0:x1].copy()
    for bb in cvb:
        cv2.rectangle(a, (bb[0] - x0, bb[1] - y0), (bb[0] + bb[2] - x0, bb[1] + bb[3] - y0), (220, 100, 0), 3)
    for bb in yob:
        cv2.rectangle(b, (bb[0] - x0, bb[1] - y0), (bb[0] + bb[2] - x0, bb[1] + bb[3] - y0), (0, 0, 230), 3)
    t = np.hstack([a, np.full((a.shape[0], 8, 3), 255, np.uint8), b])
    t = cv2.resize(t, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    lab = np.full((22, t.shape[1], 3), 255, np.uint8)
    cv2.putText(lab, label, (3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
    return np.vstack([lab, t])


def sheet(tiles, path, per_row=6):
    if not tiles:
        return
    h = max(t.shape[0] for t in tiles); w = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, w - t.shape[1] + 10, cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in tiles]
    rows = [np.hstack(tiles[i:i + per_row] + [np.full((h, w + 10, 3), 255, np.uint8)] * (per_row - len(tiles[i:i + per_row])))
            for i in range(0, len(tiles), per_row)]
    cv2.imwrite(path, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 80])


def cv_boxes_near(p, reg):
    return [g["box"] for g in pages[p]["glyphs"] if g.get("box") and gp.iou(g["box"], reg) > 0]


def yo_boxes_near(p, reg, feed="native"):
    return [e["box"] for e in d["extra"] if e["page"] == p and e["feed"] == feed and gp.iou(e["box"], reg) > 0] + \
           [r["nat_box"] for r in d["rows"] if r["page"] == p and r["nat_box"] and gp.iou(r["nat_box"], reg) > 0]




def main():
    # 1) 「其他」多余框细分
    cls = Counter()
    noov = []
    for e in d["extra"]:
        if e["feed"] != "native" or e["where"] != "其他":
            continue
        im(e["page"])
        ov = [g for g in pages[e["page"]]["glyphs"] if g.get("box") and gp.iou(g["box"], e["box"]) > 0.05]
        if not ov:
            k = "不压任何 CV 字框"; noov.append(e)
        elif any(r["page"] == e["page"] and r["nat_box"] and gp.iou(r["nat_box"], e["box"]) > 0.3 for r in d["rows"]):
            k = "与另一 YOLO 框重叠（重复检出）"
        else:
            k = "压着 CV 字框但 IoU<0.5（切法不同）"
        e["sub"] = k
        cls[k] += 1
    print("其他·细分", dict(cls))
    json.dump(d, open(RAW, "w"), ensure_ascii=False)

    def ctx(box, pad=60):
        return [box[0] - pad, box[1] - pad * 2, box[2] + 2 * pad, box[3] + 4 * pad]

    T = []
    for e in random.sample(noov, min(24, len(noov))):
        r = ctx(e["box"]); T.append(tile(e["page"], r, cv_boxes_near(e["page"], r), yo_boxes_near(e["page"], r), f"p{e['page']} conf{e['conf']:.2f}"))
    sheet(T, f"{OUT}/1_yolo_extra_no_cv.jpg")
    mis = [e for e in d["extra"] if e.get("sub") == "压着 CV 字框但 IoU<0.5（切法不同）"]
    T = []
    for e in random.sample(mis, min(24, len(mis))):
        r = ctx(e["box"]); T.append(tile(e["page"], r, cv_boxes_near(e["page"], r), yo_boxes_near(e["page"], r), f"p{e['page']} conf{e['conf']:.2f}"))
    sheet(T, f"{OUT}/2_yolo_cv_disagree.jpg")

    # 3) 难粘连：YOLO 不是 2 个框的全部 + 2 个框的抽 18
    tc = d["touch"]
    odd = [t for t in tc if t["hard"] and t["n_nat"] != 2]
    even = random.sample([t for t in tc if t["hard"] and t["n_nat"] == 2], 18)
    for name, sub in (("3_touch_hard_disagree", odd), ("4_touch_hard_both2", even)):
        T = []
        for t in sub:
            u = gp.union_xywh(t["cv"]); r = [u[0] - 40, u[1] - 60, u[2] + 80, u[3] + 120]
            T.append(tile(t["page"], r, t["cv"], t["nat"], f"p{t['page']}c{t['col']} s{t['slots']} y{t['n_nat']}"))
        sheet(T, f"{OUT}/{name}.jpg", per_row=6)

    # 5) CV 字框 YOLO 原生没命中：列首/列尾/其他
    for name, pred in (("5_missed_head_tail", lambda r: "列首字" in r["tags"] or "列尾字" in r["tags"]),
                       ("6_missed_other", lambda r: not ("列首字" in r["tags"] or "列尾字" in r["tags"]))):
        sub = [r for r in d["rows"] if (r["nat_iou"] is None) and pred(r)]
        T = []
        for r0 in sub[:30]:
            r = ctx(r0["box"]); T.append(tile(r0["page"], r, [r0["box"]], yo_boxes_near(r0["page"], r), f"p{r0['page']}c{r0['col']}s{r0['slot']} {''.join(r0['tags'][:2])}"))
        sheet(T, f"{OUT}/{name}.jpg")
        print(name, len(sub))

    # 7) 单行小注
    sub = [r for r in d["rows"] if "单行小注" in r["tags"]]
    T = []
    for r0 in sub[:18]:
        r = ctx(r0["box"], 80); T.append(tile(r0["page"], r, cv_boxes_near(r0["page"], r), yo_boxes_near(r0["page"], r), f"p{r0['page']}c{r0['col']}s{r0['slot']}"))
    sheet(T, f"{OUT}/7_solo_note.jpg")

    # 8) 版框上下沿的多余框（两种喂法）
    for feed in ("native", "cvstrip"):
        sub = [e for e in d["extra"] if e["feed"] == feed and e["where"].startswith("版框")]
        T = []
        for e in random.sample(sub, min(24, len(sub))):
            r = ctx(e["box"], 70)
            T.append(tile(e["page"], r, cv_boxes_near(e["page"], r), [e["box"]], f"p{e['page']} {e['where']} {e['conf']:.2f}"))
        sheet(T, f"{OUT}/8_frame_extra_{feed}.jpg")


if __name__ == "__main__":
    main()
