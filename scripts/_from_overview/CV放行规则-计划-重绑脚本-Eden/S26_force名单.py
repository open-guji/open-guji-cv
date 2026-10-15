# -*- coding: utf-8 -*-
"""S26 force 名单两情形（GUJI-208jx）。喂 Emi 的 run_window_sampling.sh 的第 3 个参数（force 名单，一行一格，# 注释）。

    python3 -I S26_force名单.py --s23 out --out force.txt [--redline-root <A 臂产物根>]
    python3 -I S26_force名单.py --s23 in  --out force.txt --a-root <hint 开臂产物根> --b-root <hint 关臂产物根>
                                [--redline-root <窗口 A 臂产物根>] [--hint-list …完整.tsv] [--cells27 …完整对位.tsv]
    python3 -I S26_force名单.py --selftest
    （v2.16 起，两种情形都可加）--base-table <基线表 jsonl[.gz]> --arm-table-dir <A 臂表目录>  [--hold-tsv <输出 tsv>] [--delivered-table <交付态基线表 jsonl[.gz]>]  [--expect-context-tsv/--expect-iron-tsv <核对用 tsv>]

--s23 out：S23 不进甲。force＝红线十格（208lw 起；原九格＋vol05:108:2:20）；hint 相关格不进，只在 stdout 与名单注释里写「hint 相关格按基线算」。
--s23 in ：S23 进甲。force＝红线十格 ∪ hint 正式名单（vol05 46＋vol07 4，hint 开臂格号；去重后 10＋50−1＝59 行，与红线重叠 1 格 vol05:154:8:21）；并对 27 个改号格跑 hint_remap_27.py
            产出 remap.tsv（只对这 27 格，喂 sample_newadmit.py --remap）。--a-root／--b-root 缺失或没有对应页 → 报「待产物」，
            **不写名单、不猜**（退出码 5）。整页对位不在此跑，stdout 给出 rebind_lookups.py 的命令行。
context-hold／iron-hold（208me，剧本 v2.16；Ezio 208lz、Mila 决定页 §一〇一、§九十八）：给了 --base-table 与 --arm-table-dir，就按 Ethan 208lt cmp.py 的口径
            （A 臂该格 admit 且基线同号非 admit，A 臂 channel＝context→context-hold、＝iron→iron-hold）算出这两类格，一律进 force 名单（强制待审，
            不论看图判对错，只测不放）。**它们不是红线**：红线＝已确认错放的 id 硬编码（REDLINE，十格不变）；hold 是窗口当日现算的，
            不并入 REDLINE。基线里没有的格号（无对位）不入 hold，只计数提示（对位交给 remap／sample_newadmit 的无对位阈值）。
            v2.16.1（Mila 208mh）：hold 的「基线」取并集——--base-table＝同次 A-g0 零臂表，--delivered-table＝交付态基线 4324e4b 表（可选；
            给了就两边各算一遍取并：对任一边新放行的格都进 hold，红线低方向多挡不放），每格标「两者皆新／仅交付态新／仅零臂新」，仅一边新的单列。
            --hold-tsv 写出明细（类、格号、A 臂字、基线字、基线状态、是否也在红线），供报告单列「context-hold 格数／其中已看图判错 N」（N 由 Ezio 看图填，脚本不判）。
            --expect-*-tsv 用 Ethan 的 context／iron tsv（208lt附/）核对：算出的集合应与 tsv 的「格号」列相同，多／漏都列出并退出码 3（彩排用）。
--redline-root：给了就核红线十格是否都在该产物根里找得到（cell_shrink 页 json）；找不到 → 退出码 3，名单仍写但标注。
退出码：0 成功｜3 红线格找不到｜5 待产物｜2 参数错。不碰 products／事件／字形库，只读产物、只写 --out 与 --out-dir。
"""
import argparse, subprocess, sys, tempfile, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rebind_lookups as R

PLAN = HERE.parent
REDLINE = ["vol02:15:9:20", "vol02:188:4:20", "vol05:154:8:21", "vol06:149:1:21", "vol04:217:2:15",   # 五格
           "vol06:18:9:21", "vol04:220:4:4", "vol04:23:1:3", "vol04:79:7:11",                          # 另四格，合称九格
           "vol05:108:2:20"]                                                                           # 红线十（Ezio 208lu 看图：「人」是错放、原字輕；Ethan 208lt 更正：iron 通道在基线／终头代码、main yaml 下都放行，基线为何待审成因待查；Mila 决定页 §九十四、§九十五）
