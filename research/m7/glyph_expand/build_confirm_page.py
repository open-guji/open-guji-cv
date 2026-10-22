"""待确认页：禽会俞命舍 预填标签＋少数形补采样候选。生成单文件 HTML（字块图内嵌 data URI，答案写 db 的 answers 集合）。
用法：python build_confirm_page.py <产物根> <原图根> <输出 html>"""
import base64
import json
import sys
from pathlib import Path

import cv2

from crops_by_id import crop

# (格 id, 选项, 预填, 是否没把握, 分组, 备注)
Q = "禽會俞命舍曾合愈"
A = [("vol04:17:8:3", "禽"), ("vol04:17:8:5", "禽"), ("vol06:110:5:11", "禽"), ("vol08:33:3:4", "禽"), ("vol08:57:8:5", "禽"),
     ("vol08:65:5:10", "禽"), ("vol09:112:7:19", "禽"), ("vol09:209:1:5", "禽"), ("vol09:247:5:7", "禽"), ("vol09:255:3:13", "禽"),
     ("vol08:54:8:4", "禽"), ("vol09:265:6:12", "禽"), ("vol10:19:5:4", "俞")]
A_UNSURE = [("vol09:179:5:9", "禽"), ("vol09:243:8:4", "曾"), ("vol09:137:8:6", "曾")]
B = [("蒙𫎇", "蒙", ["vol04:145:3:15", "vol05:93:6:7", "vol05:96:6:8", "vol05:96:6:14", "vol05:96:7:8"]),
     ("隸𨽾", "隸", ["vol05:57:8:8a", "vol09:208:4:17"]),
     ("讖識䜟", "讖", ["vol04:121:9:10", "vol04:121:9:14", "vol04:121:9:16", "vol06:43:8:9"])]
B_UNSURE = [("隸𨽾", "𨽾", "vol08:20:5:8a")]


def uri(g):
    s = 96 / g.shape[0]
    g = cv2.resize(g, (max(1, int(g.shape[1] * s)), 96), interpolation=cv2.INTER_AREA)
    return "data:image/png;base64," + base64.b64encode(cv2.imencode(".png", g)[1].tobytes()).decode()


if __name__ == "__main__":
    prod, imgs, out = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    items = []
    def add(cid, opts, pre, sure, group):
        g = crop(prod, imgs, cid)
        items.append({"id": cid, "opts": opts, "pre": pre, "sure": sure, "group": group, "img": uri(g)})
    for cid, pre in A: add(cid, "禽會俞命舍", pre, True, "禽會俞命舍")
    for cid, pre in A_UNSURE: add(cid, "禽會俞命舍曾", pre, False, "禽會俞命舍")
    for pair, pre, ids in B:
        for cid in ids: add(cid, pair, pre, True, pair)
    for pair, pre, cid in B_UNSURE: add(cid, pair, pre, False, pair)
    tpl = Path(__file__).with_name("confirm_page.tpl.html").read_text(encoding="utf-8")
    Path(out).write_text(tpl.replace("__ITEMS__", json.dumps(items, ensure_ascii=False)), encoding="utf-8")
    print(len(items), Path(out).stat().st_size)
