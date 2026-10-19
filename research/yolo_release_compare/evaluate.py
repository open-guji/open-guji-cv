"""yolo_tool 切分 release（四库总目殿本 16,516 页）与 CV 切分的对比评测（2026-10-19）。

结论见 doc/research/yolo_release_comparison.md；本文件只负责复现数字。

环境变量：
  SIKU_RELEASE  release zip 解压后的 96mid1ogzk/ 目录（file_archive release `siku-qiefen`）
  GUJI_WS96     guji-workspace 里 96mid1ogzk 的工作区目录（原图、vol04/05 报告、daizhige）
  YOLO_TOOL     open-guji/yolo_tool 检出目录（只 yolo 子命令要）

子命令（按顺序）：
  dzg                 release 与 ours(vol04/05 报告) 各自对 daizhige 逐列本的列边界吻合
  make-ws-a  <ws>     测试 A：release 原图抽 150 页，×1.465 缩到 period≈115，建临时工作区
  make-ws-b  <ws>     测试 B：我们 CADAL 原图 vol04/05 各 50 页，建临时工作区（不带 feedback = 纯算法）
  test-a     <ws> <yolo.jsonl>          逐框 P/R、逐列字数
  test-b     <ws> <yolo.jsonl> [err.json]  逐列字数（ours / yolo 原生 / yolo 轻清理）
  prior      <ws> <err.json>            把 release 列字数写成 column-slots 裁决（实验：列字数先验）

跑 CV：  guji pipeline keben_body_v2 <book> --to cell_shrink --pages <...> -w <ws>
跑 YOLO：python run_yolo.py <items.json> <out.jsonl>（items 由 make-ws-* 写出）
"""
import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from their import load_ch, boxes, img_path  # noqa: E402
from boxeval import match  # noqa: E402
from colcount import (their_colcounts, ours_colcounts, compare_counts,  # noqa: E402
                      yolo_columns, yolo_eval_cols)
from ours_prod import load_chars  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
WS96 = os.environ.get("GUJI_WS96", "../guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本")
SCALE_A = 1.465   # release 字距 ≈78.5px → 我们标定的 period 115px


def _col_kinds(r):
    cols = []
    for b in boxes(r):
        cx = (b["x0"] + b["x1"]) / 2
        if cols and abs(cols[-1]["cx"] - cx) < 55:
            cols[-1]["b"].append(b)
        else:
            cols.append({"cx": cx, "b": [b]})
    return ["夹注列" if any(x["small"] for x in c["b"]) else "正文列" for c in cols]


def _img_w(path):
    from PIL import Image
    return Image.open(path).width


def cmd_dzg():
    import re
    from dzg_eval import load_dzg, stream, their_book_cols, eval_cols, locate
    from ours_md import parse_md
    d = load_dzg()
    dz, ds, de = stream(d)
    per, tot, hint = [], collections.Counter(), 0
    for ch in range(1, 205):
        cols = [c for _, c in their_book_cols(ch)]
        text = "".join(cols)
        if not text:
            continue
        st, en, _, _ = locate(text, dz, max(0, hint - 2000))
        m, _ = eval_cols(cols, dz, ds, de, st, en)
        m.update(ch=ch, st=st, en=en)
        per.append(m)
        hint = en
        for k in ("n", "col_ok", "chars", "ins", "dele", "sub"):
            tot[k] += m[k]
    print("release 全书:", dict(tot), f"列边界吻合 {tot['col_ok'] / tot['n']:.4f}")
    byc = {m["ch"]: m for m in per}

    def clean(line):
        s = line.lstrip("^").lstrip(".")
        s = re.sub(r":jz\[([^\]]*)\]\{[^}]*\}", r"\1", s)
        s = s.replace("[[]]", "□")
        return re.sub(r"<([^>|]*)\|?([^>]*)>", lambda m: m.group(1) + m.group(2), s)

    for vol, chs in (("vol04", (10, 11)), ("vol05", (12, 13))):
        O = parse_md(f"{WS96}/reports/{vol}/{vol}.md")
        cols = [c for c in (clean(ln) for k in sorted(O) for ln in O[k]) if c.strip(".")]
        m, _ = eval_cols(cols, dz, ds, de, byc[chs[0]]["st"], byc[chs[1]]["en"])
        t = [byc[c] for c in chs]
        print(vol, "ours", m, f"{m['col_ok'] / m['n']:.4f}", "阙文□", sum(c.count("□") for c in cols))
        print(vol, "release", {k: sum(x[k] for x in t) for k in ("n", "col_ok", "ins", "dele", "sub")})


