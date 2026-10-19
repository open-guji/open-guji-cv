"""核对：中心库里的内容与 guji-workspace 某个提交逐行、逐文件一致（GUJI-603 验收）。

从库里把每个文件还原出来（逐行表按 src_line 拼回，整文件表取 raw），和提交里 blob 的
sha256 比；每行再单独比一次哈希，刻例图与锚图比 sha。不经过导入时的差分逻辑。
"""

from __future__ import annotations

from collections import Counter, defaultdict

from . import gitsource
from .scope import BLOB_TABLES, GS, TABLES, classify, sha256, split_lines

LINE_TABLES = {t for t in TABLES if t not in (
    "workspaces", "books", "files", "source_files", *BLOB_TABLES)}


def _db_files(cur, ws: str) -> dict[str, dict]:
    cur.execute("SELECT src_path, tbl, sha256, bytes, n_lines, final_newline "
                "FROM source_files WHERE ws = %s", (ws,))
    return {r[0]: {"tbl": r[1], "sha": r[2], "bytes": r[3], "n": r[4], "final": r[5]}
            for r in cur.fetchall()}


def verify_commit(conn, repo, commit: str = "HEAD") -> dict:
    commit = gitsource.resolve(repo, commit)
    tree = gitsource.list_tree(repo, commit)
    reader = gitsource.BlobReader(repo)
    cur = conn.cursor()
    report: dict = {"commit": commit, "workspaces": {}, "ok": True}
    try:
        for d, files in gitsource.workspaces_in_tree(tree).items():
            wsrep = _verify_ws(cur, reader, d, files)
            report["workspaces"][wsrep["ws"]] = wsrep
            report["ok"] &= not wsrep["mismatches"]
    finally:
        reader.close()
    return report


def _verify_ws(cur, reader, d, files) -> dict:
    blobs = {rel: oid for rel, oid in files if oid}
    import yaml
    ws = str((yaml.safe_load(reader.read(blobs["workspace.yaml"])) or {}).get("id") or d)
    mism: list[str] = []
    counts = Counter()
    dbf = _db_files(cur, ws)

    # 逐行表：一次取回该工作区的全部行，按文件分组
    lines_by_file: dict[str, dict[int, str]] = defaultdict(dict)
    rows_by_tbl = Counter()
    for tbl in LINE_TABLES:
        cur.execute(f"SELECT src_path, src_line, raw FROM {tbl} WHERE ws = %s", (ws,))
        for p, i, raw in cur.fetchall():
            if i in lines_by_file[p]:
                mism.append(f"{p}:{i}: 库里同一行出现两次")
            lines_by_file[p][i] = raw
            rows_by_tbl[tbl] += 1
    whole: dict[str, str] = {}
    for tbl in ("workspaces", "books", "files"):
        cur.execute(f"SELECT src_path, raw FROM {tbl} WHERE ws = %s", (ws,))
        whole.update(dict(cur.fetchall()))
    blob_sha: dict[str, str] = {}
    for t in BLOB_TABLES:
        cur.execute(f"SELECT src_path, sha256 FROM {t} WHERE ws = %s", (ws,))
        blob_sha.update(cur.fetchall())
    cur.execute("SELECT instance_id, patch_sha FROM glyph_instances WHERE ws = %s", (ws,))
    patch_sha = dict(cur.fetchall())

    git_lines = Counter()
    seen_paths = set()
    for rel, oid in sorted(blobs.items()):
        tbl = classify(rel)
        if tbl == "patch":
            # 实例 id 里的 ':' 导出时换成了 '_'，反查不唯一，所以按实例逐个比（见下）
            counts["patches_in_git"] += 1
            continue
        data = reader.read(oid)
        bsha = sha256(data)
        if tbl in BLOB_TABLES:
            counts["anchor_patches" if tbl == "anchor_patches_meta" else tbl] += 1
            seen_paths.add(rel)
            if blob_sha.get(rel) != bsha:
                mism.append(f"{rel}: {tbl} 记的 sha 不符")
            continue
        seen_paths.add(rel)
        counts["files"] += 1
        f = dbf.get(rel)
        if f is None:
            mism.append(f"{rel}: source_files 里没有")
            continue
        if f["sha"] != bsha or f["bytes"] != len(data):
            mism.append(f"{rel}: source_files 记的 sha/字节数与提交不符")
        if tbl in ("workspaces", "books", "files"):
            if rel not in whole:
                mism.append(f"{rel}: {tbl} 里没有")
            elif sha256(whole[rel].encode("utf-8")) != bsha:
                mism.append(f"{rel}: 整文件 sha 不符")
            continue
        glines, _ = split_lines(data)
        git_lines[tbl] += sum(1 for x in glines if x.strip())
        have = lines_by_file.get(rel, {})
        rebuilt = [have.get(i, "") for i in range(f["n"])]
        extra = [i for i in have if i >= f["n"]]
        if extra:
            mism.append(f"{rel}: 库里多出行 {extra[:5]}")
        bad = [i for i, (a, b) in enumerate(zip(rebuilt, glines))
               if sha256(a.encode()) != sha256(b.encode())]
        if bad or len(rebuilt) != len(glines):
            mism.append(f"{rel}: {len(bad)} 行哈希不符（如第 {bad[:5]} 行），"
                        f"行数 库{len(rebuilt)}/提交{len(glines)}")
        text = "\n".join(rebuilt) + ("\n" if f["final"] else "")
        if sha256(text.encode("utf-8")) != bsha:
            mism.append(f"{rel}: 还原后整文件 sha 不符")
        counts["lines_checked"] += len(glines)

    # 刻例图：每个实例的 patch_sha 对 git 里的图
    for iid, sha in patch_sha.items():
        rel = f"{GS}patches/{iid.replace(':', '_')}.png"
        oid = blobs.get(rel)
        if oid is None:
            if sha is not None:
                mism.append(f"{iid}: 库里有 patch_sha，提交里没有图")
            continue
        counts["patches_checked"] += 1
        if sha256(reader.read(oid)) != sha:
            mism.append(f"{iid}: 刻例图 sha 不符")

    for p in sorted(set(dbf) - seen_paths):
        mism.append(f"{p}: 库里有，提交里没有")
    for tbl in sorted(LINE_TABLES):
        if rows_by_tbl[tbl] != git_lines[tbl]:
            mism.append(f"{tbl}: 行数 库{rows_by_tbl[tbl]} / 提交非空行{git_lines[tbl]}")
    return {"ws": ws, "dir": d, "counts": dict(counts),
            "rows": {t: rows_by_tbl[t] for t in sorted(LINE_TABLES)},
            "git_lines": {t: git_lines[t] for t in sorted(LINE_TABLES)},
            "mismatches": mism}
