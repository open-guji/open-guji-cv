"""反事实：把整页「中等墨点」(面积≤AMAX 的连通块) 抹白，造一张「无印章斑点」的页，放进 overlay 工作区。
用法: python make_clean.py <ws_src> <ws_overlay> <book> <page> [AMAX=150]"""
import sys, os, cv2, numpy as np
src, ov, book, page = sys.argv[1:5]; amax = int(sys.argv[5]) if len(sys.argv) > 5 else 150
img = cv2.imread(f"{src}/data_full/zongmu/{book}/{page}.png", 0)
b = (img < 128).astype(np.uint8)
n, lab, st, _ = cv2.connectedComponentsWithStats(b, connectivity=8)
kill = np.zeros(n, bool); kill[1:] = st[1:, cv2.CC_STAT_AREA] <= amax
out = img.copy(); out[kill[lab]] = 255
d = f"{ov}/data_full/zongmu/{book}"; os.makedirs(d, exist_ok=True)
cv2.imwrite(f"{d}/{page}.png", out); print("erased", int(kill.sum()), "blobs")