DEFAULT_HINT = PLAN / "hint名单-vol05-vol07-Eden-完整.tsv"
DEFAULT_C27 = PLAN / "hint名单-remap表-Eden-完整对位.tsv"


def read_ids(path, col=0):
    out = []
    for l in open(path, encoding="utf-8"):
        if l.startswith("#") or not l.strip() or l.startswith(("新格号", "A格号")):
            continue
        c = l.rstrip("\n").split("\t")[col].strip()
        if c.startswith("vol"):
            out.append(c)
    return out


def load_cell_rows(path):
    """cell table（jsonl 或 jsonl.gz；首行 header 跳过）→ {id: row}。只读。"""
    import gzip
    p = Path(path); op = (lambda: gzip.open(p, "rt", encoding="utf-8")) if p.name.endswith(".gz") else (lambda: open(p, encoding="utf-8"))
    out = {}
    with op() as f:
        for l in f:
            l = l.strip()
            if not l:
                continue
            r = json.loads(l)
            if r.get("header") or "id" not in r:
                continue
            out[r["id"]] = r
    return out


def load_cell_dir(d):
    out = {}
    for f in sorted(Path(d).glob("*.jsonl")) + sorted(Path(d).glob("*.jsonl.gz")):
        out.update(load_cell_rows(f))
    return out


def compute_holds(base, arm):
    """→ (context_hold, iron_hold, 无对位)，口径同 208lt cmp.py：A 放行且基线非放行，按 A 臂 channel 分类。"""
    ctx, iron, nobase = [], [], []
    for cid, r in arm.items():
        if not r.get("admit"):
            continue
        ch = r.get("channel")
        if ch not in ("context", "iron"):
            continue
        b = base.get(cid)
        if b is None:
            nobase.append((cid, ch)); continue
        if b.get("admit"):
            continue
        (ctx if ch == "context" else iron).append(cid)
    key = lambda c: (c.split(":")[0], int(c.split(":")[1]), int(c.split(":")[2]), c.split(":")[3])
    return sorted(ctx, key=key), sorted(iron, key=key), sorted(nobase)


def read_tsv_ids(path):
    out = []
    for l in open(path, encoding="utf-8"):
        if l.startswith("册") or not l.strip():
            continue
        c = l.split("\t")[1].strip()
        if c.startswith("vol"):
            out.append(c)
    return out


def tables(root, ids):
    cache, miss_page = {}, set()
    for i in ids:
        bk = i.split(":")[0]
        if bk not in cache:
            cache[bk] = R.load_table(str(root), bk) if Path(root, bk).is_dir() else {}
    return cache


def present(root, ids):
    """→ (找到的, 缺的, 缺页的)"""
    t = tables(root, ids); ok, miss, nopage = [], [], []
    for i in ids:
        bk, p = i.split(":")[0], int(i.split(":")[1])
        if p not in t[bk]:
            nopage.append(i)
        elif i in t[bk][p]:
            ok.append(i)
        else:
            miss.append(i)
    return ok, miss, nopage


