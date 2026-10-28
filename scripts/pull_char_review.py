"""把快审页后台存的结果（db 集合 review）合并成 ingest_char_review.py 吃的 JSON。

用法：先用 ArtifactData 的 list 把 review 集合导成 JSON 文件（Claude 会话里做），再
    python scripts/pull_char_review.py rows.json out.json
rows.json 是文档数组或 {docs:[...]}，每份含 book/page/ok/bad。
"""
import json, sys
rows = json.load(open(sys.argv[1], encoding="utf-8"))
rows = rows.get("docs", rows.get("items", rows)) if isinstance(rows, dict) else rows
rows = [r.get("data", r) for r in rows]
book = rows[0]["book"]
ok, bad, pages = [], [], set()
for r in sorted(rows, key=lambda r: r["page"]):
    pages.add(r["page"]); ok += r["ok"]; bad += r["bad"]
json.dump({"book": book, "pages_seen": len(pages), "ok": ok, "bad": bad},
          open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
print(f"册{book}: {len(pages)} 页, ok {len(ok)}, bad {len(bad)}")
