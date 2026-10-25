"""guji source：原图（源件 → 页图 → 页表）存取，设计见 doc/design/古籍图片全流程-源件页图管线与IIIF.md。

    guji source pull <册> -w <工作区> [--rev N] [--to 目录]      # 云会话取原图：页表 → CDN → data_full/<册>/（读令牌）
    guji source show <书id> <册> [--rev N]                       # 看页表摘要
    guji source list <书id>                                      # 各册页表版本
    guji source check <书id> <册>                                # 疑似合扫页（宽高比异常），跑管线前看
    guji source ia <书id> <册> --ia <IA 标识> --ws <工作区 id> --book <册名> [--splits 表] --why …
                                                                 # 从 IA 下源件、存档、生成页图、发布页表（正式令牌）
    guji source commons <书id> <册> --file <Commons 文件名> --ws … --book … [--splits 表] --why …
                                                                 # 从 Commons（根）取 DjVu、存档、解页、发布页表（正式令牌，要 ddjvu）
                                                                 # 会话连不上 Commons 时：别处下好 DjVu 与 imageinfo，--djvu 文件 --commons-json 信息
    guji source register <书id> <册> --dir <原图目录> --map <页号→页序表> [--ia <IA 标识> | --src-file <路径>=<网址> …] --ws … --book … --why …
                                                                 # 已有原图目录原样登记（老册，不重编码）（正式令牌）
    guji source replace <书id> <册> <页序> <png> --why …          # 换一页（人工处理后的图），页表出新版（正式令牌）

令牌：`GUJI_DATA_TOKEN`（读：pull/show/list/check；写正式桶：ia/register/replace 要正式令牌）。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path


def _src():
    from .datastore.client import WorkerSource
    return WorkerSource()


def _ws_id() -> str:
    from .datastore.packs import _ws_name
    return _ws_name()


def _actor(args) -> str:
    return args.by or os.environ.get("GUJI_ACTOR") or "unknown"


def _load_splits(path: str | None, vol: str) -> dict[int, list[dict]]:
    """拆页表：`[{vol: "vol03"|"03", ia_leaf: 105, canvas_seq: "0105a", xywh: [...]}, …]`（与 web 仓
    `ops/iiif/siku-zongmu-splits.json` 同形），取本册，按页序排。"""
    if not path:
        return {}
    from .datastore.sources import norm_vol
    out: dict[int, list[dict]] = {}
    for r in json.loads(Path(path).read_text(encoding="utf-8")):
        if norm_vol(r["vol"]) != vol:
            continue
        out.setdefault(int(r["ia_leaf"]), []).append({"part": r["canvas_seq"][-1], "crop": r["xywh"],
                                                      "seq": r["canvas_seq"]})
    for v in out.values():
        v.sort(key=lambda p: p["seq"])
    return out


def _expect(table_pages: list[dict], path: str | None, skip: str | None = None) -> None:
    """`--expect`：产物包里的 `_raw_index.json`（{"<页>.png": {sha256}}）。逐页比，对不上就停，不发布。
    `skip`（`--expect-skip 17,22`）：册配置 `preclean:` 登记过的页，产物记的是修好那张（`precleaned/`）的 sha，
    与原图本来就不同，不比。"""
    if not path:
        return
    idx = json.loads(Path(path).read_text(encoding="utf-8"))
    skipped = {int(x) for x in (skip or "").split(",") if x.strip()}
    bad = [p["page"] for p in table_pages if p["page"] not in skipped
           and (idx.get(f"{p['page']}.png") or {}).get("sha256") != p["sha256"]]
    extra = len(idx) - len(table_pages)
    if bad or extra:
        raise SystemExit(f"✗ 与 {path} 不符：{len(bad)} 页 sha 不同（{bad[:10]}），页数差 {extra}；没发布")
    note = f"（预清理页 {sorted(skipped)} 不比）" if skipped else ""
    print(f"  ✓ {len(table_pages) - len(skipped)} 页与 {Path(path).name} 逐字节相同{note}")


def cmd_pull(args) -> None:
    from .core.book import load_book
    from .datastore import sources as S
    if args.workspace:
        os.environ["GUJI_WORKSPACE"] = str(Path(args.workspace).expanduser().resolve())
    src = _src()
    book_id, vol = (args.book_id, S.norm_vol(args.vol)) if args.book_id else S.resolve(src, _ws_id(), args.book)
    table = S.read_table(src, book_id, vol, args.rev)
    if args.to:
        to = Path(args.to)
        dest = lambda page: to / f"{page}.png"   # noqa: E731
    else:
        dest = load_book(args.book).raw_path
    res = S.pull(src, table, dest)
    where = args.to or str(dest(table["pages"][0]["page"]).parent)
    print(f"✓ {book_id}/{vol} 页表 r{res['rev']:03d}：{res['pages']} 页，新写 {res['written']}，原有 {res['kept']} → {where}")


def cmd_show(args) -> None:
    from .datastore import sources as S
    t = S.read_table(_src(), args.book_id, S.norm_vol(args.vol), args.rev)
    if args.json:
        print(json.dumps(t, ensure_ascii=False, indent=1))
        return
    ops = sum(1 for p in t["pages"] if p.get("ops"))
    print(f"{t['book_id']}/{t['vol']} r{t['rev']:03d}（{t.get('status')}）{t.get('ws')}/{t.get('book')}："
          f"{len(t['pages'])} 页，有处理 {ops} 页；{t.get('by')} {t.get('created')}：{t.get('why')}")
    for s in t.get("sources", []):
        print(f"  源件 {s.get('kind')}:{s['id'] + '/' if s.get('id') else ''}{s.get('name') or s.get('file')} sha256 {s.get('sha256', '')[:12]}… → {s.get('r2')}")
    if t.get("changed"):
        print(f"  本版改动：{', '.join(t['changed'][:20])}{' …' if len(t['changed']) > 20 else ''}")


def cmd_list(args) -> None:
    from .datastore import sources as S
    src = _src()
    keys = S._list(src, f"{S.ROOT}/pages/{args.book_id}/")
    vols: dict[str, list[str]] = {}
    for k in keys:
        _, _, _, vol, name = k.split("/")
        vols.setdefault(vol, []).append(name[:-5])
    for v in sorted(vols):
        print(f"{args.book_id}/{v}: {', '.join(vols[v])}")


def cmd_check(args) -> None:
    from .datastore import sources as S
    t = S.read_table(_src(), args.book_id, S.norm_vol(args.vol), args.rev)
    sus = S.check_pages(t["pages"])
    if not sus:
        print(f"✓ {args.book_id}/{t['vol']} r{t['rev']:03d}：没有疑似合扫页")
        return
    print(f"！{len(sus)} 页宽高比偏大（本册中位 {sus[0]['median']}），疑似合扫，跑管线前人看：")
    for p in sus:
        print(f"  {p['seq']}（cv 第 {p['page']} 页）{p['w']}×{p['h']} 比 {p['ratio']}  "
              f"https://blob.open-guji.com/sha256/{p['sha256'][:2]}/{p['sha256']}.png")


def _finish(src, args, table, blobs, why) -> None:
    from .datastore import sources as S
    if args.dry_run:
        print(f"（dry-run）不发布：{len(table['pages'])} 页，{len(blobs)} 张页图")
        return
    out = S.publish(src, table, blobs, by=_actor(args), why=why)
    if table.get("ws") and table.get("book"):
        S.write_pointer(src, table["ws"], table["book"], table["book_id"], table["vol"])
    print(f"✓ 发布 {out['book_id']}/{out['vol']} r{out['rev']:03d}：{out['n_pages']} 页，改动 {len(out['changed'])} 页")


def cmd_ia(args) -> None:
    from .datastore import sources as S
    vol = S.norm_vol(args.vol)
    src = _src()
    cache = Path(args.cache or Path.home() / ".cache" / "guji-source")
    rec = S.ia_download(args.ia, cache / args.ia)
    print(f"  源件 {rec['file']} {rec['bytes'] / 1e6:.1f} MB md5 ✓")
    if not args.dry_run:
        rec["r2"] = S.store_original(src, args.book_id, vol, rec)
        print(f"  已存 R2 {rec['r2']}")
    pages, blobs = S.build_from_zip(Path(rec["path"]), splits=_load_splits(args.splits, vol))
    print(f"  生成 {len(pages)} 页（{sum(len(b) for b in blobs.values()) / 1e6:.1f} MB）")
    _expect(pages, args.expect, args.expect_skip)
    table = S.new_table(args.book_id, vol, ws=args.ws, book=args.book, sources=[{"key": "s1", **rec}], pages=pages)
    _finish(src, args, table, blobs, args.why)


def cmd_commons(args) -> None:
    import tempfile
    from .datastore import sources as S
    vol = S.norm_vol(args.vol)
    src = _src()
    if args.commons_json:
        info = json.loads(Path(args.commons_json).read_text(encoding="utf-8"))
    else:
        info = S.commons_info(args.file)
    path = Path(args.djvu) if args.djvu else None
    if path is None:
        cache = Path(args.cache or Path.home() / ".cache" / "guji-source") / "commons"
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / info["url"].rsplit("/", 1)[1]
        if not path.exists():
            path.write_bytes(S._http(info["url"], timeout=1800))
    rec = S.commons_source(path, info)
    if args.reroot:                                                  # 同一 Commons 文件的新版本：R2 只增不改，存名带版本时间
        stamp = re.sub(r"[^0-9TZ]", "", info["timestamp"])
        rec["file"] = f"{Path(rec['file']).stem}.{stamp}{Path(rec['file']).suffix}"
    print(f"  源件 {info['title']}（{info['timestamp']}）{rec['bytes'] / 1e6:.1f} MB sha1 ✓")
    if not args.dry_run:
        rec["r2"] = S.store_original(src, args.book_id, vol, rec)
        print(f"  已存 R2 {rec['r2']}")
    with tempfile.TemporaryDirectory() as td:
        z = Path(td) / "leaves.zip"
        n = S.djvu_to_zip(path, z)
        if info.get("pagecount") and n != info["pagecount"]:
            raise SystemExit(f"✗ 解出 {n} 页，Commons 记 {info['pagecount']} 页")
        key = "s1"
        if args.reroot:
            prev = S.read_table(src, args.book_id, vol)
            key = f"s{len(prev['sources']) + 1}"
        pages, blobs = S.build_from_zip(z, source_key=key, splits=_load_splits(args.splits, vol))
    print(f"  生成 {len(pages)} 页（{sum(len(b) for b in blobs.values()) / 1e6:.1f} MB）")
    sources = [{"key": "s1", **rec}]
    if args.reroot:
        from PIL import Image
        from .datastore.client import BlobCache
        cache = BlobCache()
        need = [p["sha256"] for p in prev["pages"] if not cache.has(p["sha256"])]
        if need and cache.ensure(src, need, bucket="main")["missing"]:
            raise SystemExit("✗ R2 上缺旧页表的页图")

        def same(o, n) -> bool:
            if o["sha256"] == n["sha256"]:
                return True
            a, b = (Image.open(io.BytesIO(x)) for x in (cache.path(o["sha256"]).read_bytes(), blobs[n["sha256"]]))
            return S._same(a, b)
        pages, kept = S.reroot_pages(prev, pages, same)
        blobs = {}
        sources = [*prev["sources"], {"key": key, **rec}]
        print(f"  沿用旧页表 r{prev['rev']:03d} 的页序；图不同、保留旧图的页：{', '.join(kept) or '无'}")
    _expect(pages, args.expect, args.expect_skip)
    table = S.new_table(args.book_id, vol, ws=args.ws or (prev.get("ws") if args.reroot else None),
                        book=args.book or (prev.get("book") if args.reroot else None), sources=sources, pages=pages,
                        **({"encoding": prev.get("encoding", S.ENCODING)} if args.reroot else {}), decoder="ddjvu")
    _finish(src, args, table, blobs, args.why)


def cmd_commons_pack(args) -> None:
    """页表里修过的页合进根 DjVu，出回传 Commons 的新版本（设计稿 §十三）。只在本地出文件，不上传。"""
    from .datastore import sources as S
    from .datastore.client import BlobCache
    src = _src()
    t = S.read_table(src, args.book_id, S.norm_vol(args.vol), args.rev)
    root = S.root_source(t)
    n_fix = sum(1 for p in t["pages"] if S.is_fix(p))
    if not n_fix:
        print(f"✓ {t['book_id']}/{t['vol']} r{t['rev']:03d}：没有修过的页，不用回传")
        return
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rp = Path(args.djvu) if args.djvu else out_dir / f"root-{root['file']}"
    if not rp.exists():
        from .datastore import packs as PK
        PK.fetch_file(root["r2"], rp, src=S._MainBucket(src))
    if S.sha256(rp.read_bytes()) != root["sha256"]:
        raise SystemExit(f"✗ 根 {rp} 的 sha256 与页表记的不符")
    cache = BlobCache()
    need = [p["sha256"] for p in t["pages"] if S.is_fix(p) and not cache.has(p["sha256"])]
    if need:
        res = cache.ensure(src, need, bucket="main")
        if res["missing"]:
            raise SystemExit(f"✗ R2 上缺 {len(res['missing'])} 张页图")
    out = out_dir / root["file"]
    res = S.pack_for_commons(t, rp, lambda sha: cache.path(sha).read_bytes(), out)
    comment = S.commons_comment(t, res)
    info = {"commons_title": root.get("commons_title"), "replaces_sha1": root.get("commons_sha1"),
            "replaces_timestamp": root.get("commons_timestamp"), "file": str(out), "table_rev": t["rev"],
            "comment": comment, **res}
    (out_dir / f"{Path(root['file']).stem}.upload.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"✓ {out}（{res['bytes'] / 1e6:.1f} MB，{res['pages_before']}→{res['pages_after']} 页，逐页解码核过）")
    print(f"  传到：{root.get('commons_title')}（上传新版本）")
    print(f"  摘要：{comment}")


def cmd_register(args) -> None:
    from .datastore import sources as S
    vol = S.norm_vol(args.vol)
    src = _src()
    m = json.loads(Path(args.map).read_text(encoding="utf-8"))      # {"<cv 页号>": {"seq": …, "src": …, "ops": […]}}
    seq = {int(k): v["seq"] for k, v in m.items()}
    sources = []
    if args.ia:
        cache = Path(args.cache or Path.home() / ".cache" / "guji-source")
        rec = S.ia_download(args.ia, cache / args.ia)
        if not args.dry_run:
            rec["r2"] = S.store_original(src, args.book_id, vol, rec)
        sources.append({"key": "s1", **rec})
    for spec in args.src_file or []:                                 # 非 IA 源件：<路径>[=<网址>]
        path, _, url = spec.partition("=")
        rec = S.local_source(Path(path), url)
        if not args.dry_run:
            rec["r2"] = S.store_original(src, args.book_id, vol, rec)
            print(f"  源件 {rec['file']} 已存 R2 {rec['r2']}")
        sources.append({"key": f"s{len(sources) + 1}", **rec})
    pages, blobs = S.register_local(Path(args.dir), seq, pattern=args.pattern,
                                    src_of_page={int(k): v.get("src", "") for k, v in m.items()},
                                    ops_of_page={int(k): v.get("ops", []) for k, v in m.items()})
    _expect(pages, args.expect, args.expect_skip)
    table = S.new_table(args.book_id, vol, ws=args.ws, book=args.book, sources=sources, pages=pages,
                        encoding="as-is", page_numbering="keep" if args.keep_numbering else None)
    if table["page_numbering"] is None:
        del table["page_numbering"]
    _finish(src, args, table, blobs, args.why)


def cmd_replace(args) -> None:
    from .datastore import sources as S
    src = _src()
    t = S.read_table(src, args.book_id, S.norm_vol(args.vol))
    new, blobs = S.with_page(t, args.seq, Path(args.png).read_bytes(), args.why, _actor(args))
    for k in ("rev", "prev", "prev_sha256", "created", "by", "why", "changed", "n_pages"):
        new.pop(k, None)
    _finish(src, args, new, blobs, args.why)


COMMANDS = {"commons-pack": cmd_commons_pack, "pull": cmd_pull, "show": cmd_show, "list": cmd_list, "check": cmd_check,
            "ia": cmd_ia, "commons": cmd_commons, "register": cmd_register, "replace": cmd_replace}


def add_parser(sub) -> None:
    p = sub.add_parser("source", help="[v2] 原图：源件存档、页图、页表（R2），云会话取原图")
    p.add_argument("action", choices=sorted(COMMANDS))
    p.add_argument("pos", nargs="*", help="pull：<册>；show/check/ia/commons/commons-pack/register：<书id> <册>；list：<书id>；replace：<书id> <册> <页序> <png>")
    p.add_argument("-w", "--workspace", default=None, help="pull：工作区（定册配置里的原图目录）")
    p.add_argument("--rev", type=int, default=None, help="页表版本，缺省最新")
    p.add_argument("--to", default=None, help="pull：落到这个目录（<页>.png），不按册配置")
    p.add_argument("--book-id", default=None, help="pull：不查登记，直接给书 id（配 --vol）")
    p.add_argument("--vol", default=None, help="pull：配 --book-id")
    p.add_argument("--ia", default=None, help="ia/register：IA 标识，如 06061310.cn")
    p.add_argument("--file", default=None, help="commons：Commons 文件名（不带 File: 也行）")
    p.add_argument("--djvu", default=None, help="commons：本地已下好的源件（会话连不上 Commons 时）")
    p.add_argument("--commons-json", default=None, help="commons：配 --djvu，Commons imageinfo（title/url/sha1/timestamp/pagecount）")
    p.add_argument("--ws", default=None, help="ia/register：cv 工作区 id（写 by-ws 指针）")
    p.add_argument("--book", dest="book_name", default=None, help="ia/register：cv 册名，如 vol11")
    p.add_argument("--splits", default=None, help="ia：拆页表（同 web 仓 siku-zongmu-splits.json）")
    p.add_argument("--expect", default=None, help="ia/register：产物包里的 _raw_index.json，逐页核 sha，不符不发布")
    p.add_argument("--expect-skip", default=None, help="ia/register：不比的 cv 页号（册配置 preclean 登记的页），逗号分隔")
    p.add_argument("--src-file", action="append", default=None,
                   help="register：非 IA 源件 <路径>[=<网址>]，可多次（按次序记作 s1、s2…，--map 的 src 引这些键）")
    p.add_argument("--dir", default=None, help="register：已有原图目录")
    p.add_argument("--map", default=None, help="register：{cv 页号: {seq, src, ops}} 的 json")
    p.add_argument("--pattern", default="{page}.png", help="register：原图文件名")
    p.add_argument("--keep-numbering", action="store_true", help="register：cv 页号不连续时照留")
    p.add_argument("--cache", default=None, help="源件下载缓存目录，缺省 ~/.cache/guji-source")
    p.add_argument("--why", default="", help="写：为什么（进页表）")
    p.add_argument("--by", default=None, help="写：谁（缺省 GUJI_ACTOR）")
    p.add_argument("--dry-run", action="store_true", help="写：只算不传")
    p.add_argument("--json", action="store_true", help="show：整份页表")
    p.add_argument("--out", default=None, help="commons-pack：输出目录（新版 DjVu 与 .upload.json）")
    p.add_argument("--reroot", action="store_true",
                   help="commons：修好的版本已传上 Commons，按旧页表逐页对上，沿用页序（页 id 不变）")


def cmd_source(args) -> None:
    pos = list(args.pos or [])
    a = args.action
    need = {"pull": 1, "list": 1, "show": 2, "check": 2, "ia": 2, "commons": 2, "commons-pack": 2, "register": 2, "replace": 4}[a]
    if a == "pull" and args.book_id:
        need = 0
    if len(pos) < need:
        print(f"✗ 用法见 guji source --help（{a} 要 {need} 个位置参数）", file=sys.stderr)
        sys.exit(2)
    if a == "pull":
        args.book = pos[0] if pos else None
    elif a == "list":
        args.book_id = pos[0]
    else:
        args.book_id, args.vol = pos[0], pos[1]
        if a == "replace":
            args.seq, args.png = pos[2], pos[3]
    if a in ("ia", "commons", "register"):
        args.book = args.book_name
        if not args.why:
            print("✗ 写页表要 --why", file=sys.stderr)
            sys.exit(2)
        if a == "register" and not (args.dir and args.map):
            print("✗ register 要 --dir 与 --map", file=sys.stderr)
            sys.exit(2)
        if a == "commons" and not (args.file or args.commons_json):
            print("✗ commons 要 --file <Commons 文件名>（或 --djvu 配 --commons-json）", file=sys.stderr)
            sys.exit(2)
        if a == "ia" and not args.ia:
            print("✗ ia 要 --ia <IA 标识>", file=sys.stderr)
            sys.exit(2)
    if a == "commons-pack" and not args.out:
        print("✗ commons-pack 要 --out <目录>", file=sys.stderr)
        sys.exit(2)
    if a == "replace" and not args.why:
        print("✗ replace 要 --why", file=sys.stderr)
        sys.exit(2)
    COMMANDS[a](args)