def cmd_make_ws_a(ws):
    import numpy as np
    from PIL import Image
    random.seed(20261018)
    pick = []
    for ch in range(1, 205):
        _, P = load_ch(ch)
        cand = [p for p, r in P.items() if len(r["x"]) >= 120 and p > 1]
        if cand:
            pick.append((ch, random.choice(cand)))
    random.shuffle(pick)
    pick = sorted(pick[:150])
    os.makedirs(f"{ws}/books", exist_ok=True)
    os.makedirs(f"{ws}/data_full/A", exist_ok=True)
    m, items = [], []
    for n, (ch, p) in enumerate(pick, 1):
        im = Image.open(img_path(ch, p)).convert("L")
        im = im.resize((round(im.width * SCALE_A), round(im.height * SCALE_A)), Image.LANCZOS)
        a = (np.asarray(im) >= 128).astype(np.uint8) * 255
        Image.fromarray(a).convert("RGB").save(f"{ws}/data_full/A/{n}.png")
        m.append([n, ch, p])
        items.append([img_path(ch, p), f"{ch}:{p}"])
    json.dump({"scale": SCALE_A, "map": m}, open(f"{ws}/map.json", "w"))
    json.dump(items, open(f"{ws}/yolo_items.json", "w"))
    open(f"{ws}/workspace.yaml", "w").write("id: wsA\n")
    open(f"{ws}/books/A.yaml", "w").write(
        "id: A\ntitle: 测试A release 底图\nedition: keben\nraw_dir: data_full/A\n"
        'raw_pattern: "{page}.png"\nexpected_cols: 9\nchars_per_line: 21\nperiod_prior: 115.0\n')
    print(len(m), "页 →", ws)


def cmd_make_ws_b(ws):
    from cmp_md import run
    os.makedirs(f"{ws}/books", exist_ok=True)
    os.makedirs(f"{ws}/data_full", exist_ok=True)
    link = f"{ws}/data_full/zongmu"
    if not os.path.exists(link):
        os.symlink(os.path.abspath(f"{WS96}/data_full/zongmu"), link)
    open(f"{ws}/workspace.yaml", "w").write("id: wsB\n")
    random.seed(7)
    sel, items = {}, []
    for v, chs in (("vol04", [10, 11]), ("vol05", [12, 13])):
        os.system(f'cp "{WS96}/books/{v}.yaml" "{ws}/books/"')
        res = [x for x in run(f"{WS96}/reports/{v}/{v}.md", chs, f"{ws}/cmp_{v}.json")
               if x["score"] >= 0.9 and len(x["theirs"]) >= 8]
        pick = sorted(random.sample(res, 50), key=lambda x: x["our"])
        sel[v] = [[x["our"], x["ch"], x["p"]] for x in pick]
        items += [[f"{WS96}/data_full/zongmu/{v}/{o}.png", f"{v}:{o}"] for o, _, _ in sel[v]]
    json.dump(sel, open(f"{ws}/testB_pages.json", "w"))
    json.dump(items, open(f"{ws}/yolo_items.json", "w"))
    print({v: ",".join(str(o) for o, _, _ in s) for v, s in sel.items()})


def cmd_test_a(ws, yolo_jsonl):
    mp = json.load(open(f"{ws}/map.json"))
    sc = mp["scale"]
    Y = {json.loads(ln)["key"]: json.loads(ln) for ln in open(yolo_jsonl)}
    for thr in (0.5, 0.3):
        R = collections.defaultdict(collections.Counter)
        for n, ch, p in mp["map"]:
            _, P = load_ch(ch)
            bs = boxes(P[p])
            ref = [[b["x0"], b["y0"], b["x1"], b["y1"]] for b in bs]
            truth = their_colcounts(P[p], boxes)
            oc = load_chars(ws, "A", n, _img_w(f"{ws}/data_full/A/{n}.png"))
            y = Y[f"{ch}:{p}"]
            preds = {"ours": ([[v / sc for v in c["box"]] for c in oc], ours_colcounts(oc))}
            for k, clean in (("yolo_raw", False), ("yolo_clean", True)):
                cols = yolo_eval_cols(y, clean)
                preds[k] = ([[x, yy, x + w, yy + h] for x, yy, w, h in
                             (c["xywh"] for col in cols for c in col["chars"])],
                            [len(c["chars"]) for c in cols])
            for k, (pb, cnt) in preds.items():
                tp, fp, fn, _, pairs = match(pb, ref, thr)
                T = R[k]
                T["tp"] += tp; T["fp"] += len(fp); T["fn"] += len(fn)
                hit = {j for _, j, _ in pairs}
                for j, b in enumerate(bs):
                    t = "small" if b["small"] else "big"
                    T["n_" + t] += 1; T["hit_" + t] += j in hit
                if thr == 0.5:
                    a, b_ = compare_counts(cnt, truth)
                    T["col_ok"] += a; T["col_n"] += b_; T["page_ok"] += (a == b_ and len(cnt) == len(truth))
        for k, T in R.items():
            line = (f"IoU>={thr} {k:10s} P {T['tp'] / (T['tp'] + T['fp']):.4f} R {T['tp'] / (T['tp'] + T['fn']):.4f}"
                    f" 正文字召回 {T['hit_big'] / T['n_big']:.4f} 夹注字召回 {T['hit_small'] / T['n_small']:.4f}")
            if thr == 0.5:
                line += f" | 列字数全对 {T['col_ok']}/{T['col_n']}={T['col_ok'] / T['col_n']:.4f} 整页全对 {T['page_ok']}/{len(mp['map'])}"
            print(line)


