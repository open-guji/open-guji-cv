# 无 GUI 复现 yolo_tool 的 type -> slide -> 排序（逐行对照 core/workers.py BatchInferWorker.run L95-192
# 与 ui/main_window.py _page_slide_order_arrays L1106-1146）。依赖: ultralytics, opencv-python, numpy, (可选) pymupdf
import sys, os, json
import cv2, numpy as np
from ultralytics import YOLO

TYPE_PT  = os.path.join(os.environ.get("YOLO_TOOL", "../yolo_tool"), "model/type/best.pt")   # yolov8m, nc=6, 训练 imgsz=1024
SLIDE_PT = os.path.join(os.environ.get("YOLO_TOOL", "../yolo_tool"), "model/slide/best.pt")  # yolov8n, nc=1('ch'), 训练 imgsz=1024
DEVICE = "cpu"   # GUI: Windows 用 '0'，其他 'cpu'（config.py L167）

def is_noise_box(w, h, min_w=8, min_h=8):            # workers.py L13
    return w < min_w or h < min_h

def load_page(path, page_idx=0):
    """PDF 按 GUI 的方式 2x 渲染（workers.py L103-105）；图片原样读（main_window.py L1580）。"""
    if path.lower().endswith(".pdf"):
        import fitz
        page = fitz.open(path).load_page(page_idx)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
        return cv2.cvtColor(img, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_BGRA2BGR)
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)

def sort_type_boxes(type_boxes_data):
    """workers.py L126-166：列聚类(右->左) + 列内按 top，夹注(subText)同行并排者右->左。"""
    type_boxes_data.sort(key=lambda b: b['top'])
    columns, global_last_text_width = [], None
    for box in type_boxes_data:
        b_left, b_right, b_width = box['left'], box['right'], box['width']
        best_col, max_overlap = None, 0.0
        for col in columns:
            ref = next((b for b in reversed(col) if b['cls_name'] != 'subText'), None)
            if ref:
                ref_left, ref_width = ref['left'], ref['width']
            else:
                ref_sub = col[-1]
                ref_width = global_last_text_width if global_last_text_width else ref_sub['width'] * 2
                ref_left = ref_sub['cx'] - ref_width / 2.0
            ref_right = ref_left + ref_width
            inter = max(0, min(b_right, ref_right) - max(b_left, ref_left))
            if b_width > 0:
                r = inter / b_width
                if r > 0.4 and r > max_overlap:
                    max_overlap, best_col = r, col
        if best_col is not None: best_col.append(box)
        else: columns.append([box])
        if box['cls_name'] != 'subText': global_last_text_width = box['width']
    columns.sort(key=lambda col: sum(b['cx'] for b in col) / len(col), reverse=True)
    out = []
    for col in columns:
        rows = []
        for box in col:
            is_sub, added = (box['cls_name'] == 'subText'), False
            if rows and is_sub:
                for ref in rows[-1]:
                    if ref['cls_name'] == 'subText':
                        t1, b1, t2, b2 = box['top'], box['bottom'], ref['top'], ref['bottom']
                        mh = min(b1 - t1, b2 - t2)
                        if mh > 0 and max(0, min(b1, b2) - max(t1, t2)) / mh > 0.3:
                            rows[-1].append(box); added = True; break
            if not added: rows.append([box])
        for row in rows:
            if len(row) > 1: row.sort(key=lambda b: b['cx'], reverse=True)
            out.extend(row)
    return out

