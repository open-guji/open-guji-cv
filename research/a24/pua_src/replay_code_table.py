"""回放 `_pua_code_pass`（seed_admit pua_code_table）：对各册★main 包的 seed_admit 页，用 build_cell_codes.py 的输出当格→码记录，
看哪些格被改字／降审／仍不一致。用法：python replay_code_table.py <cellcodes目录> <包根> <out.tsv> [册…]"""
import collections, glob, json, os, sys
from open_guji_cv.feedback.rulings import RulingStore
from open_guji_cv.products.kinds.recog import PageAdmit, PageAlignRef
from open_guji_cv.steps.seed_admit import _pua_code_pass
from open_guji_cv.utils.pua_v2_codes import load_table

ccdir, root, out = sys.argv[1:4]
vols = sys.argv[4:] or sorted(os.path.basename(f)[11:-6] for f in glob.glob(ccdir + "/cell_codes-*.jsonl"))
table = load_table(None)
rows = []
for v in vols:
    cc = [json.loads(l) for l in open(f"{ccdir}/cell_codes-{v}.jsonl")]
    st = RulingStore(persist=False)
    for r in cc:
        st.put_cell_code(r["cell"], r["code"], ref=r["ref"], anch=r["anch"], page_match=r["page_match"])
    pages = sorted({int(r["cell"].split(":")[1]) for r in cc})
    P = f"{root}/{v}/{v}" if os.path.isdir(f"{root}/{v}/{v}") else f"{root}/{v}"
    for p in pages:
        pa = PageAdmit.model_validate(json.load(open(f"{P}/seed_admit/p{p:04d}.json"))["seed_admit"])
        try:
            al = PageAlignRef.model_validate(json.load(open(f"{P}/align_ref/p{p:04d}.json"))["align_ref"])
            amap = {c.id: (c.align_char, c.align_op) for c in al.chars} if al.anchored else {}
        except FileNotFoundError:
            amap = {}
        for c in pa.columns:                       # ★main 包里 src_code_conflict 已降审的格，还原成降审前（字还在，通道记在 demoted_from）
            for r in c.chars:
                if "src_code_conflict" in (r.doubts or []) and (r.evidence or {}).get("demoted_from"):
                    r.admit, r.channel, r.provenance = True, r.evidence["demoted_from"]["channel"], "match"
                    r.doubts = [d for d in r.doubts if d != "src_code_conflict"]
        before = {r.id: (r.admit, r.char, r.channel, r.provenance) for c in pa.columns for r in c.chars}
        fix, mism, dem = _pua_code_pass(pa.columns, amap, st, table)
        for c in pa.columns:
            for r in c.chars:
                if r.id in st.cell_codes() and r.id in before:
                    code = st.cell_codes()[r.id]["code"]
                    b = before[r.id]
                    act = "改字" if r.channel == "code_table" else ("降审" if b[0] and not r.admit else "")
                    rows.append((r.id, code, table[0].get(code, ""), b[1], b[2], b[3], r.char, act))
with open(out, "w") as f:
    f.write("格号\t码\t码表字\t原放行字\t原通道\t原provenance\t回放后字\t动作\n")
    for r in rows:
        f.write("\t".join(map(str, r)) + "\n")
c = collections.Counter((r[7] or "不动") for r in rows)
print(len(rows), "有码的格", dict(c))
