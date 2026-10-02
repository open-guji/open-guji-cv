"""Y1 任务 2：YOLO 版面模型当 Step1 列探测的第二意见，在 column-split 60 页人裁上量召回/误报。

    GUJI_WORKSPACE=<工作区> python y1_colcheck.py <column-split 目录> <border_detect 产物根> <yolo_tool 仓> <cache.json>

- 人裁：`verdicts_r1.jsonl`（ok 56 / extra 2 / miss 2）。
- CV 列数：当前 Step1 产物（`<产物根>/<book>/border_detect/pNNNN.json` 的 verticals−1）。**注意**：人裁是
  2026-09-02 对当时的 Step1 判的，4 个错页在现行 Step1 上已不错（见 HANDOFF_Y1.md），所以这里量不出召回，
  只量得出「一致性」与误报。
- YOLO 列数：版面模型（type）整页喂，text/subText/subText2 框（高≥120px）按水平重叠聚簇，夹注半行并列合一；
  **只数落在 CV 最外两条竖线之内的簇**（版心条 YOLO 会给 text 0.4–0.6，不属于 CV 的 9 列）。
- 空间判据：某 CV 列里 ≥2 个 YOLO 簇 / 某 YOLO 簇横跨 ≥2 个 CV 列 / CV 竖线穿过 YOLO 正文框内部（3/5 个采样点）。
"""
import json, os, sys
import cv2
from open_guji_cv.products.kinds.borders import VLineRec
from open_guji_cv.utils import yolo_boxes as yb

GOLD, PROD, YOLO, CACHE = sys.argv[1:5]
WS = os.environ["GUJI_WORKSPACE"] + "/data_full/zongmu"
CONF = float(os.environ.get("CONF", 0.25))
gold = {}
for l in open(f"{GOLD}/verdicts_r1.jsonl"):
    d = json.loads(l); _, b, p = d["id"].split(":"); gold[(b, int(p))] = d["verdict"]

cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
for (b, p) in sorted(gold):
    k = f"{b}/{p}"
    if k in cache: continue
    img = cv2.imread(f"{WS}/{b}/{p}.png", 0)
    cache[k] = [[*map(float, d[:5]), d[5]] for d in yb.detect_layout(f"{YOLO}/model/type/best.onnx", img)]
json.dump(cache, open(CACHE, "w"))


def clusters(boxes):
    cl = []
    for x, y, w, h, c, kcls in sorted(boxes, key=lambda b: b[0] + b[2] / 2):
        for g in cl:
            if min(g[1], x + w) - max(g[0], x) > 0.4 * min(g[1] - g[0], w):
                g[0], g[1] = min(g[0], x), max(g[1], x + w); g[2].add(kcls); break
        else:
            cl.append([x, x + w, {kcls}])
    return cl


rows = []
for (b, p), v in sorted(gold.items()):
    bd = json.load(open(f"{PROD}/{b}/border_detect/p{p:04d}.json"))["borders"]
    W = bd["width"]
    vl = [VLineRec(**x).to_vline() for x in bd["verticals"]]
    xs = sorted(W - 1 - x.x_at(bd["height"] / 2) for x in vl)         # 图像坐标，左→右
    cvint = list(zip(xs[:-1], xs[1:]))
    det = [d for d in cache[f"{b}/{p}"] if d[4] >= CONF and d[3] >= 120 and d[5] in ("text", "subText", "subText2")]
    cl = clusters(det)
    tw = sorted(g[1] - g[0] for g in cl if "text" in g[2]); med = tw[len(tw) // 2] if tw else None
    merged = []
    for g in cl:
        if merged and med and merged[-1][2] <= {"subText", "subText2"} and g[2] <= {"subText", "subText2"} \
           and g[1] - merged[-1][0] <= 1.35 * med and g[0] - merged[-1][1] < 0.25 * med:
            m = merged[-1]; m[1] = g[1]; m[2] |= g[2]
        else:
            merged.append(g)
    inside = [g for g in merged if xs[0] - 20 <= (g[0] + g[1]) / 2 <= xs[-1] + 20]   # 去掉版心条
    per_cv = [sum(1 for g in inside if a <= (g[0] + g[1]) / 2 <= c) for a, c in cvint]
    span = sum(1 for g in inside if sum(1 for a, c in cvint if min(g[1], c) - max(g[0], a) > 0.3 * (c - a)) >= 2)
    through = 0
    for d in det:
        x, y, w, h = d[:4]
        if d[5] != "text": continue
        ys = [y + h * f for f in (0.15, 0.3, 0.5, 0.7, 0.85)]
        for vlx in vl[1:-1]:
            if sum(1 for yy in ys if x + 0.25 * w < W - 1 - vlx.x_at(yy) < x + 0.75 * w) >= 3: through += 1
    rows.append(dict(key=f"{b}/{p}", gold=v, n_cv=len(cvint), n_y=len(inside), split=sum(c >= 2 for c in per_cv),
                     span=span, through=through))

def rep(name, f):
    wrong = [x for x in rows if x["gold"] != "ok"]; right = [x for x in rows if x["gold"] == "ok"]
    print(f"{name:26s} 抓住 {sum(map(f, wrong))}/{len(wrong)}  误报 {sum(map(f, right))}/{len(right)} "
          f"{[x['key'] for x in right if f(x)]}")
print(f"conf≥{CONF}")
rep("YOLO 列数 ≠ CV 列数", lambda x: x["n_y"] != x["n_cv"])
rep("某 CV 列里 ≥2 个 YOLO 簇", lambda x: x["split"] > 0)
rep("某 YOLO 簇横跨 ≥2 个 CV 列", lambda x: x["span"] > 0)
rep("CV 竖线穿过 YOLO 正文框", lambda x: x["through"] > 0)
for x in rows:
    if x["gold"] != "ok": print(x)