def run(a):
    out = Path(a.out); lines = ["# S26 force 名单（S26_force名单.py --s23 %s）；一行一格，# 为注释" % a.s23,
                                 "# 红线十格（九格：Ezio 208gd／Ezra 检查表 §二；第十格 vol05:108:2:20：Ezio 208lu、Ethan 208lt 再补二）"] + REDLINE
    rc = 0
    if a.redline_root:
        ok, miss, nopage = present(a.redline_root, REDLINE)
        print(f"红线十格核对（{a.redline_root}）：找到 {len(ok)}／{len(REDLINE)}；缺格 {miss or '无'}；缺页 {nopage or '无'}")
        if miss or nopage:
            rc = 3
            lines.append("# ⚠ 红线格找不到：%s —— 按位置追格，不能当作待审" % ",".join(miss + nopage))
    else:
        print("红线十格：未核（没给 --redline-root）")
    if a.s23 == "out":
        lines.append("# hint 相关格按基线算（S23 不进甲，不强制进看图清单）")
        print("hint 相关格按基线算")
    else:
        if not (a.a_root and a.b_root and Path(a.a_root).is_dir() and Path(a.b_root).is_dir()):
            print("待产物：S23 进甲需要 --a-root（hint 开臂）与 --b-root（hint 关臂）两个产物根；缺则不写名单、不猜。"); return 5
        hint = read_ids(a.hint_list); c27 = read_ids(a.cells27)
        need = sorted(set(hint) | set(c27))
        okA, missA, nopA = present(a.a_root, need)
        if nopA:
            print(f"待产物：hint 开臂缺 {len(nopA)} 个格所在的页（例 {nopA[:3]}）；不写名单。"); return 5
        if missA:
            print(f"提示：hint 开臂产物里没有这些格（名单是 A 格号，应都在）：{missA[:5]}…"); lines.append("# ⚠ hint 开臂没有：" + ",".join(missA))
        od = Path(a.out_dir or (out.parent / (out.stem + "_remap"))); od.mkdir(parents=True, exist_ok=True)
        cf = od / "cells27.txt"; cf.write_text("\n".join(c27), encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(HERE / "hint_remap_27.py"), "--a", a.a_root, "--b", a.b_root,
                            "--cells", str(cf), "--out-dir", str(od)], capture_output=True, text=True)
        if r.returncode != 0:
            print("hint_remap_27.py 失败：", r.stderr[-400:]); return 5
        summ = json.loads((od / "摘要.json").read_text(encoding="utf-8"))
        lines.append("# hint 正式名单（hint 开臂格号，vol05 %d＋vol07 %d）" % (sum(x.startswith("vol05") for x in hint), sum(x.startswith("vol07") for x in hint)))
        lines += [h for h in hint if h not in REDLINE]
        print(f"hint 名单 {len(hint)} 格；27 格 remap：{summ['by_status']}；remap.tsv＝{od/'remap.tsv'}（只喂这 27 格）")
        print("整页对位（不在此跑）：python3 重绑脚本-Eden/rebind_lookups.py --old <B 根> --new <A 根> --book volNN --lookups … --out-dir …")
    have_hold = bool(getattr(a, "base_table", None) and getattr(a, "arm_table_dir", None))
    if have_hold:
        base = load_cell_rows(a.base_table); arm = load_cell_dir(a.arm_table_dir)
        if not base or not arm:
            print("待产物：--base-table 或 --arm-table-dir 里读不到格（空表）；不写名单、不猜。"); return 5
        ctx, iron, nobase = compute_holds(base, arm)
        src = {c: "仅零臂新" for c in ctx + iron}          # 每格相对哪个基线新放行
        if getattr(a, "delivered_table", None):
            dbase = load_cell_rows(a.delivered_table)
            if not dbase:
                print("待产物：--delivered-table 读不到格（空表）；不写名单、不猜。"); return 5
            dctx, diron, dnobase = compute_holds(dbase, arm)
            for c in dctx + diron:
                src[c] = "两者皆新" if c in src else "仅交付态新"
            ctx = sorted(set(ctx) | set(dctx), key=lambda c: (c.split(":")[0], int(c.split(":")[1]), int(c.split(":")[2]), c.split(":")[3]))
            iron = sorted(set(iron) | set(diron), key=lambda c: (c.split(":")[0], int(c.split(":")[1]), int(c.split(":")[2]), c.split(":")[3]))
            nobase = sorted(set(nobase) & set(dnobase))     # 两边都没有的才算无对位
            one = sorted(c for c, t in src.items() if t != "两者皆新")
            from collections import Counter
            print(f"hold 基线取并集：两者皆新 {sum(1 for t in src.values() if t == '两者皆新')}｜仅交付态新 {sum(1 for t in src.values() if t == '仅交付态新')}｜仅零臂新 {sum(1 for t in src.values() if t == '仅零臂新')}")
            print("  仅一边新的格（单列）：", {c: src[c] for c in one} or "无")
        print(f"context-hold {len(ctx)} 格｜iron-hold {len(iron)} 格｜A 臂放行的 context／iron 格里基线无对位 {len(nobase)} 格（不入 hold，交 remap／无对位阈值）")
        if nobase:
            print("  无对位例：", nobase[:5])
        for tag, ids in (("context-hold", ctx), ("iron-hold", iron)):
            lines.append(f"# {tag}（窗口当日现算；A 臂放行而基线非放行、通道＝{tag.split('-')[0]}；强制待审、只测不放；不是红线）")
            lines += [f"{c}  # {tag}" + (f"；{src[c]}" if getattr(a, "delivered_table", None) else "") for c in ids if c not in REDLINE]
        if getattr(a, "hold_tsv", None):
            rows = ["类\t格号\tA臂字\t基线字\t基线状态\t也在红线\t新放行相对于"]
            for tag, ids in (("context-hold", ctx), ("iron-hold", iron)):
                for c in ids:
                    rows.append("\t".join([tag, c, str(arm[c].get("char", "")), str(base.get(c, {}).get("char", "")), "放行" if base.get(c, {}).get("admit") else "待审", "是" if c in REDLINE else "否", src.get(c, "")]))
            Path(a.hold_tsv).write_text("\n".join(rows) + "\n", encoding="utf-8")
            print(f"hold 明细 → {a.hold_tsv}")
        for tag, ids, exp in (("context", ctx, getattr(a, "expect_context_tsv", None)), ("iron", iron, getattr(a, "expect_iron_tsv", None))):
            if exp:
                want = set(read_tsv_ids(exp)); got = set(ids)
                miss, extra = sorted(want - got), sorted(got - want)
                print(f"核对 {tag} tsv（{exp}）：期望 {len(want)} 格，算出 {len(got)} 格；漏 {miss or '无'}；多 {extra or '无'}")
                if miss or extra:
                    rc = 3
                    lines.append(f"# ⚠ {tag}-hold 与期望 tsv 不符：漏 {','.join(miss) or '无'}；多 {','.join(extra) or '无'}")
    else:
        print("context-hold／iron-hold：未算（没给 --base-table 与 --arm-table-dir）；窗口当日 S26 必须给，否则这两类格不进 force 名单")
        lines.append("# ⚠ context-hold／iron-hold 未算（没给 --base-table／--arm-table-dir）")
    seen, final, seen_ids = set(), [], set()
    for l in lines:
        if l.startswith("#"):
            final.append(l); continue
        cid = l.split("#", 1)[0].strip()
        if cid and cid not in seen_ids:
            final.append(l); seen_ids.add(cid)
    out.write_text("\n".join(final) + "\n", encoding="utf-8")
    n = sum(1 for l in final if l and not l.startswith("#"))
    print(f"force 名单 {n} 行 → {out}")
    return rc


