# -*- coding: utf-8 -*-
"""审核页结果 → 回写 pua_table.jsonl 的 verdict/char/by/at。

输入：审核页（char_card，id 形如 `daizhige:U+EA96#5-18-141`）存在 db 里的逐格文档列表（ArtifactData list 导出的 JSON，
每项 {id, v, t, …}，可裹在 {"docs":[…]}/{"items":[…]} 里）。每个码汇总它所有已点格：
  pick:X → char=X；notchar → not_char；unknown[:部件] → pending；unclear/seg → 不改（列出）；
同一码的格答案不一致 → 不改，列入 conflicts。by=用户名（--by），at=该码最新一格的时间。
用法：python3 apply_review.py TABLE.jsonl DOCS.json --by sheldon [--out NEW.jsonl]   默认只打印，加 --write 才写回。
"""
import argparse, collections, datetime, json


def load_docs(p):
    d = json.load(open(p, encoding="utf-8"))
    if isinstance(d, dict):
        d = d.get("docs", d.get("items", []))
    return [x.get("data", x) for x in d]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("table"); ap.add_argument("docs"); ap.add_argument("--by", required=True)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.table, encoding="utf-8")]
    by_code = {r["code"]: r for r in rows}
    ans = collections.defaultdict(dict)   # code → {cell id: (answer, t)}
    for d in load_docs(a.docs):
        i, v = d.get("id"), d.get("v")
        if not i or "#" not in i or not v:
            continue
        code = i.split("#")[0]
        if code in by_code:
            ans[code][i] = (v, d.get("t") or 0)
    changed, conflicts, untouched = [], [], []
    for code, cells in ans.items():
        r = by_code[code]
        kinds = {}
        for cid, (v, t) in cells.items():
            if v.startswith("pick:"):
                kinds[cid] = ("char", v[5:])
            elif v == "notchar":
                kinds[cid] = ("not_char", None)
            elif v.startswith("unknown"):
                kinds[cid] = ("pending", None)
            else:
                kinds[cid] = ("skip", v)
        real = {k for k in kinds.values() if k[0] != "skip"}
        if not real:
            untouched.append((code, sorted({k[1] for k in kinds.values()})))
            continue
        if len(real) > 1:
            conflicts.append((code, sorted(real)))
            continue
        verdict, ch = next(iter(real))
        t = max(t for _, t in cells.values())
        at = datetime.datetime.fromtimestamp(t / 1000 if t > 1e11 else t, datetime.timezone.utc).strftime("%Y-%m-%d") if t else None
        if (r["verdict"], r.get("char")) != (verdict, ch):
            changed.append((code, r["verdict"], r.get("char"), verdict, ch))
            r.update(verdict=verdict, char=ch if verdict == "char" else None, by=a.by, at=at)
            if verdict != "char":
                r["orig"] = None; r["variant"] = None
    print(f"已点 {len(ans)} 码；改动 {len(changed)}；不一致 {len(conflicts)}；只点了看不清/切分 {len(untouched)}")
    for c in changed:
        print("改", *c)
    for c in conflicts:
        print("不一致（不改）", *c)
    for c in untouched:
        print("未改（看不清/切分）", *c)
    if a.write:
        with open(a.table, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("已写回", a.table)


if __name__ == "__main__":
    main()