def cmd_test_b(ws, yolo_jsonl, err_out=None):
    sel = json.load(open(f"{ws}/testB_pages.json"))
    Y = {json.loads(ln)["key"]: json.loads(ln) for ln in open(yolo_jsonl)}
    R = {k: collections.Counter() for k in ("ours", "yolo_raw", "yolo_clean")}
    errs = collections.defaultdict(list)
    for v in sel:
        for o, ch, p in sel[v]:
            _, P = load_ch(ch)
            truth = their_colcounts(P[p], boxes)
            kinds = _col_kinds(P[p])
            oc = load_chars(ws, v, o, _img_w(f"{WS96}/data_full/zongmu/{v}/{o}.png"))
            y = Y[f"{v}:{o}"]
            preds = {"ours": ours_colcounts(oc) if oc is not None else [],
                     "yolo_raw": [len(c["chars"]) for c in yolo_columns(y, drop_mid=False)],
                     "yolo_clean": [len(c["chars"]) for c in yolo_eval_cols(y, True)]}
            for k, pr in preds.items():
                a, b = compare_counts(pr, truth)
                T = R[k]
                T["ok"] += a; T["n"] += b; T["pp"] += (a == b and len(pr) == len(truth))
                for i, t in enumerate(truth):
                    T["n_" + kinds[i]] += 1
                    if i < len(pr) and pr[i] == t:
                        T["ok_" + kinds[i]] += 1
                    elif k != "yolo_raw":
                        errs[k].append((v, o, ch, p, i + 1, pr[i] if i < len(pr) else None, t, kinds[i]))
    for k, T in R.items():
        print(f"{k:10s} 列字数全对 {T['ok']}/{T['n']}={T['ok'] / T['n']:.4f}  正文列 {T['ok_正文列']}/{T['n_正文列']}"
              f"  夹注列 {T['ok_夹注列']}/{T['n_夹注列']}  整页全对 {T['pp']}/100")
    if err_out:
        json.dump(errs, open(err_out, "w"), ensure_ascii=False)


def cmd_prior(ws, err_json):
    """release 列字数 → column-slots 裁决（n_slots = 现格数 − (CV 字数 − release 字数)）。只是实验用的近似。"""
    errs = json.load(open(err_json))["ours"]
    out_dir = f"{ws}/feedback/verdicts/char-segmentation/column-slots"
    os.makedirs(out_dir, exist_ok=True)
    items, pages = [], collections.defaultdict(set)
    for v, o, ch, p, col, pr, t, kind in errs:
        if pr is None or abs(pr - t) > 3:
            continue
        g = json.load(open(f"{ws}/products/{v}/row_segment_gate/p{o:04d}.json"))["row_segment_gate_manifest"]
        nb = next(c for c in g["columns"] if c["col"] == col)["n_body_slots"]
        items.append({"anchor": {"book": v, "page": o, "col": col},
                      "expected": {"n_slots": nb - (pr - t), "note": f"release 列字数 {t}，CV 切出 {pr}"},
                      "history": [{"change": "created", "ts": "2026-10-19T00:00:00Z", "why": "实验：release 列字数先验"}],
                      "id": f"{v}:{o}:{col}", "input": {}, "label_origin": "human", "source_events": [],
                      "status": "active"})
        pages[v].add(o)
    with open(f"{out_dir}/items.jsonl", "w") as f:
        f.write("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items))
    print(len(items), "条；重跑：", {v: ",".join(map(str, sorted(s))) for v, s in pages.items()},
          "→ guji pipeline keben_body_v2 <vol> --from row_segment --to cell_shrink --pages ... --force")


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"dzg": cmd_dzg, "make-ws-a": cmd_make_ws_a, "make-ws-b": cmd_make_ws_b, "test-a": cmd_test_a,
     "test-b": cmd_test_b, "prior": cmd_prior}[cmd](*args)
