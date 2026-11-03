# -*- coding: utf-8 -*-
"""``guji model``：模型系统第一期（`core/model_pack.py`，设计 `doc/design/模型系统.md`）。

    guji model ls     -w <工作区>            # 这本书现在用的模型（每个文件一张卡：种类、层、归谁、sha256）
    guji model build  -w <工作区> [--note]   # 出新模型总号 m<N>（内容没变不出）；迁过的工作区接着 guji db push
    guji model verify -w <工作区> [--version N]   # 清单 vs 当前文件
    guji model list   -w <工作区>            # 已有的总号
    guji model upload -w <工作区> [--version N] [--execute]   # 清单里的文件按 sha256 传进 R2（缺省演练）
    guji model fetch  -w <工作区> [--version N]   # 本机缺的从 R2 取回、放到登记位置（pipeline 起跑前自动做）
    guji model fetch                          # 不给 -w：按 cv 自带的模型表补齐 cv 的 models/
    guji model registry                       # 按当前 models/ 重写 cv 自带的模型表（发版删文件前跑）
    guji model upload [--execute]             # 不给 -w：cv 模型表里的文件传进 R2

册 yaml 写 ``model: N`` 钉住。本命令不改册 yaml、不推中心库。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _ws(args) -> Path:
    if not args.workspace:
        print("✗ 要给 -w 工作区", file=sys.stderr)
        sys.exit(2)
    ws = Path(args.workspace).expanduser().resolve()
    if not ws.is_dir():
        print(f"✗ 工作区 {ws} 不存在", file=sys.stderr)
        sys.exit(2)
    return ws


def _out(obj, as_json: bool) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1 if as_json else None))


def cmd_model(args) -> None:
    from .core import model_pack as mp
    if args.model_cmd == "registry":
        _out(mp.build_registry(), True)
        return
    if args.model_cmd == "upload" and not args.workspace:
        from .ops import model_blobs as mb
        try:
            _out(mb.upload_registry(execute=args.execute), True)
        except ValueError as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)
        return
    if args.model_cmd == "fetch" and not args.workspace:
        from .ops import model_blobs as mb
        r = mb.fetch_registry()
        _out(r, True)
        sys.exit(1 if r["not_in_r2"] or r["placed"] < r["missing"] else 0)
    ws = _ws(args)
    if args.model_cmd == "ls":
        items = mp.collect(ws)
        if args.json:
            _out({"items": items, "external": mp.EXTERNAL}, True)
            return
        for i in items:
            print(f"{i['kind']:<15} {i['level']:<6} {i['owner']:<12} {i['sha256'][:12]}  {i['root']}:{i['path']}")
        for name, e in mp.EXTERNAL.items():
            print(f"{e['kind']:<15} {e['level']:<6} {e['owner']:<12} {e['revision'][:12]:<12}  外部 {e['repo']}")
        print(f"共 {len(items)} 个文件；内容哈希 {mp.items_digest(items, mp.EXTERNAL)}")
    elif args.model_cmd == "build":
        try:
            r = mp.build(ws, args.version, args.note, dry_run=args.dry_run)
        except ValueError as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)
        if "unchanged" in r:
            print(f"= 模型内容与 m{r['unchanged']} 相同，不出新号")
        else:
            print(f"✓ {'（演练）' if r['dry_run'] else ''}已写 m{r['version']}：{r['items']} 个文件，{r['digest']}"
                  f"（{r['path']}；迁过的工作区接着 guji db push -w {ws}，册 yaml 写 model: {r['version']} 钉住）")
    elif args.model_cmd == "verify":
        vs = mp.versions(ws)
        v = args.version or (vs[-1] if vs else None)
        if not v:
            print("✗ 还没有模型清单（先 guji model build）", file=sys.stderr)
            sys.exit(2)
        r = mp.check_files(ws, mp.load_manifest(ws, v))
        if args.json:
            _out({"version": v, **r}, True)
        bad = r["changed"] + r["missing"]
        if not args.json:
            print(("✓" if not bad else "✗") + f" m{v}：改了 {len(r['changed'])}，缺 {len(r['missing'])}，"
                  f"新增 {len(r['extra'])}  {(bad + r['extra'])[:6]}")
        sys.exit(1 if bad else 0)
    elif args.model_cmd in ("upload", "fetch"):
        from .ops import model_blobs as mb
        try:
            r = (mb.upload(ws, args.version, execute=args.execute) if args.model_cmd == "upload"
                 else mb.fetch(ws, args.version))
        except (ValueError, FileNotFoundError) as e:
            print(f"✗ {e}", file=sys.stderr)
            sys.exit(1)
        _out(r, True)
        if args.model_cmd == "fetch" and (r["differ_not_overwritten"] or r["not_in_r2"]):
            sys.exit(1)
    elif args.model_cmd == "list":
        vs = mp.versions(ws)
        rows = []
        for v in vs:
            m = mp.load_manifest(ws, v)
            rows.append({"version": v, "items": len(m.get("items") or []), "digest": m.get("digest"),
                         "note": m.get("note", "")})
        if args.json:
            _out(rows, True)
        else:
            for r in rows:
                print(f"m{r['version']}  {r['items']} 个文件  {r['digest']}  {r['note']}")
            if not rows:
                print("（还没有模型清单）")


def add_parser(sub) -> None:
    p = sub.add_parser("model", help="[v2] 模型总号：ls 列模型卡／build 出 m<N>／verify／list（册 yaml 写 model: N 钉住）")
    ps = p.add_subparsers(dest="model_cmd", required=True)
    ls_ = ps.add_parser("ls", help="这本书现在用的模型")
    b = ps.add_parser("build", help="出新模型总号（内容没变不出）")
    b.add_argument("--version", type=int, default=None, help="指定号（缺省最大号+1）")
    b.add_argument("--note", default="")
    b.add_argument("--dry-run", action="store_true")
    v = ps.add_parser("verify", help="清单 vs 当前文件（退出码 1 = 有改动或缺失）")
    v.add_argument("--version", type=int, default=None, help="缺省最新")
    li = ps.add_parser("list", help="已有的模型总号")
    up = ps.add_parser("upload", help="清单里的文件按 sha256 传进 R2（已有跳过；缺省只演练；不给 -w 传 cv 模型表里的）")
    up.add_argument("--version", type=int, default=None, help="缺省最新")
    up.add_argument("--execute", action="store_true", help="真传（要 GUJI_DATA_TOKEN 正式令牌）")
    fe = ps.add_parser("fetch", help="本机缺的模型文件从 R2 取回（已有但内容不同的不覆盖；不给 -w 按 cv 的模型表补 models/）")
    fe.add_argument("--version", type=int, default=None, help="缺省最新")
    ps.add_parser("registry", help="按当前 models/ 重写 cv 自带的模型表 config/model-registry.json")
    for q in (ls_, b, v, li, up, fe):
        q.add_argument("-w", "--workspace", default=None, help="工作区（清单落在数据目录 config/model-pack/m<N>/）")
        q.add_argument("--json", action="store_true")


COMMANDS = {"model": (add_parser, cmd_model)}
