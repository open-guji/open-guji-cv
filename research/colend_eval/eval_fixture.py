"""用 tests/fixtures/colend 跑列端评测(质量口径,不进测试)。口径(Mila 10-11 定):
- **trim 与 double 互通**(任一都算对);"人眼难分"不当缺陷数;
- glued 的"正确"= 规则没有把字削进去(以叠图 47:2/70:8 的核实为准,见 deep_cut);
- deep_cut 预警只在这里统计,不进 triage:多层端(层数≥2)累计 cut 超出 Step1 内框线距 +25px。
用法: python3 -I eval_fixture.py [fixture_dir] —— 默认 tests/fixtures/colend,读冻结档位(不重跑引擎);加 --rerun 则对冻结整列现跑。"""
import sys, json, re, pathlib, collections
FX = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "colend"
man = json.loads((FX / "manifest.json").read_text(encoding="utf-8"))
if "--rerun" in sys.argv:
    import numpy as np; from PIL import Image
    from open_guji_cv.books.siku_zongmu.column import clean_column
    cache = {}
    for e in man["ends"]:
        k = e["col_key"]
        if k not in cache:
            c = man["columns"][k]; img = np.where(np.array(Image.open(FX / c["file"]).convert("L")) >= 128, 255, 0).astype(np.uint8)
            cache[k] = clean_column(img, layers=tuple(man["layers"]), layer_gap=tuple(man["layer_gap"]), inner_bottom=c["inner_bottom"])[1]
        d = cache[k]["top" if e["end"] == "top" else "bottom"]; e["frozen_case"], e["frozen_px"] = d["case"], int(d["px"])
def parse(case): return case[0], int(re.sub(r"\D", "", case) or 1), case.endswith("i")
def behaviour(case):
    L, n, i = parse(case)
    if i: return "Xi"
    if n >= 2: return "multi"
    return {"a": "cut", "d": "cut", "e": "cut", "b": "b3", "c": "nocut"}[L]
rows = man["ends"]
t = collections.Counter((e["label"], behaviour(e["frozen_case"])) for e in rows)
cols = ["cut", "multi", "Xi", "b3", "nocut"]
print(f"n={len(rows)} (trim/double 互通)\n| 人判＼规则行为 | " + " | ".join(cols) + " |"); print("|---|" + "---|" * len(cols))
for lab in ("trim", "double", "glued", "none"):
    print(f"| {lab} | " + " | ".join(str(t[(lab, c)]) for c in cols) + " |")
# 互通后的"削 vs 不削"
want_cut = [e for e in rows if e["label"] in ("trim", "double", "glued")]
miss = [e for e in want_cut if behaviour(e["frozen_case"]) == "nocut"]
fa = [e for e in rows if e["label"] == "none" and e["frozen_px"] > 3]
print(f"\n应削(trim/double/glued){len(want_cut)} 端中规则不削 {len(miss)}: {[e['id'] for e in miss]}")
print(f"人判 none 但规则削>3 行: {len(fa)}: {[(e['id'], e['frozen_case'], e['frozen_px']) for e in fa]}")
# deep_cut 预警(仅下端有内框线距)
deep = []
for e in rows:
    if e["end"] != "bot": continue
    L, n, i = parse(e["frozen_case"]); c = man["columns"][e["col_key"]]
    if n >= 2:
        inner = None
        # inner_bottom 是整列坐标;列高需读图
        from PIL import Image
        H = Image.open(FX / c["file"]).size[1]; inner = H - c["inner_bottom"]
        if e["frozen_px"] - inner > 25: deep.append((e["id"], e["frozen_case"], e["frozen_px"], round(inner, 1)))
print(f"\ndeep_cut 预警(多层下端累计 cut > 内框线距+25px): {len(deep)} 端:")
for d in deep: print("  ", d)
print("已叠图确认伤字: vol02:47:2:bot, vol02:70:8:bot;预警是否命中:", [x in {d[0] for d in deep} for x in ("vol02:47:2:bot", "vol02:70:8:bot")])
