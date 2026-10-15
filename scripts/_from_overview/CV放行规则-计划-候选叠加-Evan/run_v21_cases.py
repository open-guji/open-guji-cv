# -*- coding: utf-8 -*-
"""GUJI-208kl「再补一」：v2 → v2.1 四项小修的最小情形前后对照（对应 Elena 208kn 的 H1b／H2d／H4col／H4page／H4c／H5d／H5e）。纯自造数据。
用法：python run_v21_cases.py <输出目录> <v2旧脚本目录> <v2.1脚本目录> <make_mini_roots.py所在目录>"""
import copy, json, shutil, subprocess, sys
from pathlib import Path

out, old, new, mdir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
sys.path.insert(0, mdir)
import make_mini_roots as M
shutil.rmtree(out, ignore_errors=True)
P = "vol04/seed_admit/p0001.json"
BY = "shadow_veto"


def run(d, tool, B, N, books, *flags):
    name = {"w5": "w5_demoted_diff_v2.py", "cmp": "compare_seed_admit_products_v2.py"}[tool]
    p = subprocess.run([sys.executable, "-I", str(d / name), B, N, *books, *flags], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)


def mk(name, mut_base=None, mut_new=None, raw_new=None):
    r = out / name
    for side in ("base", "new"):
        M.write(r / side, M.base_tree())
    for side, mut in (("base", mut_base), ("new", mut_new)):
        if mut:
            f = r / side / P
            o = json.loads(f.read_text("utf-8")); mut(o); f.write_text(json.dumps(o, ensure_ascii=False), "utf-8")
    if raw_new:
        raw_new(r)
    return r


def cells(o):
    return [c for col in o["seed_admit"]["columns"] for c in col["chars"]]


def demote(o, by=BY):
    c = cells(o)[0]; c["admit"] = False; c["channel"] = None; c["char"] = None
    return c


def with_dm(o, by=BY):
    demote(o); cells(o)[0]["evidence"]["demoted_from"] = {"channel": "match_ref", "by": by}


def col_ev(o):
    o["seed_admit"]["columns"][0]["evidence"] = {"demoted_from": {"channel": "m", "by": BY}}


def base_col_ev(o):
    o["seed_admit"]["columns"][0]["evidence"] = {}


def page_ev(o):
    o["seed_admit"]["evidence"] = {"demoted_from": {"channel": "m", "by": BY}}


def base_page_ev(o):
    o["seed_admit"]["evidence"] = {}


def reorder(o):
    ev = cells(o)[0]["evidence"]; ev["cov"] = ev.pop("cov")        # cov 挪到最后：语义同、键序异


def dupkey(r):
    f = r / "new" / P
    t = f.read_text("utf-8"); t = t.replace('"slot": 2', '"slot": 9, "slot": 2', 1); f.write_text(t, "utf-8")


def badjson(r):
    (r / "new" / P).write_text('{"seed_admit": ', "utf-8")


def oddnames(r):
    d = r / "new" / "vol04/seed_admit"
    shutil.copy(d / "p0001.json", d / "0001.json"); shutil.copy(d / "p0001.json", d / "P0003.json")


cases = [
    # (名, 项, base变换, new变换, new原始改写, 书, 工具们[(label, tool, flags)])
    ("H4col 列级 evidence 带键", "①", base_col_ev, lambda o: (base_col_ev(o), col_ev(o)), None),
    ("H4page 页级 evidence 带键", "①", base_page_ev, lambda o: (base_page_ev(o), page_ev(o)), None),
    ("H4c by 非白名单（缺省）", "①", demote, lambda o: (demote(o), cells(o)[0]["evidence"].__setitem__("demoted_from", {"channel": None, "by": "bogus_pass"})), None),
    ("H4c by 非白名单（--strict-by）", "①", demote, lambda o: (demote(o), cells(o)[0]["evidence"].__setitem__("demoted_from", {"channel": None, "by": "bogus_pass"})), None),
    ("H4c' channel 非 str/None", "①", demote, lambda o: (demote(o), cells(o)[0]["evidence"].__setitem__("demoted_from", {"channel": 5, "by": BY})), None),
    ("合法 W5 形（对照，应过）", "—", demote, with_dm, None),
    ("H1b 带键页重复键", "②", demote, with_dm, dupkey),
    ("H1d 带键页键序不同", "②", demote, lambda o: (with_dm(o), reorder(o)), None),
    ("H2d 多册 vol04 坏 JSON、vol05 好", "③", None, None, badjson),
    ("H5d 新根含 0001.json／P0003.json", "④", None, None, oddnames),
]
rows = []
for name, item, mb, mn, raw in cases:
    r = mk(name.split(" ")[0] + "_" + str(len(rows)), mb, mn, raw)
    B, N = str(r / "base"), str(r / "new")
    flags_w5 = ("--strict-by",) if "strict-by" in name else ()
    books = ("vol04", "vol05")
    res = []
    for lab, tool, fl in (("w5", "w5", flags_w5), ("cmp --strip", "cmp", ("--strip-demoted-from",))):
        o = run(old, tool, B, N, books, *fl); n = run(new, tool, B, N, books, *fl)
        res.append((lab, o[0], n[0], n[1]))
    rows.append((name, item, res))
print("| 情形 | 项 | w5 v2→v2.1 | cmp --strip v2→v2.1 |\n|---|---|---|---|")
for name, item, res in rows:
    print(f"| {name} | {item} | {res[0][1]}→{res[0][2]} | {res[1][1]}→{res[1][2]} |")
print("\n## v2.1 输出（节选）")
for name, item, res in rows:
    for lab, o, n, txt in res:
        short = " / ".join(l[:160] for l in txt.strip().splitlines())[:420]
        print(f"- {name} · {lab}: rc={n} | {short}")
