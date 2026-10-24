"""`guji freeze register <册>`：冻结登记一次做齐（GUJI-694）。见 `ops/freeze_register.py` 模块头。

缺省只出计划（不存包、不写库、不改 yaml、不打 tag）；`--execute` 才动手。打 1.0 标签与冻结要用户明说（1.0 发布标准 G8）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def cmd_freeze(args) -> None:
    from .core.book import _book_yaml_path
    from .datastore import packs as PK
    from .ops import freeze_register as FR
    from .products.store import default_products_root
    root = Path(args.root).expanduser().resolve() if args.root else default_products_root()
    p = FR.plan(args.book, args.version, text_id=args.text_id, ws_name=PK._ws_name(), products_root=root,
                text_dir=Path(args.text_dir) if args.text_dir else None, note=args.note or "")
    yaml_path = _book_yaml_path(args.book)
    if args.json and not args.execute:
        print(json.dumps(p, ensure_ascii=False, indent=1))
    else:
        r = p["record"]
        print(f"冻结登记计划：{args.book} 文本 {args.version}")
        print(f"  cv {p['cv']['version']}（{(p['cv']['commit'] or '?')[:12]}）　产物包 {r['pack']}（标 main，旁存 baseline.json）")
        print(f"  登记 → {FR.registry_path(args.book)}　yaml → {yaml_path}（freeze.pack={p['label']}，顶层 cv_version）")
        print(f"  tag {r['tag']}　book-text {(r['text_commit'] or '（没给 --text-dir）')[:12]}")
        for pr in p["problems"]:
            print(f"  ✗ {pr}")
    if p["problems"]:
        sys.exit(1)
    if not args.execute:
        print("（只出计划；确认后加 --execute）")
        return
    from .cli_products import book_versions
    done = FR.execute(p, products_root=root, yaml_path=yaml_path, vers=book_versions(args.book, root),
                      tag_via=Path(args.tag_via) if args.tag_via else None)
    print(f"✓ 冻结包 {done['pack']}（{done['files']} 个文件的 sha 记进 baseline.json）")
    print(f"✓ 登记 {done['registry']}；yaml {done['yaml']}")
    if done["tagged"]:
        print(f"✓ tag {done['tag']}")
    elif done["tagged"] is None:
        print(f"· tag 没打：在 ai-team 里跑 {' '.join(repr(x) if ' ' in x else x for x in done['tag_cmd'])}")
    print(f"接着：guji db sync -w <工作区>（yaml 与登记进中心库），再 guji close-check {args.book} 看 1a、guji exit-check 看 E5–E8")


def add_parser(sub) -> None:
    p = sub.add_parser("freeze", help="[v2] 冻结登记：存冻结包＋baseline、登记、改 yaml、打 freeze/ tag（GUJI-694）")
    p.add_argument("action", choices=["register"])
    p.add_argument("book")
    p.add_argument("--version", required=True, help="冻结的文本版本，如 1.0.0")
    p.add_argument("--text-id", required=True, dest="text_id", help="book-text 条目 id（tag 名用），如 96mid1ogzk")
    p.add_argument("--text-dir", default=None, dest="text_dir", help="book-text 本书目录（取 HEAD sha 记进登记）")
    p.add_argument("--root", default=None, help="产物根，缺省本机产物根")
    p.add_argument("--note", default=None)
    p.add_argument("--tag-via", default=None, dest="tag_via", help="ai-team 仓目录：经中转站 process/tag.py 打 tag")
    p.add_argument("--execute", action="store_true", help="真的做（缺省只出计划）")
    p.add_argument("--json", action="store_true")
