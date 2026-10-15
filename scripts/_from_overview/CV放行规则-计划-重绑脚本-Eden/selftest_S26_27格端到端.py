# -*- coding: utf-8 -*-
"""GUJI-208kh：27 格真 id＋真框（取自 hint名单-remap表-Eden-完整对位.tsv）造 hint 开臂(A)／关臂(B) 两根，
走 S26_force名单.py --s23 in → remap.tsv，再造 cell table 喂 Emi 的 sample_newadmit.py --remap／--force-all，
验 27 格是否都按 A 臂号被抽到。python3 -I selftest_S26_27格端到端.py   （不碰真书、产物、事件）"""
import csv, json, subprocess, sys, tempfile, gzip
from pathlib import Path
HERE = Path(__file__).resolve().parent; PLAN = HERE.parent
rows = list(csv.reader(open(PLAN / "hint名单-remap表-Eden-完整对位.tsv", encoding="utf-8"), delimiter="\t"))[1:]
def box(s): return [float(x) for x in s.strip("[]").split(",")] if s.strip() else None
A27 = {r[0]: box(r[5]) for r in rows}                                   # A 格号→A 框
PAIR = {r[0]: (r[2], box(r[4])) for r in rows if r[1].startswith("一对一")}   # A 格号→(B 旧号, B 框)
assert len(A27) == 27, len(A27)
HINT = [l.split('\t')[0] for l in open(PLAN / 'hint名单-vol05-vol07-Eden-完整.tsv', encoding='utf-8').read().splitlines()[1:] if l.startswith('vol')]
assert len(HINT) == 50

def write_root(root, cells):
    pages = {}
    for cid, b in cells.items():
        bk, pg = cid.split(":")[:2]; pages.setdefault((bk, int(pg)), {})[cid] = b
    for (bk, pg), ids in pages.items():
        d = Path(root, bk, "cell_shrink"); d.mkdir(parents=True, exist_ok=True)
        (d / f"p{pg:04d}.json").write_text(json.dumps({"x": {"columns": [{"chars": [{"id": i, "bbox": b} for i, b in ids.items()]}]}}), encoding="utf-8")

def run(mode):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        Acells = dict(A27); Bcells = {old: bb for a, (old, bb) in PAIR.items()}
        # 链式：B 54:7:19／96:7:11 占着 A 的号（真数据里它们是别的真实格，放行）；A 里它们的位置是 7:20／7:12
        Acells["vol05:54:7:20"] = [1556.06, 2486.41, 1678.79, 2608.2]; Bcells["vol05:54:7:19"] = [1556.06, 2486.41, 1678.79, 2592.64]
        Acells["vol05:96:7:12"] = [1513.72, 1601.94, 1626.49, 1700.26]; Bcells["vol05:96:7:11"] = [1513.72, 1601.94, 1626.49, 1700.26]
        Bcells["vol05:78:1:19"] = [5000, 5000, 5100, 5100]                    # B 78:1:19 在 A 里无对应
        for k, h in enumerate(x for x in HINT if x not in A27):             # 名单里另 23 个未改号页的格：A／B 同号同框（合成框）
            bx = [10.0 * k, 10.0, 10.0 * k + 8, 18.0]; Acells[h] = bx; Bcells[h] = bx
        write_root(td / "A", Acells); write_root(td / "B", Bcells)
        force = td / "force.txt"
        r = subprocess.run([sys.executable, "-I", str(HERE / "S26_force名单.py"), "--s23", "in", "--out", str(force),
                            "--a-root", str(td / "A"), "--b-root", str(td / "B")], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        remap = td / "force_remap" / "remap.tsv"
        rm = dict(l.split("\t") for l in remap.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#"))
        # cell table：基线＝B 号（hint 关），臂＝A 号（hint 开）；填充 400 个同号放行格撑起 5% 线（=20）
        fill = {f"vol05:900:1:{i}": 1 for i in range(1, 401)}
        def tbl(path, rowsd):
            with gzip.open(path, "wt", encoding="utf-8") as f:
                f.write(json.dumps({"header": True}) + "\n")
                for cid, (adm, prov) in rowsd.items():
                    f.write(json.dumps({"id": cid, "admit": adm, "char": "字", "channel": "match_ref", "provenance": prov}) + "\n")
        base = {cid: (True, "match") for cid in fill}; arm = {cid: (True, "match") for cid in fill}
        for cid in Bcells: base[cid] = (cid in ("vol05:54:7:19", "vol05:96:7:11"), "match")   # 基线：两个被占号是放行，其余待审
        for cid in Acells:
            arm[cid] = (cid in A27 or cid in HINT, "match")
        arm["vol05:154:8:21"] = (mode == "red_open", "match")                   # 红线格：真数据里 hint 开臂放行
        base["vol05:108:2:20"] = (False, "match"); arm["vol05:108:2:20"] = (False, "match")   # 红线十（208lw 加；208lx 起 sample_newadmit 红线十格）：基线、A 臂都待审，本自测只要它在表里找得到
        for p in ("base", "arm"): pass
        tbl(td / "base.jsonl.gz", base); tbl(td / "arm.jsonl.gz", arm)
        out = td / "out"
        s = subprocess.run([sys.executable, "-I", str(HERE.parent / "抽样脚本-Emi" / "sample_newadmit.py"), "--base", str(td / "base.jsonl.gz"),
                            "--arm", str(td / "arm.jsonl.gz"), "--out", str(out), "--remap", str(remap), "--force-all", str(force)],
                           capture_output=True, text=True)
        cells = [l.split("#")[0].strip() for l in (out / "cells.txt").read_text(encoding="utf-8").splitlines()] if (out / "cells.txt").exists() else []
        return s.returncode, s.stderr[-300:], cells, rm, r.stdout

# 1) 真数据口径：154:8:21 在 hint 开臂放行（名单里就是 A 放行）→ 红线停线
rc, err, cells, rm, so = run("red_open")
print("口径1 hint 开臂 154:8:21 放行：rc=", rc, "|", err.strip().splitlines()[-1] if err.strip() else "")
assert rc == 3 and "154:8:21" in err
# 2) 若 154:8:21 在 hint 开臂仍待审（不放行）：27 格应都被抽到（其余 26 格是新放行；154:8:21 本身不是新放行）
rc, err, cells, rm, so = run("red_closed")
print("口径2 154:8:21 待审：rc=", rc, "| 看图清单", len(cells), "格")
assert rc == 0, err
need = set(HINT) - {"vol05:154:8:21"}
miss = sorted(need - set(cells))
n27 = set(A27) - {"vol05:154:8:21"}
print("27 个改号格里被抽到：%d／%d（154:8:21 红线待审、不算新放行）；漏：%s" % (len(n27 & set(cells)), len(n27), sorted(n27 - set(cells)) or "无"))
print("hint 名单 50 格里被抽到：%d／%d" % (len(need & set(cells)), len(need)))
print("remap：旧→新", {k: v for k, v in rm.items() if k != v}.__len__(), "条改号／补行；方向＝旧(B hint 关)→新(A hint 开)，与 sample_newadmit.apply_remap 用法一致")
assert not miss
print("端到端自测通过")
