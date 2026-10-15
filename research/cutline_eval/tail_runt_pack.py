"""末格矮(slot=n_body_slots、<0.6×period、有墨)扫描命中格的叠图包(vol01/03/06/08/09/10 各册,Mila 10-12 要量误并比例)。
读 tail_runt_scan_all.json(各册扫描结果),输出每格一张原图叠图(红=本列各格上沿,绿=该末格上下沿)。
用法: python3 -I tail_runt_pack.py <out_dir> [册 ...]"""
import sys, json, pathlib, cv2, numpy as np
WS = "/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本"
ROOT = {"vol01": "/home/user/wsall/vol01/cloud-20260927-32b9c2b/vol01", "vol03": "/home/user/wsall/vol03/products/vol03", "vol06": "/home/user/wsall/vol06/products/vol06",
        "vol08": "/home/user/wsall/vol08/products/vol08", "vol09": "/home/user/wsall/vol09/products/vol09", "vol10": "/home/user/wsall/vol10/products/vol10"}
def main(out, books):
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    scan = json.load(open(pathlib.Path(__file__).with_name("tail_runt_scan_all.json"))); made = []
    for bk in books:
        for pg, col, h, per, ratio, ink in scan[bk][3]:
            d = json.load(open(f"{ROOT[bk]}/row_segment/p{pg:04d}.json"))["cells"]; c = next(c for c in d["columns"] if c["col"] == col)
            cell = max(c["cells"], key=lambda x: x["slot"])
            g = cv2.imdecode(np.fromfile(f"{WS}/data_full/zongmu/{bk}/{pg}.png", np.uint8), cv2.IMREAD_GRAYSCALE)
            if g is None: print("缺图", bk, pg); continue
            W = g.shape[1]; pts = lambda q: [(W - 1 - x, y) for x, y in q]
            q = pts(cell["quad_page"]); xs = [p[0] for p in q]; ys = [p[1] for p in q]
            x0, x1 = max(0, int(min(xs)) - 40), int(max(xs)) + 40; y0, y1 = max(0, int(min(ys)) - 260), int(max(ys)) + 160
            v = cv2.cvtColor(g[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)
            for cc in c["cells"]:
                qq = pts(cc["quad_page"]); cv2.line(v, (int(qq[0][0]) - x0, int(qq[0][1]) - y0), (int(qq[1][0]) - x0, int(qq[1][1]) - y0), (0, 0, 255), 1)
            for a, b in ((q[0], q[1]), (q[3], q[2])): cv2.line(v, (int(a[0]) - x0, int(a[1]) - y0), (int(b[0]) - x0, int(b[1]) - y0), (0, 160, 0), 2)
            cv2.putText(v, f"{bk} p{pg} c{col} s{cell['slot']} h={h} ink={ink}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
            fn = f"{bk}_p{pg}_c{col}.png"; cv2.imwrite(str(out / fn), v); made.append(fn)
    print(len(made), "张")
if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:] or ["vol01", "vol03", "vol06", "vol08", "vol09", "vol10"])
