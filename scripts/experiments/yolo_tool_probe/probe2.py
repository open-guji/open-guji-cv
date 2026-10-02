# -*- coding: utf-8 -*-
"""yolo_tool 的 YOLO 版面/单字模型 vs CV 切分：分场景对比（四庫 vol03，27 页）。

    python probe2.py <yolo_tool 仓> <vol03 原图目录> <guji-page 目录> <products 根> <输出目录>

guji-page 目录里是 `export_guji_page.py` 从同一快照导出的 pNNNN.json（CV 字框、列、留白/排除标记），
products 根用来读 Step1 版框线（上下框 y）与 Step3 切点候选（判「粘连」）。

YOLO 跑两种喂法：
- **原生**：照 yolo_tool `BatchInferWorker`——版面模型整页 → 每个版面框原样裁条 → 单字模型；
- **CV 列条**：CV 列框左右 +8px、上下各 +40px（**故意带上版框线**）→ 单字模型，专看框线噪声。

字级配对：同列内按 IoU 贪心一对一，IoU≥0.5 算命中。场景标签按 CV 字位打：
正文 / 抬头字 / 双行夹注 / 单行小注 / 列首字 / 列尾字 / 短列（列末有留白）里的字 / 粘连（与上或下邻字之间
所有候选切线都穿墨，`seam_ink>0`）/ 印章压字。
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict

import cv2
import numpy as np
import onnxruntime as ort

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from open_guji_cv.formats import guji_page as gp  # noqa: E402

YOLO, RAW, GPD, PROD, OUT = sys.argv[1:6]
BOOK = sys.argv[6] if len(sys.argv) > 6 else "vol03"
PAGES = ([int(x) for x in sys.argv[7].split(",")] if len(sys.argv) > 7 else
         [3, 6, 8, 9, 10, 11, 12, 13, 15, 17, 20, 25, 27, 28, 31, 39, 49, 50, 51, 64, 67, 78, 80, 83, 92, 100, 103])
TYPE_NAMES = ["text", "subText", "midText", "ear", "subText2", "midSubText"]
sess = {m: ort.InferenceSession(f"{YOLO}/model/{m}/best.onnx", providers=["CPUExecutionProvider"])
        for m in ("type", "slide")}


def detect(m, img, conf=0.25, iou=0.45):
    h, w = img.shape[:2]
    r = 1024 / max(h, w)
    nh, nw = max(1, int(round(h * r))), max(1, int(round(w * r)))
    pad = np.full((1024, 1024, 3), 114, np.uint8)
    top, left = (1024 - nh) // 2, (1024 - nw) // 2
    pad[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    x = pad[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    out = sess[m].run(None, {"images": x})[0][0].T
    sc = out[:, 4:]
    cls, cf = sc.argmax(1), sc.max(1)
    k = cf >= conf
    b, cls, cf = out[k, :4], cls[k], cf[k]
    xywh = np.stack([(b[:, 0] - b[:, 2] / 2 - left) / r, (b[:, 1] - b[:, 3] / 2 - top) / r,
                     b[:, 2] / r, b[:, 3] / r], 1)
    idx = np.array(cv2.dnn.NMSBoxes(xywh.tolist(), cf.tolist(), conf, iou)).reshape(-1)
    return [([float(v) for v in xywh[i]], int(cls[i]), float(cf[i])) for i in idx]


def ib(b):
    return [int(round(b[0])), int(round(b[1])), max(1, int(round(b[2]))), max(1, int(round(b[3])))]


def greedy_match(cv_boxes, yo_boxes, thr=0.5):
    pairs = sorted(((gp.iou(c, y), i, j) for i, c in enumerate(cv_boxes) for j, y in enumerate(yo_boxes)),
                   reverse=True)
    mc, my, out = set(), set(), {}
    for s, i, j in pairs:
        if s < thr:
            break
        if i in mc or j in my:
            continue
        mc.add(i); my.add(j); out[i] = (j, s)
    return out


def frame_ys(prod_borders, W, x_tl):
    x_tr = (W - 1) - x_tl
    t, b = prod_borders["top"], prod_borders["bottom"]
    return t["y_at_right"] + t["slope"] * x_tr, b["y_at_right"] + b["slope"] * x_tr


rows = []           # 每个 CV 字位一行
extra = []          # 每个 YOLO 多出来的框一行
colrows = []        # 每个 CV 列一行（版面层）
touch_cases = []    # 粘连切点：两边各自怎么切
for p in PAGES:
    pg = gp.load(f"{GPD}/p{p:04d}.json")
    img = cv2.imread(f"{RAW}/{p}.png")
    H, W = img.shape[:2]
    bd = json.load(open(f"{PROD}/{BOOK}/border_detect/p{p:04d}.json"))["borders"]
    cells = json.load(open(f"{PROD}/{BOOK}/row_segment/p{p:04d}.json"))["cells"]
    touch = set()       # (col, slot_above, slot_below) 粘连切点：Step3 直线格线穿墨处（cut_candidates 非空）
    hard = set()        # 其中「难」的：多候选（≥2 种切法）或交下游再审（escalate）
    for col in cells["columns"]:
        for cc in col.get("cut_candidates", []):
            key = (col["col"], cc["slot_above"], cc["slot_below"])
            touch.add(key)
            if len(cc["candidates"]) >= 2 or cc.get("escalate"):
                hard.add(key)

    # ── YOLO 原生 ──
    tdet = detect("type", img)
    native = []
    for b, c, f in tdet:
        x, y, w, h = ib(b)
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 - x0 < 10 or y1 - y0 < 15:
            continue
        for sb, _, sf in detect("slide", img[y0:y1, x0:x1]):
            if sb[2] >= 6 and sb[3] >= 6:
                native.append((ib([sb[0] + x0, sb[1] + y0, sb[2], sb[3]]), sf, TYPE_NAMES[c]))
    # 原生框与 CV 字框全页一对一配对（原生框不保证落在 CV 列里）
    gl = [g for g in pg["glyphs"] if g.get("box")]
    m_nat = greedy_match([g["box"] for g in gl], [n[0] for n in native])
    nat_hit = {gl[i]["id"]: (native[j], s) for i, (j, s) in m_nat.items()}
    used_nat = {j for j, _ in m_nat.values()}

    marks_blank = [m["box"] for m in pg["marks"] if m["kind"] == "blank" and m.get("box")]
    marks_excl = [m["box"] for m in pg["marks"] if m["kind"] == "excluded" and m.get("box")]
    occl = [g["box"] for g in gl if "occluded" in g.get("flags", [])]

    cols_x = [(c["box"][0], c["box"][0] + c["box"][2]) for _, c in gp.iter_columns(pg) if c.get("box")]

    def where(box, ytop, ybot):
        cy = box[1] + box[3] / 2
        cx = box[0] + box[2] / 2
        if not any(a - 5 <= cx <= b + 5 for a, b in cols_x):
            return "列外（版心/页边）"
        if box[1] <= ytop + 12 or cy < ytop + 20:
            return "版框上沿"
        if box[1] + box[3] >= ybot - 12 or cy > ybot - 20:
            return "版框下沿"
        if any(gp.iou(box, o) > 0.2 for o in occl + marks_excl):
            return "印章/排除区"
        if any(gp.iou(box, o) > 0.3 for o in marks_blank):
            return "留白格"
        return "其他"

    for j, (box, sf, tcls) in enumerate(native):
        if j in used_nat:
            continue
        ytop, ybot = frame_ys(bd, W, box[0] + box[2] / 2)
        extra.append(dict(page=p, feed="native", box=box, conf=sf, tcls=tcls, where=where(box, ytop, ybot)))

    # ── 版面层：CV 列 vs YOLO 版面框 ──
    tboxes = [(ib(b), TYPE_NAMES[c], f) for b, c, f in tdet]
    for _, col in gp.iter_columns(pg):
        if not col.get("box"):
            continue
        cx0, cx1 = col["box"][0], col["box"][0] + col["box"][2]
        cg = [g for g in gl if g.get("col") == col["id"]]
        if not cg:
            continue
        inside = [t for t in tboxes if cx0 <= t[0][0] + t[0][2] / 2 <= cx1]
        cov = sum(1 for g in cg if any(gp.iou(g["box"], t[0]) > 0 and
                                       t[0][0] <= g["box"][0] + g["box"][2] / 2 <= t[0][0] + t[0][2] and
                                       t[0][1] <= g["box"][1] + g["box"][3] / 2 <= t[0][1] + t[0][3]
                                       for t in tboxes))
        # 一个 YOLO 版面框横跨两列以上？
        span = max([sum(1 for _, c2 in gp.iter_columns(pg) if c2.get("box") and
                        min(t[0][0] + t[0][2], c2["box"][0] + c2["box"][2]) - max(t[0][0], c2["box"][0])
                        > 0.3 * c2["box"][2]) for t in inside] or [0])
        colrows.append(dict(page=p, col=col["n"], lanes=sorted({g["lane"] for g in cg}), n_cv=len(cg),
                            n_type=len(inside), type_cls=sorted({t[1] for t in inside}), glyph_cov=cov,
                            max_span=span, raised=col.get("raised", 0)))

    # ── CV 列条喂法（带版框线） ──
    for _, col in gp.iter_columns(pg):
        if not col.get("box"):
            continue
        cx, cy, cw, ch = col["box"]
        x0, x1 = max(0, cx - 8), min(W, cx + cw + 8)
        y0, y1 = max(0, cy - 40), min(H, cy + ch + 40)
        sdet = [ib([b[0] + x0, b[1] + y0, b[2], b[3]]) + [f] for b, _, f in detect("slide", img[y0:y1, x0:x1])
                if b[2] >= 6 and b[3] >= 6]
        cg = [g for g in gl if g.get("col") == col["id"]]
        m_col = greedy_match([g["box"] for g in cg], [s[:4] for s in sdet])
        used = {j for j, _ in m_col.values()}
        for j, s in enumerate(sdet):
            if j not in used:
                ytop, ybot = frame_ys(bd, W, s[0] + s[2] / 2)
                extra.append(dict(page=p, feed="cvstrip", box=s[:4], conf=s[4], tcls="", where=where(s[:4], ytop, ybot)))
        slots = sorted(g["slot"] for g in cg if g["lane"] == "main")
        blanks_after = any(m["kind"] == "blank" and m.get("col") == col["id"] and m["slot"] > (max(slots) if slots else 99)
                           for m in pg["marks"])
        for i, g in enumerate(cg):
            ytop, ybot = frame_ys(bd, W, g["box"][0] + g["box"][2] / 2)
            tags = []
            tags.append({"main": "正文", "jz_r": "双行夹注", "jz_l": "双行夹注", "solo": "单行小注"}[g["lane"]])
            if g["slot"] < 0:
                tags.append("抬头字")
            if g["lane"] == "main" and slots and g["slot"] == slots[0]:
                tags.append("列首字")
            if g["lane"] == "main" and slots and g["slot"] == slots[-1]:
                tags.append("列尾字")
            if blanks_after:
                tags.append("短列")
            nb = {(col["n"], g["slot"], g["slot"] + 1), (col["n"], g["slot"] - 1, g["slot"])}
            if nb & touch:
                tags.append("粘连")
            if nb & hard:
                tags.append("粘连·难")
            if "occluded" in g.get("flags", []):
                tags.append("印章压字")
            nh = nat_hit.get(g["id"])
            sh = m_col.get(i)
            rows.append(dict(page=p, col=col["n"], slot=g["slot"], lane=g["lane"], tags=tags, box=g["box"],
                             review=g["review"], frame_top=ytop, frame_bot=ybot,
                             nat_iou=round(nh[1], 3) if nh else None, nat_box=nh[0][0] if nh else None,
                             strip_iou=round(sh[1], 3) if sh else None,
                             strip_box=sdet[sh[0]][:4] if sh else None))
        # 粘连切点：看两边各出了几个框
        for (cn, sa, sb2) in touch:
            if cn != col["n"]:
                continue
            ga = next((g for g in cg if g["slot"] == sa and g["lane"] == "main"), None)
            gb = next((g for g in cg if g["slot"] == sb2 and g["lane"] == "main"), None)
            if not ga or not gb:
                continue
            uni = gp.union_xywh([ga["box"], gb["box"]])
            ys = [s[:4] for s in sdet if gp.iou(s[:4], uni) > 0 and
                  uni[1] - 10 <= s[1] + s[3] / 2 <= uni[1] + uni[3] + 10]
            nat = [n[0] for n in native if gp.iou(n[0], uni) > 0 and
                   uni[1] - 10 <= n[0][1] + n[0][3] / 2 <= uni[1] + uni[3] + 10 and
                   uni[0] - 10 <= n[0][0] + n[0][2] / 2 <= uni[0] + uni[2] + 10]
            touch_cases.append(dict(page=p, col=cn, slots=[sa, sb2], cv=[ga["box"], gb["box"]], yolo=ys,
                                    n_yolo=len(ys), nat=nat, n_nat=len(nat), hard=(cn, sa, sb2) in hard,
                                    review=[ga["review"], gb["review"]]))

os.makedirs(OUT, exist_ok=True)
json.dump(dict(rows=rows, extra=extra, cols=colrows, touch=touch_cases), open(f"{OUT}/probe2_raw.json", "w"),
          ensure_ascii=False)

# ── 汇总 ──
def rate(sub, key):
    n = len(sub)
    h = sum(1 for r in sub if r[key] is not None and r[key] >= 0.5)
    return f"{h}/{n} ({100 * h / max(n, 1):.1f}%)"


def med(sub, key):
    v = sorted(r[key] for r in sub if r[key] is not None)
    return round(v[len(v) // 2], 2) if v else None


print("== 字级：CV 字框被 YOLO 命中（IoU≥0.5），原生喂法 / CV 列条喂法；中位 IoU")
tagset = ["正文", "抬头字", "双行夹注", "单行小注", "列首字", "列尾字", "短列", "粘连", "粘连·难", "印章压字"]
for t in ["(全部)"] + tagset:
    sub = rows if t == "(全部)" else [r for r in rows if t in r["tags"]]
    if not sub:
        continue
    print(f"  {t:6s} n={len(sub):5d}  原生 {rate(sub, 'nat_iou'):18s} 中位 {med(sub, 'nat_iou')}   "
          f"列条 {rate(sub, 'strip_iou'):18s} 中位 {med(sub, 'strip_iou')}")
print("== YOLO 多出来的框（CV 没有对应字框），按位置")
for feed in ("native", "cvstrip"):
    c = Counter(e["where"] for e in extra if e["feed"] == feed)
    hc = Counter(e["where"] for e in extra if e["feed"] == feed and e["conf"] >= 0.5)
    print(f"  {feed:8s} 共 {sum(c.values())}（置信≥0.5 的 {sum(hc.values())}）：",
          "，".join(f"{k} {v}（≥0.5: {hc[k]}）" for k, v in c.most_common()))
print("== 版面层（每个 CV 列）")
c = Counter()
for r in colrows:
    c["列"] += 1
    c["有 YOLO 版面框"] += r["n_type"] > 0
    c["一个版面框横跨≥2 个 CV 列"] += r["max_span"] >= 2
    c["CV 字被版面框盖住≥95%"] += r["glyph_cov"] >= 0.95 * r["n_cv"]
    if "jz_r" in r["lanes"]:
        c["CV 夹注列"] += 1
        c["CV 夹注列·YOLO 给了 subText"] += "subText" in r["type_cls"]
    else:
        c["CV 无夹注列·YOLO 却给 subText"] += "subText" in r["type_cls"]
    if r["raised"]:
        c["抬头列"] += 1
print("  ", dict(c))
print("== 粘连切点：CV 切成 2 个，YOLO 在这两字范围里出了几个框（原生 / 列条）")
for hd in (False, True):
    sub = [t for t in touch_cases if t["hard"] == hd]
    print("  ", "难" if hd else "一般", len(sub), "原生", dict(Counter(t["n_nat"] for t in sub)),
          "列条", dict(Counter(t["n_yolo"] for t in sub)))
print("== 「其他」多余框（原生）按版面类别", dict(Counter(e["tcls"] for e in extra if e["feed"] == "native" and e["where"] == "其他")))