def infer_page(cv_img, type_model, slide_model, type_conf=0.25, slide_conf=0.25):
    img_h, img_w = cv_img.shape[:2]
    # ---- 1) 版面: 整页直接喂，imgsz 不传 => 沿用 ckpt 的 1024，rect letterbox；iou 写死 0.45
    res = type_model.predict(source=cv_img, conf=type_conf, iou=0.45, verbose=False, device=DEVICE)
    names = type_model.names
    tb = []
    for b in res[0].boxes:
        x1, y1, x2, y2 = b.xyxy[0].cpu().numpy()
        w, h = float(x2 - x1), float(y2 - y1)
        if is_noise_box(w, h, min_w=10, min_h=15): continue
        cls_name = names[int(b.cls[0])]
        if 'text' not in cls_name.lower(): cls_name = 'text'      # 只有 'ear' 被改名为 text
        tb.append({'left': float(x1), 'right': float(x2), 'top': float(y1), 'bottom': float(y2),
                   'width': w, 'height': h, 'cx': float((x1 + x2) / 2), 'cy': float((y1 + y2) / 2),
                   'cls_name': cls_name, 'conf': float(b.conf[0])})
    sorted_t = sort_type_boxes(tb)
    # ---- 2) 每个版面框切条 -> slide；坐标 + (lx1, ly1) 回映射到整页
    t_list, s_list = [], []
    for t_id, box in enumerate(sorted_t, start=1):
        x1, y1, w, h = box['left'], box['top'], box['width'], box['height']
        t_list.append([x1, y1, w, h, box['cls_name'], box['conf'], 'type', t_id])
        lx1, ly1 = max(0, int(x1)), max(0, int(y1))
        lx2, ly2 = min(img_w, int(x1 + w)), min(img_h, int(y1 + h))
        crop = cv_img[ly1:ly2, lx1:lx2]          # 原图直接裁，不加 padding、不二值化、不缩放
        if crop.size == 0: continue
        sr = slide_model.predict(source=crop, conf=slide_conf, iou=0.45, verbose=False, device=DEVICE)
        tmp = []
        for sb in sr[0].boxes:
            cx1, cy1, cx2, cy2 = sb.xyxy[0].cpu().numpy()
            sw, sh = cx2 - cx1, cy2 - cy1
            if is_noise_box(sw, sh, min_w=6, min_h=6): continue
            tmp.append((cx1 + lx1, cy1 + ly1, sw, sh, float(sb.conf[0])))
        tmp.sort(key=lambda b: b[1] + b[3] / 2)  # 列内按中心 y 上->下
        for loc_id, (sx, sy, sw, sh, sc) in enumerate(tmp, start=1):
            s_list.append([float(sx), float(sy), float(sw), float(sh), 'text', sc, 'slide', loc_id])
    return t_list, s_list

def reading_order(t_list, s_list):
    """main_window.py _page_slide_order_arrays L1106-1146（GUI 载入/投影文本时的最终阅读序）：
    每个字框按“与版面框交集面积最大”唯一归属，再按 type 序号、列内中心 y 排。"""
    t_sorted = sorted(t_list, key=lambda b: b[7] if len(b) > 7 and b[7] > 0 else 9**9)
    def inter(a, b):
        w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]); h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
        return w * h if w > 0 and h > 0 else 0.0
    lines = {i: [] for i in range(len(t_sorted))}
    for s in s_list:
        best, mx = -1, 0.0
        for i, t in enumerate(t_sorted):
            a = inter(s, t)
            if a > mx: mx, best = a, i
        if best >= 0: lines[best].append(s)
    flat = []
    for i in range(len(t_sorted)):
        col = sorted(lines[i], key=lambda b: b[1] + b[3] / 2.0)
        flat.extend((i + 1, col_k, b) for col_k, b in enumerate(col, start=1))
    return flat   # [(type序号, 列内序号, slide框), ...]

if __name__ == "__main__":
    path = sys.argv[1]; page = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    img = load_page(path, page)
    tm, sm = YOLO(TYPE_PT), YOLO(SLIDE_PT)
    t_list, s_list = infer_page(img, tm, sm)
    order = reading_order(t_list, s_list)
    out = {"image_hw": img.shape[:2], "type": t_list,
           "chars": [{"gid": g, "col": c, "k": k, "xywh": b[:4], "conf": b[5]}
                     for g, (c, k, b) in enumerate(order, start=1)]}
    print(json.dumps(out, ensure_ascii=False))
