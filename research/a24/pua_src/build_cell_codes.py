"""全册格→私用码对应（`src-2` 裁定，seed_admit `pua_code_table` 的输入；A24 2026-11-06，A31 X01 派单）。

对每个册的每页：产物页 seed_admit 的格序列（reading 顺序）与新图源文本层 `text.jsonl.gz` 做 SequenceMatcher 对位，
文本层里是私用码（U+F0000 以上、码在码表或待收登记里都记）的位置，若对到我们的某一格（equal，或等长 replace）且左右各 2 格内
锚点（字相同）≥3、整页相似度 ≥0.85，出一条 `src-2`：{cell, code, ref（该格整理本对位字）, anch, page_match}。
不依赖现放行字是什么，也不依赖前后文窗口。

用法：python build_cell_codes.py <册…|all> --out <dir> [--pack-root DIR]
 需要：GUJI_DATA_TOKEN_READ、`guji`、新图源包 q.zip（环境变量 Q_ZIP）、页对应 pagemap_all.json.gz（环境变量 PAGEMAP）、工作区 WS。
 输出：<dir>/cell_codes-<册>.jsonl（一行一格 payload），再用 `--to-events` 转成裁定事件放进 feedback/rulings/（由 A31 推库）。
"""
import argparse, collections, difflib, gzip, io, json, os, shutil, subprocess, sys, zipfile

PUA15 = lambda ch: ord(ch) >= 0xF0000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vols", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pack-root", default="")
    ap.add_argument("--min-anch", type=int, default=3)
    ap.add_argument("--min-match", type=float, default=0.85)
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from open_guji_cv.utils.jiazhu_order import sort_by_reading
    from types import SimpleNamespace as NS
    WS, GUJI = os.environ["WS"], os.environ.get("GUJI", "guji")
    Z = zipfile.ZipFile(os.environ["Q_ZIP"])
    pm = json.load(gzip.open(os.environ["PAGEMAP"], "rt"))
    env = dict(os.environ, GUJI_DATA_TOKEN=os.environ["GUJI_DATA_TOKEN_READ"], GUJI_CORPUS_DRIFT="warn")
    os.makedirs(a.out, exist_ok=True)
    vols = sorted(pm) if a.vols == ["all"] else a.vols

    def tdata(book):
        return {json.loads(l)["p"]: json.loads(l) for l in gzip.open(io.BytesIO(Z.read(f"96mid1ogzk/{book}/text.jsonl.gz")), "rt")}

    for v in vols:
        out = f"{a.out}/cell_codes-{v}.jsonl"
        if os.path.exists(out):
            continue
        tmp = None if a.pack_root else f"{a.out}/_tmp_{v}"        # 给了 --pack-root 就把包留在那里（回放要复用）
        dest = f"{a.pack_root}/{v}" if a.pack_root else tmp
        if not os.path.isdir(dest):
            lab = subprocess.run([GUJI, "products", "pack", "list", v, "-w", WS], capture_output=True, text=True, env=env).stdout
            l = [x for x in lab.splitlines() if x.startswith("★")][0].split("\t")[0].split("/")[-1]
            subprocess.run([GUJI, "products", "pack", "fetch", v, "-w", WS, "--label", l, "--to", dest], capture_output=True, env=env)
        P = f"{dest}/{v}" if os.path.isdir(f"{dest}/{v}") else dest
        L = lambda k, p: json.load(open(f"{P}/{k}/p{p:04d}.json"))
        T, res = {}, []
        for pg in pm[v]:
            if pg.get("status") != "ok":
                continue
            p = pg["our"]
            try:
                cells = [c for col in L("seed_admit", p)["seed_admit"]["columns"] for c in col["chars"]]
            except FileNotFoundError:
                continue
            g = pg["their"]
            if g[0] not in T:
                T[g[0]] = tdata(g[0])
            ours = "".join((c.get("char") or "□") for c in cells)
            best = None
            for dp in range(-3, 4):
                if g[1] + dp in T[g[0]]:
                    r = difflib.SequenceMatcher(None, ours, T[g[0]][g[1] + dp]["c"], autojunk=False).ratio()
                    if best is None or r > best[0]:
                        best = (r, g[1] + dp)
            if not best or best[0] < a.min_match:
                continue
            Tt = T[g[0]][best[1]]["c"]
            try:
                ar = {c["id"]: c["align_char"] for c in L("align_ref", p)["align_ref"]["chars"]}
            except Exception:
                ar = {}
            sm = difflib.SequenceMatcher(None, ours, Tt, autojunk=False)
            for tag, a0, a1, b0, b1 in sm.get_opcodes():
                if not (tag == "equal" or (a1 - a0) == (b1 - b0)):
                    continue
                for j in range(b0, b1):
                    if not PUA15(Tt[j]):
                        continue
                    k = a0 + j - b0
                    anch = sum(1 for d in (-2, -1, 1, 2) if 0 <= k + d < len(ours) and 0 <= j + d < len(Tt) and ours[k + d] == Tt[j + d])
                    if anch < a.min_anch:
                        continue
                    res.append(dict(cell=cells[k]["id"], code="%X" % ord(Tt[j]), ref=ar.get(cells[k]["id"], ""), anch=anch,
                                    page_match=round(best[0], 3), src=Tt[j], cur=cells[k].get("char"), admit=cells[k].get("admit"),
                                    channel=cells[k].get("channel")))
        with open(out, "w") as f:
            for r in res:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(v, len(res), "cells")
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
