# -*- coding: utf-8 -*-
"""给正式 products 留快照（路径+sha256）。只读，不写 products。

    python products_snapshot.py <products根> <册...> --out <目录>      # 每册出 <目录>/<册>.manifest.jsonl.gz
    python products_snapshot.py --verify <目录>/<册>.manifest.jsonl.gz <products根>   # 复核快照与现状一致

manifest 每行 {"path": "<册>/<步>/<文件>", "sha256": ..., "size": ...}；末行 {"summary": 汇总sha256, "n": 文件数}。
汇总 sha256 = 按 path 排序后逐行 "path\tsha256\n" 的 sha256，贴到卡上即可。
"""
import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def scan(root: Path, book: str) -> list[dict]:
    base = root / book
    if not base.is_dir():
        sys.exit(f"没有 {base}")
    rows = [{"path": f"{book}/{p.relative_to(base).as_posix()}", "sha256": sha(p), "size": p.stat().st_size}
            for p in sorted(base.rglob("*")) if p.is_file()]
    return rows


def summary(rows: list[dict]) -> str:
    h = hashlib.sha256()
    for r in sorted(rows, key=lambda r: r["path"]):
        h.update(f'{r["path"]}\t{r["sha256"]}\n'.encode())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root_or_manifest")
    ap.add_argument("books", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.verify:
        mf, root = Path(a.root_or_manifest), Path(a.books[0])
        rows = [json.loads(l) for l in gzip.open(mf, "rt", encoding="utf-8")]
        meta = rows.pop()
        book = rows[0]["path"].split("/")[0]
        cur = {r["path"]: r["sha256"] for r in scan(root, book)}
        old = {r["path"]: r["sha256"] for r in rows}
        diff = [p for p in old if cur.get(p) != old[p]]
        extra = [p for p in cur if p not in old]
        print(f"{book}: 快照 {meta['n']} 个文件 summary={meta['summary']}；现状不同 {len(diff)}、新增 {len(extra)}")
        return 0 if not diff and not extra else 1
    root, out = Path(a.root_or_manifest), Path(a.out or ".")
    out.mkdir(parents=True, exist_ok=True)
    for book in a.books:
        rows = scan(root, book)
        s = summary(rows)
        with gzip.open(out / f"{book}.manifest.jsonl.gz", "wt", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.write(json.dumps({"summary": s, "n": len(rows)}) + "\n")
        print(f"{book}: {len(rows)} 个文件 summary={s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
