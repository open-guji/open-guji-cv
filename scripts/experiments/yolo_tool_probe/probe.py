"""把 yolo_tool 的 type/slide ONNX 模型跑在四庫 vol03 两页上，与 CV 的列与字框对比。

    pip install onnxruntime      # 不用 torch / ultralytics，直接跑仓里的 best.onnx
    python scripts/experiments/yolo_tool_probe/probe.py <yolo_tool 仓> <vol03 原图目录> <输出目录> > result.json

CV 一侧取 doc/formats/samples/guji_page_v0/ 的两张 guji-page 样张（列框、字框、排除标记）。
单字模型的输入 = CV 列框左右各放 8px、上下各放 40px 的竖条（yolo_tool 自己是拿版面模型的框去裁）。
前处理照 ultralytics：等比缩到 1024、居中补 114 灰；置信 0.25、NMS IoU 0.45、丢掉 <6px 的框（同 yolo_tool）。
"""
import json, sys, os
import numpy as np, cv2, onnxruntime as ort
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from open_guji_cv.formats import guji_page as gp
YOLO, R, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
D = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'doc', 'formats', 'samples', 'guji_page_v0')
sess = {m: ort.InferenceSession(f'{YOLO}/model/{m}/best.onnx', providers=['CPUExecutionProvider']) for m in ('type', 'slide')}
TYPE_NAMES = ['text', 'subText', 'midText', 'ear', 'subText2', 'midSubText']

def detect(m, img, conf=0.25, iou=0.45):
    h, w = img.shape[:2]
    r = 1024 / max(h, w)
    nh, nw = int(round(h * r)), int(round(w * r))
    pad = np.full((1024, 1024, 3), 114, np.uint8)
    top, left = (1024 - nh) // 2, (1024 - nw) // 2
    pad[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    x = pad[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    out = sess[m].run(None, {'images': x})[0][0].T          # N × (4+nc)
    sc = out[:, 4:]; cls = sc.argmax(1); cf = sc.max(1)
    k = cf >= conf
    b, cls, cf = out[k, :4], cls[k], cf[k]
    xywh = np.stack([(b[:, 0] - b[:, 2] / 2 - left) / r, (b[:, 1] - b[:, 3] / 2 - top) / r, b[:, 2] / r, b[:, 3] / r], 1)
    idx = cv2.dnn.NMSBoxes(xywh.tolist(), cf.tolist(), conf, iou)
    idx = np.array(idx).reshape(-1)
    return [(xywh[i].tolist(), int(cls[i]), float(cf[i])) for i in idx]

res = {}
for pno, imgf, desc in ((3, '3.png', 'page'), (107, '107.png', 'canvas')):
    pg = gp.load(f'{D}/p{pno:04d}.guji-page.json')
    if desc == 'canvas':
        dst = json.load(open(f'{D}/meta.json'))['pages'][str(pno)]['canvas_image']
    else:
        dst = pg['image']
    img = cv2.imread(f'{R}/{imgf}')
    vis = img.copy()
    tdet = detect('type', img)
    for (x, y, w, h), c, f in tdet:
        cv2.rectangle(vis, (int(x), int(y)), (int(x + w), int(y + h)), (0, 160, 0) if c else (255, 0, 0), 6)
    page_rows = []
    for _, col in gp.iter_columns(pg):
        if not col.get('box'): continue
        cx, cy, cw, ch = gp.map_box(col['box'], pg['image'], dst)
        x0, x1 = max(0, cx - 8), min(img.shape[1], cx + cw + 8)
        y0, y1 = max(0, cy - 40), min(img.shape[0], cy + ch + 40)
        strip = img[y0:y1, x0:x1]
        sdet = [([bx + x0, by + y0, bw, bh], c, f) for (bx, by, bw, bh), c, f in detect('slide', strip)]
        sdet = [d for d in sdet if d[0][2] >= 6 and d[0][3] >= 6]
        cvg = [gp.map_box(g['box'], pg['image'], dst) for g in pg['glyphs'] if g.get('col') == col['id'] and g.get('box')]
        cvb = [gp.map_box(m['box'], pg['image'], dst) for m in pg['marks'] if m.get('col') == col['id'] and m['kind'] == 'excluded' and m.get('box')]
        matched = sum(1 for g in cvg if any(gp.iou(g, [int(v) for v in d[0]]) >= 0.5 for d in sdet))
        lanes = sorted({g['lane'] for g in pg['glyphs'] if g.get('col') == col['id']})
        page_rows.append(dict(col=col['n'], lanes=lanes, cv_glyphs=len(cvg), cv_excluded=len(cvb), yolo=len(sdet), iou50=matched,
                              yolo_widths=[round(d[0][2]) for d in sdet][:3]))
        for (bx, by, bw, bh), c, f in sdet:
            cv2.rectangle(vis, (int(bx), int(by)), (int(bx + bw), int(by + bh)), (0, 0, 255), 3)
        for g in cvg:
            cv2.rectangle(vis, (g[0], g[1]), (g[0] + g[2], g[1] + g[3]), (255, 160, 0), 2)
    res[pno] = dict(type=[(TYPE_NAMES[c], round(f, 2), [round(v) for v in b]) for b, c, f in tdet], cols=page_rows)
    s = 1200 / vis.shape[1]
    cv2.imwrite(f'{OUT}/yolo_p{pno}.jpg', cv2.resize(vis, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 82])
print(json.dumps(res, ensure_ascii=False, indent=0))
