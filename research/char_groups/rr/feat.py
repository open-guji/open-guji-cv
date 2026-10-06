"""入人八字形特征：二值化 → 取字体主体 → 归一化后的投影与顶部结构。纯 numpy/cv2，离线评测用，不进管线。"""
import json, os
import numpy as np, cv2

DS = os.environ.get("GUJI_DATASET", "/home/user/open-guji-dataset") + "/char-groups/rr"
CLS = "人入八"


def load_items(core_only=True):
    R = [json.loads(l) for l in open(DS + "/items.jsonl", encoding="utf-8")]
    return [r for r in R if r["core"] or not core_only]


def crop_path(r):
    return f"{DS}/crops/{r['id'].replace(':', '_')}.png"


def binarize(path):
    g = cv2.imread(path, 0)
    if g is None:
        return None
    g = cv2.GaussianBlur(g, (3, 3), 0)
    _, b = cv2.threshold(g, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b.astype(np.uint8)


def main_body(b):
    """去掉小碎点（斑点噪声）：保留面积 ≥ 最大连通块 8% 的块，裁到包围盒。"""
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    if n <= 1:
        return None, 0
    areas = st[1:, cv2.CC_STAT_AREA]
    keep = [i + 1 for i, a in enumerate(areas) if a >= 0.08 * areas.max()]
    m = np.isin(lab, keep).astype(np.uint8)
    ys, xs = np.where(m)
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1], len(keep)


def features(path, N=24):
    b = binarize(path)
    if b is None:
        return None
    m, ncc = main_body(b)
    if m is None or m.shape[0] < 8 or m.shape[1] < 8:
        return None
    h, w = m.shape
    img = cv2.resize(m.astype(np.float32), (N, N), interpolation=cv2.INTER_AREA)
    rowp = img.sum(1) / N
    colp = img.sum(0) / N
    # 顶部 1/3 带：横向占据范围、与下半的左右位置关系
    top = img[: N // 3]
    tcols = np.where(top.sum(0) > 0.25)[0]
    tleft = tcols.min() / N if len(tcols) else 1.0
    tright = tcols.max() / N if len(tcols) else 0.0
    tw = tright - tleft
    # 顶部带里的连通块数（八：一横与撇分离 → 2 块）
    tb = (m[: max(2, h // 3)] > 0).astype(np.uint8)
    ntop = cv2.connectedComponents(tb, connectivity=8)[0] - 1
    hand = np.array([h / w, ncc, ntop, tleft, tright, tw, top.sum() / (N * N / 3)], np.float32)
    return np.concatenate([img.ravel(), rowp, colp, hand]), hand