def selftest():
    def root(d, cells):
        for bk, pg, ids in cells:
            p = Path(d, bk, "cell_shrink"); p.mkdir(parents=True, exist_ok=True)
            (p / f"p{pg:04d}.json").write_text(json.dumps({"x": {"columns": [{"chars": [{"id": i, "bbox": b} for i, b in ids.items()]}]}}), encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # 红线根：十格各一页
        rl = [(i.split(":")[0], int(i.split(":")[1]), {i: [0, 0, 10, 10]}) for i in REDLINE]
        root(td / "rl", rl)
        # hint 臂 A／B：vol05 p1 两格（一个同号、一个改号），vol07 p2 一格
        A = [("vol05", 1, {"vol05:1:1:5": [0, 0, 10, 10], "vol05:1:1:6": [0, 20, 10, 30]}), ("vol07", 2, {"vol07:2:3:1": [0, 0, 10, 10]})]
        B = [("vol05", 1, {"vol05:1:1:5": [0, 0, 10, 10], "vol05:1:1:5b": [0, 20, 10, 30]}), ("vol07", 2, {"vol07:2:3:1": [0, 0, 10, 10]})]
        root(td / "A", A); root(td / "B", B)
        (td / "hint.tsv").write_text("新格号\n" + "\n".join(["vol05:1:1:5", "vol05:1:1:6", "vol07:2:3:1"]) + "\n", encoding="utf-8")
        (td / "c27.tsv").write_text("A格号\n" + "\n".join(["vol05:1:1:5", "vol05:1:1:6", "vol07:2:3:1"]) + "\n", encoding="utf-8")
        ns = lambda **k: argparse.Namespace(**{**dict(s23="out", out=str(td / "f.txt"), a_root=None, b_root=None, out_dir=None, redline_root=None,
                                                         hint_list=str(td / "hint.tsv"), cells27=str(td / "c27.tsv")), **k})
        assert run(ns(redline_root=str(td / "rl"))) == 0
        o = [l for l in (td / "f.txt").read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
        assert o == REDLINE, o
        assert run(ns(s23="in")) == 5 and True                                             # 缺产物：待产物
        assert run(ns(s23="in", a_root=str(td / "A"), b_root=str(td / "B"), redline_root=str(td / "rl"))) == 0
        o = [l for l in (td / "f.txt").read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
        assert o[:len(REDLINE)] == REDLINE and o[len(REDLINE):] == ["vol05:1:1:5", "vol05:1:1:6", "vol07:2:3:1"], o
        assert (td / "f_remap" / "remap.tsv").exists()
        root(td / "rl2", rl[:-1])                                                            # 少一格红线 → 退出码 3
        assert run(ns(redline_root=str(td / "rl2"))) == 3
    # —— v2.16：context-hold／iron-hold（彩排用 Ethan 208lt 的 v2 tsv：context 21 格、iron 6 格，应一格不漏）——
    import gzip
    ctx_tsv, iron_tsv = PLAN / "208lt附" / "context_new_admit_all_vols.tsv", PLAN / "208lt附" / "iron_new_admit_all_vols.tsv"
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        if ctx_tsv.exists() and iron_tsv.exists():
            C, I = read_tsv_ids(ctx_tsv), read_tsv_ids(iron_tsv)
        else:
            C = [f"vol02:{n}:1:1" for n in range(1, 22)]; I = ["vol05:108:2:20", "vol05:23:7:21"]
        assert len(C) == 21 and len(I) == 6 and "vol05:108:2:20" in I, (len(C), len(I))
        def w(path, rows):
            with gzip.open(path, "wt", encoding="utf-8") as f:
                f.write(json.dumps({"header": True}) + "\n")
                for cid, adm, ch in rows:
                    f.write(json.dumps({"id": cid, "admit": adm, "channel": ch, "char": "字"}) + "\n")
        arm_rows = [(c, True, "context") for c in C] + [(c, True, "iron") for c in I]
        arm_rows += [("vol06:1:1:1", True, "context"), ("vol06:1:1:2", False, "context"), ("vol06:1:1:3", True, "match_ref"),   # 基线已放行／A 未放行／别的通道：都不是 hold
                     ("vol06:1:1:4", True, "context"), ("vol06:1:1:5", True, "iron")]                                         # 基线没有这两格：无对位，不入 hold
        base_rows = [(c, False, "none") for c in C + I] + [("vol06:1:1:1", True, "context"), ("vol06:1:1:2", False, "x"), ("vol06:1:1:3", False, "x")]
        rl = [(i.split(":")[0], int(i.split(":")[1]), {i: [0, 0, 10, 10]}) for i in REDLINE]
        for bk, pg, idd in rl:
            pp = Path(td, "rl", bk, "cell_shrink"); pp.mkdir(parents=True, exist_ok=True)
            (pp / f"p{pg:04d}.json").write_text(json.dumps({"x": {"columns": [{"chars": [{"id": i, "bbox": b} for i, b in idd.items()]}]}}), encoding="utf-8")
        ns = lambda **kk: argparse.Namespace(**{**dict(s23="out", out=str(td / "f.txt"), a_root=None, b_root=None, out_dir=None, redline_root=None,
                                                          hint_list=None, cells27=None, base_table=None, arm_table_dir=None, hold_tsv=None,
                                                          expect_context_tsv=None, expect_iron_tsv=None), **kk})
        (td / "arm").mkdir(); w(td / "arm" / "vol_all_A.jsonl.gz", arm_rows); w(td / "base.jsonl.gz", base_rows)
        k = dict(base_table=str(td / "base.jsonl.gz"), arm_table_dir=str(td / "arm"), hold_tsv=str(td / "h.tsv"),
                 expect_context_tsv=str(ctx_tsv) if ctx_tsv.exists() else None, expect_iron_tsv=str(iron_tsv) if iron_tsv.exists() else None)
        assert run(ns(redline_root=str(td / "rl"), **k)) == 0
        lines = (td / "f.txt").read_text(encoding="utf-8").splitlines()
        ids = [l.split("#", 1)[0].strip() for l in lines if l and not l.startswith("#")]
        assert len(ids) == len(set(ids)), "force 名单有重复格号"
        assert ids[:len(REDLINE)] == REDLINE and set(ids[len(REDLINE):]) == set(C) | (set(I) - set(REDLINE)), ids
        assert "vol06:1:1:1" not in ids and "vol06:1:1:4" not in ids and "vol06:1:1:5" not in ids
        hold = (td / "h.tsv").read_text(encoding="utf-8").splitlines()
        assert len(hold) == 1 + 21 + 6 and any("vol05:108:2:20" in l and l.split("\t")[5] == "是" for l in hold), hold
        # 期望 tsv 少一格 → 退出码 3；红线十不变
        short = td / "short.tsv"; short.write_text("册\t格号\n" + "\n".join("vol\t" + c for c in C[:-1]) + "\n", encoding="utf-8")
        assert run(ns(redline_root=str(td / "rl"), **{**k, "expect_context_tsv": str(short)})) == 3
        # —— v2.16.1 并集：交付态表＝上面的 base（C、I 都待审）；零臂表里 C 的前 3 格已是放行（只对交付态新）、另加一格只对零臂新 ——
        w(td / "zero.jsonl.gz", [(c, c in set(C[:3]), "x") for c in C + I] + [("vol06:1:1:1", True, "context"), ("vol06:1:1:2", False, "x"), ("vol06:1:1:3", False, "x"),
                                                                           ("vol09:1:1:1", False, "x")])
        arm2 = [(c, True, "context") for c in C] + [(c, True, "iron") for c in I] + [("vol09:1:1:1", True, "context")]      # vol09:1:1:1：零臂待审、交付态表里没有
        (td / "arm2").mkdir(); w(td / "arm2" / "vol_all_A.jsonl.gz", arm2)
        k2 = dict(base_table=str(td / "zero.jsonl.gz"), delivered_table=str(td / "base.jsonl.gz"), arm_table_dir=str(td / "arm2"), hold_tsv=str(td / "h2.tsv"))
        assert run(ns(redline_root=str(td / "rl"), **k2)) == 0
        h2 = {l.split("\t")[1]: l.split("\t")[6] for l in (td / "h2.tsv").read_text(encoding="utf-8").splitlines()[1:]}
        assert set(h2) == set(C) | set(I) | {"vol09:1:1:1"}, sorted(set(h2) ^ (set(C) | set(I) | {"vol09:1:1:1"}))
        assert all(h2[c] == "仅交付态新" for c in C[:3]) and h2["vol09:1:1:1"] == "仅零臂新" and all(h2[c] == "两者皆新" for c in C[3:] + I), h2
        (td / "emptyarm").mkdir()
        assert run(ns(base_table=str(td / "base.jsonl.gz"), arm_table_dir=str(td / "emptyarm"))) == 5                    # 空目录＝待产物
    print("S26_force名单 自测通过：out＝十格；in 缺产物＝待产物(5)；in 有产物＝十格＋hint 名单＋remap；红线缺格＝退出码 3；context-hold 21＋iron-hold 6 一格不漏、无对位不入、与红线去重")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--s23", choices=["in", "out"]); ap.add_argument("--out"); ap.add_argument("--out-dir")
    ap.add_argument("--a-root"); ap.add_argument("--b-root"); ap.add_argument("--redline-root")
    ap.add_argument("--hint-list", default=str(DEFAULT_HINT)); ap.add_argument("--cells27", default=str(DEFAULT_C27))
    ap.add_argument("--delivered-table"); ap.add_argument("--base-table"); ap.add_argument("--arm-table-dir"); ap.add_argument("--hold-tsv")
    ap.add_argument("--expect-context-tsv"); ap.add_argument("--expect-iron-tsv")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest(); sys.exit(0)
    if not a.s23 or not a.out:
        ap.error("需要 --s23 与 --out"); 
    sys.exit(run(a))
