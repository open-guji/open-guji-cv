"""矮格复核包(10 格):每格出一张原图叠图(红=该列各格上沿,绿=被复核格的上下沿)+ 清单 json/md。
用法: python3 -I runt_review_pack.py <out_dir>   (需各册产物与原图在固定路径,见脚本内 CASES)"""
import sys, json, pathlib, cv2, numpy as np
WS = "/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本"
ROOT = {"vol02": WS + "/products/vol02", "vol04": "/home/user/ws4/products/vol04", "vol05": "/home/user/wsall/vol05/products/vol05", "vol07": "/home/user/wsall/vol07/products/vol07"}
# (册, 页, 列, slot, 类别, 说明)
CASES = [("vol02", 113, 1, 4, "A 批已确认伤字", "老|莊,线切进「莊」上部;该格 41px=0.36 period"),
         ("vol02", 15, 9, 20, "矮格(中段)", "线从「元」下半穿过;37px"),
         ("vol02", 188, 4, 20, "矮格(中段)", "线从「足」下半穿过;39px"),
         ("vol04", 196, 2, 21, "末格矮(slot21)", "66px=0.58 period,有墨"),
         ("vol04", 196, 8, 21, "末格矮(slot21)", "66px=0.58 period,有墨"),
         ("vol05", 3, 5, 21, "末格矮(slot21)", "59px=0.52"),
         ("vol05", 46, 8, 21, "末格矮(slot21)", "63px=0.56"),
         ("vol05", 108, 2, 21, "末格矮(slot21)", "49px=0.43"),
         ("vol05", 154, 8, 21, "末格矮(slot21)", "67px=0.59"),
         ("vol07", 87, 8, 21, "末格矮(slot21)", "65px=0.58")]
# 未入包:vol04 14:5 slot21 是空列末格(ink 0.02,前一格 ink 0),不是字格切错
def main(out):
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True); lst = []
    for bk, pg, col, slot, kind, note in CASES:
        d = json.load(open(f"{ROOT[bk]}/row_segment/p{pg:04d}.json"))["cells"]; c = next(c for c in d["columns"] if c["col"] == col)
        cell = next(x for x in c["cells"] if x["slot"] == slot)
        g = cv2.imdecode(np.fromfile(f"{WS}/data_full/zongmu/{bk}/{pg}.png", np.uint8), cv2.IMREAD_GRAYSCALE); W = g.shape[1]
        def pts(q): return [(W - 1 - x, y) for x, y in q]          # quad_page 右上原点 → 左上原点
        q = pts(cell["quad_page"]); xs = [p[0] for p in q]; ys = [p[1] for p in q]
        x0, x1 = int(min(xs)) - 40, int(max(xs)) + 40; y0, y1 = max(0, int(min(ys)) - 260), int(max(ys)) + 260; x0 = max(0, x0)
        v = cv2.cvtColor(g[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)
        for cc in c["cells"]:                                       # 红:各格上沿
            qq = pts(cc["quad_page"]); a = (int(qq[0][0]) - x0, int(qq[0][1]) - y0); b = (int(qq[1][0]) - x0, int(qq[1][1]) - y0)
            cv2.line(v, a, b, (0, 0, 255), 1)
        for a, b in ((q[0], q[1]), (q[3], q[2])):                    # 绿:被复核格上下沿
            cv2.line(v, (int(a[0]) - x0, int(a[1]) - y0), (int(b[0]) - x0, int(b[1]) - y0), (0, 160, 0), 2)
        h = round(cell["y1"] - cell["y0"]); per = round(d["period"]); fn = f"{bk}_p{pg}_c{col}_s{slot}.png"
        cv2.putText(v, f"{bk} p{pg} c{col} slot{slot} h={h}px (period {per})", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
        cv2.imwrite(str(out / fn), v)
        lst.append(dict(cell_id=f"{bk}:{pg}:{col}:{slot}", book=bk, page=pg, col=col, slot=slot, h_px=h, period=per, ratio=round(h / per, 2),
                        kind=kind, note=note, ink_ratio=cell["ink_ratio"], image=f"overlays/runt_review/{fn}",
                        page_image=f"data_full/zongmu/{bk}/{pg}.png", product=f"{bk}/row_segment/p{pg:04d}.json"))
    json.dump(lst, open(out.parent / "runt_review_10.json", "w"), ensure_ascii=False, indent=1)
    md = ["# 矮格复核 10 格(overview#554)", "", "问每格:**线是否切进了字/多切了一格**(绿线=该格上下沿,红线=本列各格上沿)。回:对/切错/拿不准。", "",
          "| cell_id | 类别 | h/period | 说明 | 图 |", "|---|---|---|---|---|"]
    md += [f"| `{x['cell_id']}` | {x['kind']} | {x['h_px']}/{x['period']}={x['ratio']} | {x['note']} | `{x['image']}` |" for x in lst]
    md += ["", "未入包:`vol04:14:5:21`(空列末格,ink 0.02、前一格 ink 0,不是字格切错)。", "cell_id 格式 = `册:页:列:slot`(同 touching-cuts 的 id 口径)。"]
    (out.parent / "runt_review_10.md").write_text("\n".join(md), encoding="utf-8")
    print(len(lst))
if __name__ == "__main__": main(sys.argv[1])
