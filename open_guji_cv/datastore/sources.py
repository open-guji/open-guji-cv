"""原图：源件存档、页图按 sha 存 R2、页表（`guji-pages/1`）、管线取图。

设计：`doc/design/古籍图片全流程-源件页图管线与IIIF.md`（2026-10-23 用户定案）。
一句话：**页图是唯一真源**，cv 管线（`data_full/`）和网站书影（COS 上的 IIIF）都从它派生。

R2 正式桶的布局（全部经 guji-data Worker，按名字只增不改）::

    pack/source/orig/<书id>/<册>/<源件文件名>/{part-NNN, manifest.json}   源件原样（`packs.push_file`）
    sha256/<前两位>/<sha>.png                                               页图（按哈希公开，blob.open-guji.com）
    pack/source/pages/<书id>/<册>/r<NNN>.json                               页表，每改一次出一版，只增不改
    pack/source/by-ws/<工作区>/<册名>.json                                  cv 的册 → (书id, 册) 指针

- 书 id 是 book-index id（如 `96mid1ogzk`）；册是两位数（`11`），与 IIIF 路径同；cv 的册名照旧（`vol11`）。
- 页序 seq（全链路唯一的页 id）沿用 IIIF 已在用的口径：源件里的叶号补零 4 位，合扫拆页加 a–d（`0105a`）。
- cv 页号 `page` 照旧连续整数（`p0105`），页表一行同时写 seq 与 page。
- 「覆盖」一页＝页表出新版、指向新 sha；旧字节不删，旧产物能复现。页数变（拆页）会让后面的页号整体后移，
  该册 Step1 起全过期（L3），所以合扫检查要在跑管线之前做完（`check`）。

页图编码（`ENCODING`）：源图 `convert("RGB")` 后 Pillow 缺省参数存 PNG。殿本 vol11–20 线上产物用的原图
（产物包 `_raw_index.json` 记的 sha）就是这样从 IA `_tif.zip` 转出来的，逐字节相同（2026-10-23 逐册核过）。
已在 git 里的老册（vol01–10）不重编码，原样登记（`register_local`），产物不过期。

令牌：取（`pull`、`show`、`list`）读令牌就够；写正式桶（源件、页图、页表、指针）要正式令牌。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import re
import time
import urllib.parse
from pathlib import Path

SCHEMA = "guji-pages/1"
ENCODING = "pillow-rgb-png/1"            # 页图编码口径：Image.convert("RGB").save(PNG)，Pillow 缺省参数
ROOT = "source"
SEQ_RE = re.compile(r"^\d{4}[a-z]?$")
BOOK_ID_RE = re.compile(r"^[0-9a-z]{6,16}$")
VOL_RE = re.compile(r"^\d{2,3}$")
IA_ORDER = ("_tif.zip", "_cnbook.zip", "_jp2.zip")   # 同 scripts/ia_download_zongmu.py：tif 与工作区原图逐像素一致


class TableConflict(RuntimeError):
    """别人先发布了同一版号（Worker 回 409）：重新读最新版，在它上面改。"""


# ─── R2 键 ───────────────────────────────────────────────────────────────

def _check_ids(book_id: str, vol: str) -> None:
    if not BOOK_ID_RE.match(book_id or ""):
        raise ValueError(f"书 id 不合法：{book_id!r}（book-index id，如 96mid1ogzk）")
    if not VOL_RE.match(vol or ""):
        raise ValueError(f"册号不合法：{vol!r}（两位数字，如 11）")


def orig_key(book_id: str, vol: str, filename: str) -> str:
    _check_ids(book_id, vol)
    return f"{ROOT}/orig/{book_id}/{vol}/{filename}"


def table_prefix(book_id: str, vol: str) -> str:
    _check_ids(book_id, vol)
    return f"{ROOT}/pages/{book_id}/{vol}/"


def table_key(book_id: str, vol: str, rev: int) -> str:
    return f"{table_prefix(book_id, vol)}r{rev:03d}.json"


def pointer_key(ws: str, book: str) -> str:
    return f"{ROOT}/by-ws/{ws}/{book}.json"


def norm_vol(vol) -> str:
    """`11`、`vol11`、11 → `11`。"""
    m = re.search(r"(\d+)$", str(vol))
    if not m:
        raise ValueError(f"认不出册号：{vol!r}")
    return f"{int(m.group(1)):02d}"


def leaf_seq(leaf: int, part: str = "") -> str:
    return f"{leaf:04d}{part}"


# ─── Worker 调用（/v1/packs） ─────────────────────────────────────────────

def _client():
    from .client import WorkerSource
    return WorkerSource()


def _get(src, key: str) -> bytes:
    return src._call("GET", "/v1/packs/" + urllib.parse.quote(key), query={"bucket": "main"}, raw=True)


def _put(src, key: str, data: bytes, content_type: str = "application/json") -> None:
    from .client import CentralError
    try:
        src._call("PUT", "/v1/packs/" + urllib.parse.quote(key), query={"bucket": "main"}, data=data,
                  content_type=content_type, tries=3)
    except CentralError as e:
        if e.status == 409:
            raise TableConflict(f"{key} 已存在（只增不改）") from None
        raise


def _list(src, prefix: str) -> list[str]:
    rows = src._call("GET", "/v1/packs", query={"bucket": "main", "prefix": prefix})["packs"]
    return sorted(r["key"] for r in rows)


def _exists(src, key: str) -> bool:
    return key in _list(src, key)


# ─── 页图编码与处理 ───────────────────────────────────────────────────────

def encode_page(im) -> bytes:
    """页图编码（见模块头 ENCODING）。确定性：同一张源图、同一 Pillow 主版本，字节相同。"""
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def apply_ops(im, ops: list[dict]):
    """可复现的处理：`{"crop": [x, y, w, h]}`（源图坐标）、`{"rotate": 90|180|270}`（顺时针）。
    `{"manual": "说明"}` 是人工处理后上传的整张图，build 不能复现，这里跳过（字节在页表里按 sha 取）。"""
    for op in ops or []:
        if "crop" in op:
            x, y, w, h = (int(v) for v in op["crop"])
            im = im.crop((x, y, x + w, y + h))
        elif "rotate" in op:
            deg = int(op["rotate"]) % 360
            if deg not in (0, 90, 180, 270):
                raise ValueError(f"只支持 90 的倍数旋转：{op}")
            if deg:
                im = im.rotate(-deg, expand=True)
        elif "manual" in op:
            continue
        else:
            raise ValueError(f"不认识的处理：{op}")
    return im


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG")
    import struct
    return struct.unpack(">II", data[16:24])


# ─── 源件：IA ────────────────────────────────────────────────────────────

def _http(url: str, timeout: float = 120) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"user-agent": "open-guji-cv-source"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def ia_pick(meta: dict) -> dict:
    files = meta.get("files") or []
    for suf in IA_ORDER:
        for f in files:
            if f.get("name", "").endswith(suf):
                return f
    raise FileNotFoundError(f"IA 条目里没有 {' / '.join(IA_ORDER)}")


def ia_download(ia_id: str, dest_dir: Path, retries: int = 3) -> dict:
    """下 IA 条目的源件（缺省 `_tif.zip`）到 `dest_dir`，核 IA 给的 md5，返回来源记录（页表 `sources[]` 一行）。
    本机已有且 md5 对得上就不再下。"""
    meta = json.loads(_http(f"https://archive.org/metadata/{ia_id}"))
    f = ia_pick(meta)
    name = f["name"]
    url = f"https://archive.org/download/{ia_id}/{urllib.parse.quote(name)}"
    dest = Path(dest_dir) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    md5 = f.get("md5")
    for attempt in range(retries):
        if dest.exists() and (not md5 or hashlib.md5(dest.read_bytes()).hexdigest() == md5):
            break
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            tmp.write_bytes(_http(url, timeout=1800))
            tmp.replace(dest)
        except Exception:          # noqa: BLE001 —— 退避重试，最后一次照抛
            tmp.unlink(missing_ok=True)
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt * 5)
    data = dest.read_bytes()
    if md5 and hashlib.md5(data).hexdigest() != md5:
        raise ValueError(f"{name} 的 md5 与 IA 记录不符，不用")
    return {"kind": "ia", "id": ia_id, "file": name, "url": url, "source_md5": md5,
            "sha256": sha256(data), "bytes": len(data), "path": str(dest),
            "fetched_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def _ascii_name(name: str, sha: str) -> str:
    """R2 键只收 ASCII（Worker 拒中文前缀）：`NLC403-…-15647_北行日錄_卷一.pdf` → `NLC403-…-15647.pdf`；
    `CADAL06061320 欽定四庫全書總目·卷四十三~卷四十四.djvu` → `CADAL06061320.djvu`；一个 ASCII 字都没有就用 sha 头。"""
    p = Path(name)
    stem = re.sub(r"_+$", "", re.sub(r"[^A-Za-z0-9.-]+", "_", p.stem)).strip("_.") or sha[:16]
    return stem + re.sub(r"[^A-Za-z0-9.]", "", p.suffix.lower())


def local_source(path: Path, url: str = "", kind: str = "file") -> dict:
    """手边已有的源件（国图／Commons 的 PDF、DjVu 等）→ 来源记录，与 `ia_download` 同形。"""
    path = Path(path)
    data = path.read_bytes()
    s = sha256(data)
    return {"kind": kind, "file": _ascii_name(path.name, s), "name": path.name, "url": url, "sha256": s, "bytes": len(data),
            "path": str(path), "fetched_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def commons_info(title: str) -> dict:
    """Commons 文件当前版本：{title, url, sha1, size, timestamp, pagecount}。`title` 不带 `File:` 也行。"""
    t = title if title.startswith("File:") else f"File:{title}"
    q = urllib.parse.urlencode({"action": "query", "format": "json", "formatversion": 2, "titles": t,
                                "prop": "imageinfo", "iiprop": "url|sha1|size|timestamp"})
    page = json.loads(_http(f"{COMMONS_API}?{q}"))["query"]["pages"][0]
    if "imageinfo" not in page:
        raise FileNotFoundError(f"Commons 没有 {t}")
    ii = page["imageinfo"][0]
    return {"title": page["title"], "url": ii["url"].split("?", 1)[0], "sha1": ii["sha1"], "size": ii["size"],
            "timestamp": ii["timestamp"], "pagecount": ii.get("pagecount")}


def commons_source(path: Path, info: dict) -> dict:
    """手边的 Commons 源件（DjVu／PDF）→ 来源记录。核 Commons 给的 sha1，版本钉在 `commons_timestamp`。
    Commons 是根（设计稿第十二节）：R2 里这份是根的镜像，IA 等是另一份镜像。"""
    data = Path(path).read_bytes()
    if hashlib.sha1(data).hexdigest() != info["sha1"]:
        raise ValueError(f"{path} 与 Commons {info['title']} 当前版本 sha1 不符")
    rec = local_source(path, "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(info["title"].replace(" ", "_")),
                       kind="commons")
    # R2 里按 Commons 文件名存（ASCII 部分，如 `CADAL06061320.djvu`），不看本地文件叫什么
    name = info["title"].split(":", 1)[-1]
    rec["file"] = _ascii_name(name, rec["sha256"])
    rec.update(name=name, commons_title=info["title"], commons_sha1=info["sha1"], commons_timestamp=info["timestamp"],
               commons_url=info["url"])
    return rec


def djvu_to_zip(djvu: Path, dest_zip: Path) -> int:
    """DjVu 每页用 `ddjvu` 原尺寸解成 TIFF（JB2 黑白页解出 1-bit，与 IA `_tif.zip` 逐像素相同），打成叶 zip
    （`<名>_<叶号4位>.tif`），交给 `build_from_zip`。返回页数。要装 djvulibre（`ddjvu`、`djvused`）。"""
    import subprocess
    import tempfile
    import zipfile
    n = int(subprocess.run(["djvused", "-e", "n", str(djvu)], capture_output=True, text=True, check=True).stdout)
    stem = re.sub(r"[^A-Za-z0-9-]+", "_", Path(djvu).stem).strip("_") or "djvu"
    with tempfile.TemporaryDirectory() as td, zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_STORED) as z:
        for i in range(1, n + 1):
            tif = Path(td) / "p.tif"
            subprocess.run(["ddjvu", "-format=tiff", f"-page={i}", str(djvu), str(tif)], check=True)
            z.write(tif, f"{stem}_{i:04d}.tif")
    return n


# ─── 修好的页回传 Commons（设计稿 §十三）────────────────────────────────

def djvu_count(djvu: Path) -> int:
    import subprocess
    return int(subprocess.run(["djvused", "-e", "n", str(djvu)], capture_output=True, text=True, check=True).stdout)


def djvu_dpi(djvu: Path, page: int) -> int:
    """第 page 页 INFO 块里的 dpi（新编的页沿用，免得 Commons 上显示尺寸跳）。"""
    import subprocess
    out = subprocess.run(["djvused", "-e", f"select {page}; dump", str(djvu)],
                         capture_output=True, text=True, check=True).stdout
    m = re.search(r"INFO \[\d+\]\s+DjVu \d+x\d+, v\d+, (\d+) dpi", out)
    return int(m.group(1)) if m else 300


def is_fix(page: dict) -> bool:
    """给读者看的修正（要回传 Commons）：拆页（seq 带 a–d）、`crop`／`rotate`、`guji source replace` 换的整张图
    （`manual` 带 `by`）。不带 `by` 的 `manual` 是登记时的存档说明（如书脊签缩小存档），回传时用根的原页。"""
    if len(page["seq"]) > 4:
        return True
    return any("crop" in o or "rotate" in o or ("manual" in o and o.get("by")) for o in page.get("ops") or [])


def root_source(table: dict) -> dict:
    """页表的根：最后一个 `kind=commons` 的源件。"""
    roots = [s for s in table.get("sources", []) if s.get("kind") == "commons"]
    if not roots:
        raise ValueError(f"{table['book_id']}/{table['vol']} r{table['rev']:03d} 没有 Commons 根，先 guji source commons 登记")
    return roots[-1]


def fix_groups(table: dict, n_root: int) -> list[tuple[int, list[dict]]]:
    """页表按根的叶号（seq 前 4 位）分组，核对每一叶都在、次序不乱；返回含修正的组 `[(叶号, [页…])]`。"""
    leaves: list[tuple[int, list[dict]]] = []
    for p in table["pages"]:
        leaf = int(p["seq"][:4])
        if leaves and leaves[-1][0] == leaf:
            leaves[-1][1].append(p)
        else:
            leaves.append((leaf, [p]))
    got = [leaf for leaf, _ in leaves]
    if got != list(range(1, n_root + 1)):
        miss = sorted(set(range(1, n_root + 1)) - set(got))
        raise ValueError(f"页表的叶与根对不上（根 {n_root} 叶；缺 {miss[:5]}，或有重复／乱序）：删叶、换序的回传还不支持")
    return [(leaf, ps) for leaf, ps in leaves if len(ps) > 1 or any(is_fix(p) for p in ps)]


def encode_djvu_page(png: bytes, dpi: int, out: Path) -> None:
    """一页 PNG → 单页 DjVu。黑白页 `cjb2`（无损 JB2），灰度／彩色页 `c44`（IW44，有损，同 #125 首页做法）。
    页图一律存成 RGB PNG（`encode_page`），所以按内容判黑白：只有纯黑纯白两种像素就当黑白页。"""
    import subprocess
    from PIL import Image
    im = Image.open(io.BytesIO(png))
    im.load()
    if im.mode != "1":
        colors = im.convert("RGB").getcolors(3)
        if colors is not None and {c for _, c in colors} <= {(0, 0, 0), (255, 255, 255)}:
            im = im.convert("L").point(lambda v: 255 if v else 0).convert("1", dither=Image.Dither.NONE)
    if im.mode == "1":
        tmp, cmd = out.with_suffix(".pbm"), ["cjb2", "-dpi", str(dpi)]
    else:
        im = im.convert("RGB" if im.mode in ("RGB", "RGBA", "P") else "L")
        tmp, cmd = out.with_suffix(".ppm" if im.mode == "RGB" else ".pgm"), ["c44", "-dpi", str(dpi)]
    im.save(tmp)
    subprocess.run([*cmd, str(tmp), str(out)], check=True, capture_output=True)
    tmp.unlink()


def _decoded(djvu: Path, page: int, td: Path):
    import subprocess
    from PIL import Image
    tif = td / "cmp.tif"
    subprocess.run(["ddjvu", "-format=tiff", f"-page={page}", str(djvu), str(tif)], check=True)
    im = Image.open(tif)
    im.load()
    return im


def _same(a, b) -> bool:
    return a.size == b.size and a.convert("L").tobytes() == b.convert("L").tobytes()


def pack_for_commons(table: dict, root: Path, png_of_sha, out: Path) -> dict:
    """根 DjVu ＋ 页表里修过的页 → 回传 Commons 用的新版 DjVu。

    只动含修正的叶：`djvm -d` 删掉根的这一叶，`djvm -i` 在原位插入页表里的页（从后往前，前面的页号不受影响）；
    其余页的字节原样保留。写完逐页 `ddjvu` 解码核对：修过的页与页表 PNG 逐像素相同，其余页与根逐像素相同。
    `png_of_sha(sha) -> bytes`。返回 {pages_before, pages_after, changes: [{leaf, seqs, pages}], sha1, bytes}。"""
    import hashlib
    import shutil
    import subprocess
    import tempfile
    n_root = djvu_count(root)
    groups = fix_groups(table, n_root)
    shutil.copyfile(root, out)
    with tempfile.TemporaryDirectory() as tdn:
        td = Path(tdn)
        for leaf, ps in reversed(groups):
            dpi = djvu_dpi(root, leaf)
            subprocess.run(["djvm", "-d", str(out), str(leaf)], check=True)
            for j, p in enumerate(ps):
                one = td / f"fix{p['seq']}.djvu"
                encode_djvu_page(png_of_sha(p["sha256"]), dpi, one)
                subprocess.run(["djvm", "-i", str(out), str(one), str(leaf + j)], check=True)
                one.unlink()
        if djvu_count(out) != len(table["pages"]):
            raise RuntimeError(f"新 DjVu {djvu_count(out)} 页 ≠ 页表 {len(table['pages'])} 页")
        fixed = {p["seq"] for _, ps in groups for p in ps}
        for i, p in enumerate(table["pages"], 1):
            got = _decoded(out, i, td)
            if p["seq"] in fixed:
                from PIL import Image
                want = Image.open(io.BytesIO(png_of_sha(p["sha256"])))
            else:
                want = _decoded(root, int(p["seq"][:4]), td)
            if not _same(got, want):
                raise RuntimeError(f"第 {i} 页（{p['seq']}）解码与{'页表' if p['seq'] in fixed else '根'}不一致")
    data = out.read_bytes()
    pos = {p["seq"]: i for i, p in enumerate(table["pages"], 1)}
    return {"pages_before": n_root, "pages_after": len(table["pages"]),
            "changes": [{"leaf": leaf, "seqs": [p["seq"] for p in ps], "pages": [pos[p["seq"]] for p in ps],
                         "ops": [p.get("ops") or [] for p in ps]} for leaf, ps in groups],
            "sha1": hashlib.sha1(data).hexdigest(), "bytes": len(data)}


def commons_comment(table: dict, res: dict) -> str:
    """Commons「上传新版本」的摘要（中英各一句，每处改动一条）。"""
    zh, en = [], []
    for c in res["changes"]:
        n, leaf = len(c["seqs"]), c["leaf"]
        if n > 1:
            zh.append(f"原第{leaf}页为未裁开的合扫，拆为{n}页（新第{c['pages'][0]}–{c['pages'][-1]}页）")
            en.append(f"split uncut multi-leaf scan p.{leaf} into {n} pages (new pp.{c['pages'][0]}-{c['pages'][-1]})")
        else:
            zh.append(f"第{leaf}页修正（{'、'.join(next(iter(o)) for o in c['ops'][0]) or '换图'}）")
            en.append(f"fixed p.{leaf}")
    pages = f"{res['pages_before']}→{res['pages_after']}"
    return (f"{'；'.join(zh)}；页数 {pages}；其余页逐字节未动。"
            f" / {'; '.join(en)}; pages {pages}; all other pages byte-identical. (open-guji page table "
            f"{table['book_id']}/{table['vol']} r{table['rev']:03d})")


def reroot_pages(prev: dict, new_pages: list[dict], same) -> tuple[list[dict], list[str]]:
    """修好的版本传上 Commons 以后重登记：新根第 i 页对应旧页表第 i 页。**页图字节一律沿用旧页表**（产物不过期）；
    `same(旧页, 新页) -> bool` 逐像素相同的页 src 改指新根、ops 清空（修正已在根里）；不同的（如书脊签）原样保留。
    返回 (页, 保留原样的 seq)。"""
    old = prev["pages"]
    if len(old) != len(new_pages):
        raise ValueError(f"新根 {len(new_pages)} 页 ≠ 旧页表 {len(old)} 页，不是同一版修好的整册")
    out, kept = [], []
    for o, n in zip(old, new_pages):
        if same(o, n):
            out.append({**o, "src": n["src"], "ops": []})
        else:
            out.append(dict(o))
            kept.append(o["seq"])
    return out, kept


def store_original(src, book_id: str, vol: str, rec: dict) -> str:
    """源件原样存 R2（已有就跳过，核 sha）。返回 R2 键（不含 `pack/`）。"""
    from . import packs as PK
    key = orig_key(book_id, vol, rec["file"])
    if _exists(src, f"{key}/manifest.json"):
        man = json.loads(_get(src, f"{key}/manifest.json"))
        if man.get("sha256") != rec["sha256"]:
            raise ValueError(f"R2 里已有 {key}，但 sha 不同（{man.get('sha256')} ≠ {rec['sha256']}）；源件只增不改，换文件名")
        return key
    PK.push_file(key, Path(rec["path"]), src=_MainBucket(src))
    return key


class _MainBucket:
    """让 `packs.push_file` 写正式桶（它按分支选桶；这里固定 main）。"""
    branch = "main"

    def __init__(self, src):
        self._src = src

    def _call(self, *a, **kw):
        return self._src._call(*a, **kw)


def zip_leaves(zip_path: Path) -> list[str]:
    """源件 zip 里的叶，按文件名排序（IA 文件名 `<id>_<叶号4位>.tif`，排序即叶序）。"""
    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        return sorted(n for n in z.namelist() if n.lower().endswith((".tif", ".tiff", ".jp2", ".png", ".jpg")))


def _leaf_no(name: str, fallback: int) -> int:
    m = re.search(r"_(\d{3,5})\.\w+$", name)
    return int(m.group(1)) if m else fallback


# ─── 生成页图 ─────────────────────────────────────────────────────────────

def build_from_zip(zip_path: Path, source_key: str = "s1", splits: dict[int, list[dict]] | None = None,
                   leaf_ops: dict[int, list[dict]] | None = None, skip: set[int] | None = None) -> tuple[list[dict], dict[str, bytes]]:
    """源件 zip → 页表的 `pages` 与 `{sha: 页图字节}`。

    `splits`：`{叶号: [{"part": "a", "crop": [x,y,w,h]}, …]}` 合扫叶拆成几页（按列出的顺序）；
    `leaf_ops`：`{叶号: [处理…]}` 整叶旋转等；`skip`：不出页的叶（如重复扫描）。
    cv 页号从 1 起连续编。"""
    import zipfile
    from PIL import Image
    splits, leaf_ops, skip = splits or {}, leaf_ops or {}, skip or set()
    pages: list[dict] = []
    blobs: dict[str, bytes] = {}
    with zipfile.ZipFile(zip_path) as z:
        for i, name in enumerate(zip_leaves(zip_path), 1):
            leaf = _leaf_no(name, i)
            if leaf in skip:
                continue
            im = Image.open(io.BytesIO(z.read(name)))
            im.load()
            base_ops = list(leaf_ops.get(leaf, []))
            parts = splits.get(leaf) or [{"part": ""}]
            for p in parts:
                ops = base_ops + ([{"crop": p["crop"]}] if p.get("crop") else [])
                data = encode_page(apply_ops(im, ops))
                s = sha256(data)
                blobs[s] = data
                w, h = png_size(data)
                pages.append({"seq": leaf_seq(leaf, p.get("part", "")), "page": len(pages) + 1, "sha256": s,
                              "bytes": len(data), "w": w, "h": h, "src": f"{source_key}:{name}", "ops": ops})
    return pages, blobs


def register_local(raw_dir: Path, seq_of_page: dict[int, str], pattern: str = "{page}.png",
                   src_of_page: dict[int, str] | None = None, ops_of_page: dict[int, list[dict]] | None = None
                   ) -> tuple[list[dict], dict[str, bytes]]:
    """已有的 cv 原图目录原样登记（不重编码，sha 不变，产物不过期）。`seq_of_page`：cv 页号 → 页序。"""
    pages, blobs = [], {}
    for page in sorted(seq_of_page):
        data = (Path(raw_dir) / pattern.format(page=page)).read_bytes()
        s = sha256(data)
        blobs[s] = data
        w, h = png_size(data)
        row = {"seq": seq_of_page[page], "page": page, "sha256": s, "bytes": len(data), "w": w, "h": h,
               "src": (src_of_page or {}).get(page, ""), "ops": (ops_of_page or {}).get(page, [])}
        pages.append(row)
    return pages, blobs


def check_pages(pages: list[dict], wide: float = 1.15) -> list[dict]:
    """疑似合扫（宽高比明显大于本册中位数）的页，给人看。殿本单叶竖长（宽/高约 0.75），合扫双叶约 1.4。"""
    import statistics
    ratios = [p["w"] / p["h"] for p in pages if p.get("h")]
    if not ratios:
        return []
    med = statistics.median(ratios)
    return [{**p, "ratio": round(p["w"] / p["h"], 3), "median": round(med, 3)}
            for p in pages if p.get("h") and p["w"] / p["h"] > med * wide and not p["seq"][-1].isalpha()]


# ─── 页表 ────────────────────────────────────────────────────────────────

def validate(table: dict) -> None:
    if table.get("schema") != SCHEMA:
        raise ValueError(f"页表 schema 应为 {SCHEMA}")
    _check_ids(table.get("book_id", ""), table.get("vol", ""))
    seqs = [p["seq"] for p in table["pages"]]
    bad = [s for s in seqs if not SEQ_RE.match(s)]
    if bad:
        raise ValueError(f"页序不合法：{bad[:5]}")
    if len(set(seqs)) != len(seqs):
        raise ValueError("页序有重复")
    pages = [p["page"] for p in table["pages"]]
    if pages != list(range(1, len(pages) + 1)) and table.get("page_numbering") != "keep":
        raise ValueError("cv 页号应从 1 起连续（老册保留原编号写 page_numbering: keep）")
    if len(set(pages)) != len(pages):
        raise ValueError("cv 页号有重复")
    for p in table["pages"]:
        if not re.fullmatch(r"[0-9a-f]{64}", p.get("sha256", "")):
            raise ValueError(f"{p['seq']} 没有 sha256")


def revisions(src, book_id: str, vol: str) -> list[int]:
    pre = table_prefix(book_id, vol)
    out = []
    for k in _list(src, pre):
        m = re.fullmatch(re.escape(pre) + r"r(\d{3,})\.json", k)
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


def read_table(src, book_id: str, vol: str, rev: int | None = None) -> dict:
    vol = norm_vol(vol)
    if rev is None:
        revs = revisions(src, book_id, vol)
        if not revs:
            raise FileNotFoundError(f"R2 里没有 {book_id}/{vol} 的页表")
        rev = revs[-1]
    t = json.loads(_get(src, table_key(book_id, vol, rev)))
    if t.get("rev") != rev:
        raise ValueError(f"页表 r{rev:03d} 里写的版本是 {t.get('rev')}")
    return t


def diff_pages(old: dict | None, new_pages: list[dict]) -> list[str]:
    """哪些页序是新增或字节变了的（`changed`）。"""
    before = {p["seq"]: p["sha256"] for p in (old or {}).get("pages", [])}
    return [p["seq"] for p in new_pages if before.get(p["seq"]) != p["sha256"]] + \
        [s for s in before if s not in {p["seq"] for p in new_pages}]


def publish(src, table: dict, blobs: dict[str, bytes], *, by: str, why: str,
            upload=None) -> dict:
    """发布一版页表：先传缺的页图（已有跳过），再写 `r<下一版>.json`。返回写进去的页表。

    `upload(blobs)` 缺省经 Worker 传正式桶（`r2.upload_via_worker`），测试里换成假的。"""
    validate(table)
    book_id, vol = table["book_id"], table["vol"]
    revs = revisions(src, book_id, vol)
    old = read_table(src, book_id, vol, revs[-1]) if revs else None
    rev = (revs[-1] if revs else 0) + 1
    referenced = {p["sha256"] for p in table["pages"]}
    missing = referenced - set(blobs)
    if missing and old is not None:
        missing -= {p["sha256"] for p in old["pages"]}        # 没变的页沿用上一版，字节早已在 R2
    if missing:
        raise ValueError(f"有 {len(missing)} 页图不在手边、上一版也没有：{sorted(missing)[:3]}")
    for s, data in blobs.items():
        if sha256(data) != s:
            raise ValueError(f"页图字节与 sha 不符：{s}")
    (upload or _upload_main)({s: d for s, d in blobs.items() if s in referenced})
    out = dict(table)
    out.update({"rev": rev, "prev": (f"r{revs[-1]:03d}" if revs else None),
                "prev_sha256": (sha256(_get(src, table_key(book_id, vol, revs[-1]))) if revs else None),
                "created": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "by": by, "why": why, "changed": diff_pages(old, table["pages"]),
                "n_pages": len(table["pages"])})
    _put(src, table_key(book_id, vol, rev), json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    return out


def _upload_main(blobs: dict[str, bytes]) -> dict:
    from . import r2
    objs = {s: r2.Obj(s, len(d), s) for s, d in blobs.items()}
    return r2.upload_via_worker(None, objs, bucket="main", read=lambda o: blobs[o.oid])


def write_pointer(src, ws: str, book: str, book_id: str, vol: str) -> None:
    """cv 的 (工作区, 册名) → (书 id, 册)。只写一次；已有且相同就跳过，不同就报错。"""
    key = pointer_key(ws, book)
    rec = {"ws": ws, "book": book, "book_id": book_id, "vol": norm_vol(vol)}
    if _exists(src, key):
        have = json.loads(_get(src, key))
        if (have.get("book_id"), have.get("vol")) != (book_id, rec["vol"]):
            raise ValueError(f"{key} 已指向 {have.get('book_id')}/{have.get('vol')}，与 {book_id}/{rec['vol']} 不符")
        return
    _put(src, key, json.dumps(rec, ensure_ascii=False).encode("utf-8"))


def resolve(src, ws: str, book: str) -> tuple[str, str]:
    try:
        rec = json.loads(_get(src, pointer_key(ws, book)))
    except Exception as e:  # noqa: BLE001
        raise FileNotFoundError(f"R2 里没有 {ws}/{book} 的原图登记（{pointer_key(ws, book)}）：{e}") from None
    return rec["book_id"], rec["vol"]


def with_page(table: dict, seq: str, data: bytes, note: str, by: str) -> tuple[dict, dict[str, bytes]]:
    """把一页换成人工处理后的图（页序、页号不变），返回新页表（未发布）与要传的字节。"""
    s = sha256(data)
    w, h = png_size(data)
    t = json.loads(json.dumps(table))
    for p in t["pages"]:
        if p["seq"] == seq:
            p.update({"sha256": s, "bytes": len(data), "w": w, "h": h,
                      "ops": [*p.get("ops", []), {"manual": note, "by": by}]})
            break
    else:
        raise KeyError(f"页表里没有页序 {seq}")
    return t, {s: data}


# ─── 管线取图 ─────────────────────────────────────────────────────────────

PULL_MARK = "_pages.json"


def pull(src, table: dict, dest_of_page, *, cache=None, fetch=None) -> dict:
    """按页表把页图落到 cv 原图目录。`dest_of_page(page) -> Path`（一般是 `BookSpec.raw_path`）。

    已有且 sha 对得上的页不动；页图先进本地缓存（按 sha 去重、核 sha），再复制到目标。
    `fetch(shas) -> {sha: bytes}` 缺省经 Worker 签名、走公开 CDN 取。返回 {written, kept, pages, rev}。"""
    from .client import BlobCache
    cache = cache or BlobCache()
    want = {p["sha256"] for p in table["pages"]}
    need = [s for s in want if not cache.has(s)]
    if need:
        if fetch is not None:
            got = fetch(need)
            for s, d in got.items():
                cache.put(s, d)
        else:
            res = cache.ensure(src, need, bucket="main")
            if res["missing"]:
                raise FileNotFoundError(f"R2 上缺 {len(res['missing'])} 张页图：{res['missing'][:3]}")
    written = kept = 0
    dirs = set()
    for p in table["pages"]:
        dest = Path(dest_of_page(p["page"]))
        dirs.add(dest.parent)
        if dest.exists() and sha256(dest.read_bytes()) == p["sha256"]:
            kept += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(cache.path(p["sha256"]).read_bytes())
        tmp.replace(dest)
        written += 1
    for d in dirs:
        (d / PULL_MARK).write_text(json.dumps(
            {"book_id": table["book_id"], "vol": table["vol"], "rev": table["rev"], "encoding": table.get("encoding"),
             "pages": {str(p["page"]): {"seq": p["seq"], "sha256": p["sha256"]} for p in table["pages"]}},
            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"written": written, "kept": kept, "pages": len(table["pages"]), "rev": table["rev"]}


def new_table(book_id: str, vol: str, *, ws: str | None, book: str | None, sources: list[dict],
              pages: list[dict], encoding: str = ENCODING, status: str = "final", **extra) -> dict:
    import PIL
    srcs = [{k: v for k, v in s.items() if k != "path"} for s in sources]
    return {"schema": SCHEMA, "book_id": book_id, "vol": norm_vol(vol), "ws": ws, "book": book,
            "status": status, "encoding": encoding, "build": {"pillow": PIL.__version__},
            "sources": srcs, "pages": pages, **extra}
