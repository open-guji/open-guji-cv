"""seal_flag 开/关两份 cell_shrink 产物对比：去掉 seal_region 旗后必须逐字节相同（几何/类型/字块键一概不动）。
用法: python flag_diff.py <prods_on> <prods_off>"""
import json, sys, glob, os
on, off = sys.argv[1:3]
tot = {}
for f in sorted(glob.glob(f"{on}/*/cell_shrink/p*.json")):
    book, page = f.split("/")[-3], os.path.basename(f)
    g = f.replace(on, off)
    a, b = json.load(open(f)), json.load(open(g))
    nflag = 0
    for col in a["char_index"]["columns"]:
        for ch in col["chars"]:
            if "seal_region" in ch["flags"]:
                nflag += 1; ch["flags"] = [x for x in ch["flags"] if x != "seal_region"]
    same = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    n = sum(len(c["chars"]) for c in a["char_index"]["columns"])
    print(f"{book} {page}: 字位 {n}, seal_region {nflag}, 去旗后与关旗版一致: {same}")
    assert same, f
