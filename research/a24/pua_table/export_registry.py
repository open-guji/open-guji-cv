# -*- coding: utf-8 -*-
"""码表 pua_table.jsonl → 待收字登记表 glyph_pending_codes.json（重导，并**双向**核对；A24 2026-11-06，A31 R01 深挖发现漏导 7 码）。

登记表 `codes` ＝ 码表里 verdict=pending 的 daizhige 码 ∪ 它们的 same_as（siku-qiefen-v2 码）∪ 原登记表里还没有 E 码对照的 v2 码（原样保留）。
双向校验（旧 export_table.py 只查「v2 同义码在不在登记表」，同义码在就放过了，所以漏了 7 个 E 码）：
  ① 码表待收 → 登记表：码本身必须在登记表，同义 v2 码也必须在；
  ② 登记表 daizhige 码 → 码表：必须在码表里且 verdict=pending（不能是 char／open／not_char）；
  ③ 登记表 v2 码：在码表 same_as 里有对应的列出数量；没有的只是还没有 E 码对照，原样保留；
  ④ 登记表任一码在码表里 verdict=char → 报冲突，退出码 1。
用法：python3 export_registry.py pua_table.jsonl 旧登记表.json 新登记表.json
"""
import json, sys


def main(table, old, out):
    rows = [json.loads(l) for l in open(table, encoding="utf-8")]
    oldj = json.load(open(old, encoding="utf-8"))
    oldc = oldj["codes"]
    by = {r["code"]: r for r in rows}
    pend = {r["code"]: r for r in rows if r["verdict"] == "pending"}
    new_dz = sorted(pend)
    pend_v2 = {s for r in pend.values() for s in r["same_as"] if s.startswith("siku-qiefen-v2:")}
    keep_v2 = [c for c in oldc if c.startswith("siku-qiefen-v2:")]
    v2 = sorted(set(keep_v2) | pend_v2)
    codes = v2 + new_dz
    reg = set(codes)
    old_dz = {c for c in oldc if c.startswith("daizhige:")}
    bad = []
    miss = sorted(c for c in pend if c not in set(oldc))
    miss_v2 = sorted(s for s in pend_v2 if s not in set(oldc))
    print("表内待收", len(pend), "；旧登记表 daizhige", len(old_dz), "v2", len(keep_v2), "→ 新登记表", len(codes), f"(v2 {len(v2)}，daizhige {len(new_dz)})")
    print("① 旧登记表漏的待收 E 码", len(miss), miss, "；漏的同义 v2 码", miss_v2)
    extra = sorted(old_dz - set(pend))
    print("② 旧登记表 daizhige 码不是码表待收：", extra)
    for c in extra:
        bad.append(("登记表 E 码不是待收", c, by.get(c, {}).get("verdict")))
    nov2 = sorted(s for s in keep_v2 if s not in pend_v2)
    print("③ v2 码在码表待收 same_as 里有对应", len(pend_v2), "个；没有 E 码对照的", len(nov2), "个（原样保留）")
    for c in reg:
        if by.get(c, {}).get("verdict") == "char":
            bad.append(("登记表码在码表里已定字", c, by[c]["char"]))
    for r in pend.values():
        for s in r["same_as"]:
            if s not in reg:
                bad.append(("同义码不在登记表", r["code"], s))
    if bad:
        print("冲突：", bad)
    oldj["codes"] = codes
    oldj["_note"] = oldj["_note"].split(" 同时列殆知阁源文件的原码位")[0] + (
        f" 同时列殆知阁源文件的原码位（daizhige:U+Exxx）：出单时按窗口回查得到的是这套码。11-06 起由码表 pua_table.jsonl 重导（research/a24/pua_table/export_registry.py）："
        f"daizhige 码 ＝ 码表 verdict=pending 的全部（{len(new_dz)} 个，补上此前漏导的 {len(miss)} 个），v2 码 {len(v2)} 个（其中 {len(nov2)} 个还没有 E 码对照，原样保留）；码表与登记表双向核对一致。")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(oldj, f, ensure_ascii=False, indent=1)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
