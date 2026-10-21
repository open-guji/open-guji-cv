"""语料库分层版本 P3 的一键迁移（设计 doc/design/语料库分层版本.md 第八节）。

分两个阶段，**先 prepare，再 push**，每次只做一件事，重复跑安全：

  python scripts/migrate_corpus_layers.py prepare -w <殿本工作区>
      只写本机（数据目录）和 R2（按哈希存，只增）：拉最新 → 放 book_prompt.json → 出全局层新版 b<M>
      （不推）→ 出书库新版 v<N>（两级清单）→ 十册各登钉子账 → verify 全部干净 → 大文件上传 R2。
      不改册 yaml、不推中心库。

  python scripts/migrate_corpus_layers.py push -w <殿本工作区> [--yes]
      把 prepare 出的东西推进中心库：先全局层（corpus-base，升级脚本身份），再殿本工作区
      （书库 v<N>、钉子账、book_prompt.json）。缺省只演练；**真推要 --yes，而且要 sheldon 一句同意**。

册 yaml 改 `corpus: <新总号>` 不在这里做（归发版时统一改册配置的人，和 lv／zheng 点名一起）。
钉子账首行是迁移行（`legacy_token`），保持 `corpus: 9` 的册指纹 `corpus-v9` 不变。
需要中心库写权限（`NEON_DATABASE_URL` 等）和 R2 令牌（`GUJI_DATA_TOKEN`）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BOOK_PROMPT = {"book_desc": "《四庫全書總目》殿本刻本"}


def _vols(ws: Path) -> list[str]:
    from open_guji_cv.core.workspace import books_dir
    d = books_dir(ws)
    return sorted(p.stem for p in d.glob("*.yaml")) if d and d.is_dir() else []


def prepare(ws: Path, from_n: int, note: str) -> dict:
    from open_guji_cv.core import corpus_pin as cpn
    from open_guji_cv.datastore.client import BlobCache, WorkerSource
    from open_guji_cv.datastore.workcopy import _db_manifest, pull
    from open_guji_cv.ops import corpus_pack as cp

    src = WorkerSource()
    print("1/7 拉殿本最新（只读）…")
    pull(src, ws, cache=BlobCache())
    print("2/7 放 book_prompt.json（书层）…")
    from open_guji_cv.core.workspace import data_root
    f = data_root(ws) / "config" / "groups" / "book_prompt.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(BOOK_PROMPT, ensure_ascii=False) + "\n", encoding="utf-8")
    print("3/7 出全局层新版（本机，不推）…")
    base_ws = cp.base_workdir("main")
    if _db_manifest(src, cp.BASE_WS):
        pull(src, base_ws, force=True)
    out = cp.build_base(base_ws, note)
    b = json.loads(out.read_text(encoding="utf-8"))["base_version"]
    dst = Path(str(cpn.base_manifest_path(ws, b)))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out.read_bytes())
    print(f"    全局层 b{b}")
    print("4/7 出书库新版（两级清单，本机）…")
    v = int(cp.build(ws, note=note, base=b).parent.name[1:])
    print(f"    书库 v{v}")
    print("5/7 十册登钉子账…")
    rows = {}
    for vol in _vols(ws):
        rows[vol] = cpn.append_pin(ws, vol, from_n=from_n, global_ver=b, book_ver=v, note=note)["n"]
    print("    ", rows)
    print("6/7 verify …")
    bad = {vol: cp.verify(ws, n, vol) for vol, n in rows.items()}
    bad = {k: r for k, r in bad.items() if not r["clean"]}
    if bad:
        raise SystemExit(f"verify 不干净：{json.dumps(bad, ensure_ascii=False)[:800]}")
    print("7/7 大文件传 R2（按哈希，已有跳过）…")
    n = next(iter(rows.values()))
    vol0 = next(iter(rows))
    up = cp.upload_blobs(ws, n, vol0, execute=True)
    print("    ", up.get("upload"))
    return {"base": b, "book": v, "pins": rows}


def push(ws: Path, yes: bool) -> None:
    from open_guji_cv.cli_db import _pg_conn
    from open_guji_cv.datastore.workcopy import push as wpush
    from open_guji_cv.ops import corpus_pack as cp

    actor = os.environ.get("GUJI_ACTOR") or os.environ.get("USER") or None
    base_ws = cp.base_workdir("main")
    print(f"全局层 corpus-base → 中心库{'' if yes else '（演练）'}")
    with _pg_conn() as conn:
        rep = wpush(conn, base_ws, actor=actor, shared_writer=True, dry_run=not yes)
    print(json.dumps(rep, ensure_ascii=False, default=str)[:600])
    cmd = [sys.executable, "-m", "open_guji_cv", "db", "push", "-w", str(ws)] + ([] if yes else ["--dry-run"])
    print("殿本工作区 →", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["prepare", "push"])
    ap.add_argument("-w", "--workspace", required=True, help="殿本工作区目录（含 workspace.yaml）")
    ap.add_argument("--from-n", type=int, default=9, help="册 yaml 现在的 corpus: 号（缺省 9）")
    ap.add_argument("--note", default="语料库分层版本 P3 迁移", help="写进清单和钉子账的备注")
    ap.add_argument("--yes", action="store_true", help="push：真推（缺省只演练）")
    a = ap.parse_args()
    ws = Path(a.workspace).expanduser().resolve()
    os.environ["GUJI_WORKSPACE"] = str(ws)
    if a.phase == "prepare":
        print(json.dumps(prepare(ws, a.from_n, a.note), ensure_ascii=False))
    else:
        push(ws, a.yes)


if __name__ == "__main__":
    main()
