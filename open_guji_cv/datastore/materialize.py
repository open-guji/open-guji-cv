"""从中心库还原工作区文件（GUJI-606 ``guji db pull`` 的前半段，也是日后「git 改每日导出」的底子）。

还原规则与 ``verify`` 相同：逐行表按 ``src_line`` 拼回，整文件表取 ``raw``，空文件与文件末尾
换行靠 ``source_files``；每个文件写完核一次整文件 sha256，对不上就整次报错，不留半成品。
刻例图按 ``glyph_instances.patch_sha`` 从本地缓存（缺的经 Worker 从 R2 拉）落到
``patches/<实例 id，':' 换成 '_'>.png``；锚图按 ``anchor_patches_meta`` 落回原路径。
"""

from __future__ import annotations

import os
import shutil
from collections import defaultdict
from pathlib import Path

from .scope import GS, sha256

WHOLE_TABLES = ("workspaces", "books", "files")
NOT_LINE = set(WHOLE_TABLES) | {"source_files", "anchor_patches_meta"}


class MaterializeError(RuntimeError):
    pass


def _safe(instance_id: str) -> str:            # 同 clustering.glyph_db._safe
    return instance_id.replace(":", "_")


def materialize(src, ws: str, dest: str | Path, prefixes: tuple[str, ...] = (GS,),
                cache=None, bucket: str = "main", with_images: bool = True) -> dict:
    """把工作区 ``ws`` 里路径以 ``prefixes`` 之一开头的文件还原到 ``dest``（目录结构同工作区）。

    ``dest`` 下原有的同前缀目录先清空，保证不残留库里已经没有的文件。返回统计。
    """
    dest = Path(dest)
    sel = lambda p: any(p.startswith(x) for x in prefixes)
    files = {r["src_path"]: r for r in src.rows("source_files", ws) if sel(r["src_path"])}
    if not files:
        raise MaterializeError(f"库里工作区 {ws} 没有 {'、'.join(prefixes)} 下的文件")

    by_tbl: dict[str, list[str]] = defaultdict(list)
    for p, f in files.items():
        by_tbl[f["tbl"]].append(p)

    texts: dict[str, bytes] = {}
    for tbl, paths in sorted(by_tbl.items()):
        want = set(paths)
        if tbl == "anchor_patches_meta":
            continue
        if tbl in WHOLE_TABLES:
            for r in src.rows(tbl, ws):
                if r["src_path"] in want:
                    texts[r["src_path"]] = r["raw"].encode("utf-8")
            continue
        lines: dict[str, dict[int, str]] = defaultdict(dict)
        for r in src.rows(tbl, ws):
            if r["src_path"] in want:
                lines[r["src_path"]][int(r["src_line"])] = r["raw"]
        for p in paths:
            f = files[p]
            have = lines.get(p, {})
            n = int(f["n_lines"])
            extra = [i for i in have if i >= n]
            if extra:
                raise MaterializeError(f"{p}: 库里有超出 n_lines 的行 {sorted(extra)[:5]}")
            text = "\n".join(have.get(i, "") for i in range(n)) + ("\n" if f["final_newline"] else "")
            texts[p] = text.encode("utf-8")

    bad = [p for p, b in texts.items()
           if sha256(b) != files[p]["sha256"] or len(b) != int(files[p]["bytes"])]
    missing = [p for p, f in files.items() if f["tbl"] != "anchor_patches_meta" and p not in texts]
    if bad or missing:
        raise MaterializeError(f"还原后 sha 不符 {len(bad)} 个（如 {bad[:3]}），缺 {len(missing)} 个（如 {missing[:3]}）")

    # 图：刻例图（只在还原字形库时）＋锚图（只在还原 feedback/ 时）
    images: dict[str, str] = {}                      # 相对路径 → sha
    if with_images and sel(GS + "patches/"):
        for r in src.rows("glyph_instances", ws):
            if r.get("patch_sha"):
                images[f"{GS}patches/{_safe(r['instance_id'])}.png"] = r["patch_sha"]
    if with_images:
        for p, f in files.items():
            if f["tbl"] == "anchor_patches_meta":
                images[p] = f["sha256"]
    img_stats = {}
    if images:
        if cache is None:
            from .client import BlobCache
            cache = BlobCache()
        img_stats = cache.ensure(src, images.values(), bucket=bucket)

    # 落盘：先写进临时目录，全部成功再换上去
    tmp = dest.with_name(dest.name + f".tmp{os.getpid()}")
    if tmp.exists():
        shutil.rmtree(tmp)
    for p, b in texts.items():
        out = tmp / p
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b)
    for p, sha in images.items():
        out = tmp / p
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cache.path(sha), out)
    dest.mkdir(parents=True, exist_ok=True)
    tops = {x.rstrip("/").split("/")[0] for x in prefixes}
    for top in tops:
        if (tmp / top).exists():
            for prefix in prefixes:
                if prefix.split("/")[0] != top:
                    continue
                old = dest / prefix.rstrip("/")
                if old.exists():
                    shutil.rmtree(old) if old.is_dir() else old.unlink()
                new = tmp / prefix.rstrip("/")
                if new.exists():
                    old.parent.mkdir(parents=True, exist_ok=True)
                    new.replace(old)
    shutil.rmtree(tmp, ignore_errors=True)
    return {"ws": ws, "files": len(texts), "images": len(images),
            "image_cache": img_stats, "bytes": sum(len(b) for b in texts.values())}
