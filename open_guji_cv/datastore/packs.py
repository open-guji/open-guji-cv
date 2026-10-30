"""产物包：一册的 products 打包存进 R2（经 guji-data Worker `/v1/packs`），新会话直接取，不再整册现算。

为什么：products 不进中心库，每个新会话要拿到「重跑前」的那份，只能从 Step1 整册重算
（殿本一册 1.5–2.5 小时）。打包后一册约十几 MB，取回是几秒到几十秒。取回的产物可以：

- 当 `guji products diff --a` 的「前」，看这次改动的前后对比；
- 当 `guji exp run --snapshot` 的上游；
- 直接放进本机 `products/` 接着增量重跑（指纹照常判：代码、参数、库变了的步照样过期，只重跑那些）。

布局（正式桶 `pack/` 之下，按名字只增不改）::

    products/<ws>/<册>/<标签>/manifest.json
    products/<ws>/<册>/<标签>/part-000.tgz …   每段 ≤ 64 MB

    products/<ws>/<册>/main-ptr/<UTC 时刻>-<标签>.json   每册的 main 指针，只增不改，最新一条为准

每份包按「册 + 标签」各存一份，不覆盖，任意两份都能取回比（不同 cv 版本、不同开关的结果并存）。
**main** 是这册当前的正式结果：`pack promote` 或 `pack push --main` 追加一条指针；`fetch` 不给标签时取 main，
没标过 main 才退回最新存的那份。标签缺省 `cv<版本>-c<语料库号>-g<字形库号>-<改动名或 UTC 时刻>`（三样版本共同决定结果，见 `version_label`）。存要正式令牌（`GUJI_DATA_TOKEN_PROD`；实验分支上存进实验桶要实验令牌），
取、列读令牌就够。包里不带 `_prev/`（上一代，只给格级复用用）和 `*.tmp`。

只当缓存用：取回时逐段核 sha256，对不上就报错，不解。产物新不新鲜照旧由引擎按指纹判，包本身不保证新鲜。
"""
from __future__ import annotations

import hashlib
import re
import io
import json
import shutil
import tarfile
import time
from pathlib import Path

PART_BYTES = 64 * 1024 * 1024
SKIP_DIRS = {"_prev"}


def _client():
    from .client import WorkerSource
    return WorkerSource()


def _bucket(src) -> str:
    from .client import is_exp_branch
    return "exp" if is_exp_branch(src.branch) else "main"


def _ws_name() -> str:
    """产物包键里的工作区名：标记 ``.central.json`` 的 ws，其次 ``workspace.yaml`` 的 id。

    两样都没有就报错，不猜：以前回退成目录名首段或 ``ws``，包落在别的前缀下，
    用 ``-w <工作区>`` 再也取不到（GUJI-671，vol01–03 的包曾落进 ``products/ws/``）。"""
    from ..core.workspace import central_marker, workspace_root
    m = central_marker() or {}
    if m.get("ws"):
        return str(m["ws"])
    root = workspace_root()
    if root is not None and (root / "workspace.yaml").is_file():
        import yaml
        wid = (yaml.safe_load((root / "workspace.yaml").read_text(encoding="utf-8")) or {}).get("id")
        if wid:
            return str(wid)
    raise SystemExit(f"产物包要知道工作区名：{root or '没设工作区（-w／GUJI_WORKSPACE）'} 下既没有 .central.json 的 ws，"
                     "也没有 workspace.yaml 的 id")


def _prefix(ws: str, book: str) -> str:
    return f"products/{ws}/{book}"


def _call(src, method: str, key: str, **kw):
    import urllib.parse
    return src._call(method, "/v1/packs/" + urllib.parse.quote(key), query={"bucket": _bucket(src)}, **kw)


def _tar_book(root: Path, book: str, steps: list[str] | None) -> tuple[bytes, int, dict[str, int]]:
    base = Path(root) / book
    if not base.is_dir():
        raise FileNotFoundError(f"没有产物目录 {base}")
    avail = sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
    use = steps or avail
    missing = [s for s in use if s not in avail]
    if missing:
        raise FileNotFoundError(f"{base} 下没有这些步：{', '.join(missing)}")
    buf = io.BytesIO()
    n, per = 0, {}
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tf:
        for f in sorted(base.glob("*")):                         # 册级文件（_raw_index.json 等）
            if f.is_file() and not f.name.endswith(".tmp") and not f.name.startswith("."):
                tf.add(f, arcname=f"{book}/{f.name}")
                n += 1
        for s in use:
            k = 0
            for f in sorted((base / s).rglob("*")):
                rel = f.relative_to(base / s)
                if not f.is_file() or f.name.endswith(".tmp") or (rel.parts and rel.parts[0] in SKIP_DIRS):
                    continue
                tf.add(f, arcname=f"{book}/{s}/{rel.as_posix()}")
                k += 1
            per[s], n = k, n + k
    return buf.getvalue(), n, per


LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")   # 与 Worker /v1/packs 的路径段规则一致
MAIN_DIR = "main-ptr"
LABEL_MAX_MAIN = 96 - len("20261020T004800Z-") - len(".json")


def version_label(v: dict) -> str:
    """`cv0.4.7-c1-g2`：cv 版本、语料库号、字形库号。没钉的写 `c-`；字形库没钉写 `g-` 加人裁指纹前 6 位。"""
    cv = re.sub(r"[^A-Za-z0-9.]", "p", str(v.get("cv") or "unknown"))     # 0.4.7+3 → 0.4.7p3
    c = f"c{v['corpus']}" if v.get("corpus") is not None else "c-"
    if v.get("glyph_pin") is not None:
        g = f"g{v['glyph_pin']}"
    else:
        fp = str(v.get("human_fp") or "")
        h = re.sub(r"[^0-9a-f]", "", fp.split(":")[-1].lower())[:6] if fp.startswith("h1:") else ""
        g = f"g-{h}" if h else "g-"
    return f"cv{cv}-{c}-{g}"


def check_label(label: str) -> None:
    """包标签只许 ASCII 字母、数字、`_.-`（Worker 拒收中文等，报 bad_path）。先在本地挡下，说清楚。"""
    if not LABEL_RE.match(label or ""):
        raise ValueError(f"包标签 {label!r} 不合法：只能用 ASCII 字母、数字和 _.-，以字母或数字开头，"
                         f"不超过 96 字符（如 v0.4.7-layout-prior）")
    if label == MAIN_DIR:
        raise ValueError(f"标签不能叫 {MAIN_DIR}（main 指针占用）")


MARK = ".pack.json"     # <产物根>/<册>/.pack.json：本机这份产物最后一次存包／取包是哪个标签、当时的摘要


def products_digest(root: Path, book: str) -> str:
    """一册产物的摘要：各步 `_manifest.jsonl` 内容的 sha256。manifest 只追加，跑过任何一页就变；
    取回的包解出来与存包时一字不差，所以存、取之后各记一次，之后对得上就说明没再跑过。"""
    base = Path(root) / book
    h = hashlib.sha256()
    for m in sorted(base.glob("*/_manifest.jsonl")):
        h.update(m.parent.name.encode("utf-8") + b"\0")
        h.update(m.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def write_mark(root: Path, book: str, label: str, how: str) -> None:
    base = Path(root) / book
    if base.is_dir():
        (base / MARK).write_text(json.dumps({"label": label, "how": how, "digest": products_digest(root, book),
                                             "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                                            ensure_ascii=False) + "\n", encoding="utf-8")


def unpacked_note(root: Path, book: str) -> str | None:
    """本机这册产物有没存进产物包的新结果 → 一句提醒；没产物、或与最后存／取的包一致 → None。
    提醒只是提醒（不挡什么）：试跑、半截的结果本来就不该存。"""
    base = Path(root) / book
    if not any(base.glob("*/_manifest.jsonl")):
        return None
    try:
        mk = json.loads((base / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        mk = None
    if mk and mk.get("digest") == products_digest(root, book):
        return None
    tail = f"（上次{'存' if mk.get('how') == 'push' else '取'}的是 {mk.get('label')}，之后又跑过）" if mk else "（从没存过包）"
    return (f"本册产物还没存进产物包{tail}：正式结果跑完记得 "
            f"guji products pack push {book} --change <改动名> [--main]")


def push_products(book: str, root: Path, label: str | None = None, steps: list[str] | None = None,
                  note: str = "", src=None, change: str | None = None, vers: dict | None = None,
                  purity: dict | None = None) -> dict:
    """`label` 给了就整个用它；不给就拼 `<版本三段>-<change>`（change 缺省 UTC 时刻），如 `cv0.4.7-c1-g2-layout`。
    `vers`：三样版本（`cli_products.book_versions` 读册配置算好传进来；不传只记 cv）。
    `purity`：存包前的纯净性检查（`ops/pack_purity.check`），原样记进 manifest，标 main 时看。"""
    from ..core import cv_version as CV
    src = src or _client()
    if vers is None:
        ver, commit = CV.describe()
        vers = {"cv": ver, "cv_commit": commit, "corpus": None, "glyph_pin": None, "human_fp": None}
    ver, commit = vers["cv"], vers["cv_commit"]
    label = label or f"{version_label(vers)}-{change or time.strftime('%Y%m%dT%H%M', time.gmtime())}"
    check_label(label)
    ws = _ws_name()
    pre = f"{_prefix(ws, book)}/{label}"
    data, nfiles, per = _tar_book(root, book, steps)
    parts = []
    for i in range(0, max(1, len(data)), PART_BYTES):
        chunk = data[i:i + PART_BYTES]
        name = f"part-{len(parts):03d}.tgz"
        _call(src, "PUT", f"{pre}/{name}", data=chunk, content_type="application/gzip", tries=3)
        parts.append({"name": name, "bytes": len(chunk), "sha256": hashlib.sha256(chunk).hexdigest()})
    man = {"name": pre, "ws": ws, "book": book, "label": label, "cv_version": ver, "cv_commit": commit,
           "versions": vers,
           "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "note": note,
           "files": nfiles, "steps": per, "bytes": len(data), "parts": parts,
           "pack_sha256": hashlib.sha256(data).hexdigest()}
    if purity is not None:
        man["purity"] = purity
    _call(src, "PUT", f"{pre}/manifest.json", data=json.dumps(man, ensure_ascii=False, indent=1).encode("utf-8"),
          content_type="application/json", tries=3)
    if not steps:                       # 只打了几步的包不算整册存过
        write_mark(root, book, label, "push")
    return man


def list_packs(book: str | None = None, src=None) -> list[dict]:
    src = src or _client()
    ws = _ws_name()
    pre = _prefix(ws, book) + "/" if book else f"products/{ws}/"
    rows = src._call("GET", "/v1/packs", query={"bucket": _bucket(src), "prefix": pre})["packs"]
    out = []
    for r in rows:
        if r["key"].endswith("/manifest.json"):
            try:
                m = json.loads(_call(src, "GET", r["key"], raw=True))
            except Exception:
                m = {}
            out.append({"name": r["key"][:-len("/manifest.json")], "bytes": m.get("bytes"),
                        "created": m.get("created"), "note": m.get("note", ""), "cv_version": m.get("cv_version"),
                        "versions": m.get("versions")})
    out = sorted(out, key=lambda m: m.get("created") or "")
    mains: dict[str, str | None] = {}
    for m in out:
        bk = m["name"].split("/")[2]
        if bk not in mains:
            mains[bk] = main_label(bk, src)
        m["main"] = m["name"].split("/")[-1] == mains[bk]
    return out


def _latest(book: str, src) -> str:
    rows = list_packs(book, src=src)
    if not rows:
        raise FileNotFoundError(f"R2 里没有 {book} 的产物包（guji products pack list 看看）")
    return rows[-1]["name"]


def main_label(book: str, src=None) -> str | None:
    """这册 main 指针指着的标签；没标过 → None。指针只增不改，按时刻取最新一条。"""
    src = src or _client()
    pre = f"{_prefix(_ws_name(), book)}/{MAIN_DIR}/"
    keys = sorted(r["key"] for r in src._call("GET", "/v1/packs", query={"bucket": _bucket(src), "prefix": pre})["packs"]
                  if r["key"].endswith(".json"))
    if not keys:
        return None
    return keys[-1][len(pre):-len(".json")].split("-", 1)[1]


def promote(book: str, label: str, note: str = "", src=None, why: str | None = None) -> str:
    """把已存的 `<册>/<标签>` 标成 main（追加一条指针，不动包本身）。

    main 是正式结果，只收正式版 cv 出的包（2026-10-23 起）：正式库里包的 `cv_version` 不是三段数字
    （dev／rc／任意提交跑的 `0.5.10.dev3+g…`、`dev+g…`、带 dirty、没记版本）就拒，
    确要标给 `why`（记进指针）。实验桶里的包不查。

    存包时记了纯净性（`purity`，`ops/pack_purity`）且不纯（混版本、图源对不上）的，先照标、在指针里记一笔
    `impure`（2026-10-30 起，A32 精校前移 A2）。没有改成拦：实测册 007 近期的 main 候选包（A24 全册重放）
    切分步、5-b 都是旧代码跑的，严格口径下全部「不纯」，拦就等于改了现行重跑做法，要用户先定（见 ops/pack_purity）。"""
    from ..core.cv_version import is_formal
    src = src or _client()
    check_label(label)
    if len(label) > LABEL_MAX_MAIN:
        raise ValueError(f"标签 {label!r} 太长，标 main 时不能超过 {LABEL_MAX_MAIN} 字符")
    pre = _prefix(_ws_name(), book)
    man = json.loads(_call(src, "GET", f"{pre}/{label}/manifest.json", raw=True))   # 包得先存在
    ver = man.get("cv_version")
    if _bucket(src) == "main" and not is_formal(ver) and not (why or "").strip():
        raise ValueError(f"包 {label} 是 cv {ver or '未知版本'} 出的，不是正式版，不能标 main："
                         f"发正式 tag 后在它上面重跑再存；确要标加 --why \"<理由>\"")
    from ..ops.pack_purity import describe
    pur = man.get("purity")
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    rec = {"book": book, "label": label, "at": ts, "note": note}
    if not is_formal(ver):
        rec.update(cv_version=ver, cv_override=(why or "").strip() or None)
    if pur and pur.get("pure") is False:
        rec.update(impure=describe(pur), impure_why=(why or "").strip() or None)
    _call(src, "PUT", f"{pre}/{MAIN_DIR}/{ts}-{label}.json", data=json.dumps(rec, ensure_ascii=False).encode("utf-8"),
          content_type="application/json", tries=3)
    return f"{pre}/{label}"


def fetch_products(book: str, dest_root: Path, label: str | None = None, force: bool = False, src=None) -> dict:
    """取回并解到 `<dest_root>/<册>/`。目标已有该册产物时，除非 `force`，拒绝（不覆盖本机正在用的产物）。"""
    src = src or _client()
    if not label:
        label = main_label(book, src)
    name = f"{_prefix(_ws_name(), book)}/{label}" if label else _latest(book, src)
    man = json.loads(_call(src, "GET", f"{name}/manifest.json", raw=True))
    dest = Path(dest_root) / book
    if dest.exists() and any(dest.iterdir()) and not force:
        raise FileExistsError(f"{dest} 已有产物；要覆盖加 --force，或用 --to 解到别处（如对比用的空目录）")
    buf = io.BytesIO()
    for p in man["parts"]:
        chunk = _call(src, "GET", f"{name}/{p['name']}", raw=True)
        if hashlib.sha256(chunk).hexdigest() != p["sha256"]:
            raise ValueError(f"{name}/{p['name']} sha256 对不上，包坏了，不解")
        buf.write(chunk)
    buf.seek(0)
    if dest.exists():                       # 全部段核过 sha 才动本机产物
        shutil.rmtree(dest)
    Path(dest_root).mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=buf, mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile() or m.name.startswith("/") or ".." in Path(m.name).parts or not m.name.startswith(f"{book}/"):
                raise ValueError(f"包里有不合规的路径：{m.name}")
        tf.extractall(dest_root, filter="data") if hasattr(tarfile, "data_filter") else tf.extractall(dest_root)
    write_mark(dest_root, book, name.rsplit("/", 1)[-1], "fetch")
    return {"name": name, "dest": str(dest), "files": man["files"], "cv_version": man.get("cv_version")}


# ---- 生僻字 embedding 索引（Step5-b 冷建：29k 字，云上 4 核 40 分钟以上）----
# 键按内容算（checkpoint + 字体集 + 字表，`cnn_candidates.emb_index_key`），各机器同一份输入得到同一个文件名，
# 所以按文件名存取就行：`rare-index/<checkpoint 目录>/emb_<key>.npz/{part-000, manifest.json}`。

def _models_root() -> Path:
    return Path(__file__).resolve().parents[2] / "models"


def push_file(key: str, path: Path, src=None, gzip_level: int | None = None) -> dict:
    """把一个文件按 64 MB 分段存到 `key/part-NNN`，再写 `key/manifest.json`。

    边读边传（2026-10-20）：字体域预建件一套约 1.5 GB，整份读进内存会把小机器挤爆。
    `gzip_level` 给了就边读边压（manifest 记 `encoding: gzip`，`sha256`／`bytes` 是**解压后**原文件的）。"""
    import zlib
    src = src or _client()
    whole = hashlib.sha256()
    total = 0
    parts: list[dict] = []
    z = zlib.compressobj(gzip_level, zlib.DEFLATED, 31) if gzip_level is not None else None
    buf = bytearray()

    def send(chunk: bytes) -> None:
        name = f"part-{len(parts):03d}"
        _call(src, "PUT", f"{key}/{name}", data=bytes(chunk), tries=3)
        parts.append({"name": name, "bytes": len(chunk), "sha256": hashlib.sha256(chunk).hexdigest()})

    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(PART_BYTES), b""):
            whole.update(blk)
            total += len(blk)
            buf += z.compress(blk) if z is not None else blk
            while len(buf) >= PART_BYTES:
                send(buf[:PART_BYTES])
                del buf[:PART_BYTES]
    if z is not None:
        buf += z.flush()
    while len(buf) > PART_BYTES:
        send(buf[:PART_BYTES])
        del buf[:PART_BYTES]
    if buf or not parts:
        send(buf)
    man = {"name": key, "bytes": total, "sha256": whole.hexdigest(), "parts": parts,
           "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if z is not None:
        man["encoding"] = "gzip"
    _call(src, "PUT", f"{key}/manifest.json", data=json.dumps(man).encode("utf-8"),
          content_type="application/json", tries=3)
    return man


#: 取大文件时同时在路上的段数（每段 ≤ 64 MB，内存里最多这么多段）。云端实测（2026-10-20，读令牌）：
#: 单路约 11 MB/s，4 路合计 21 MB/s，8 路 44 MB/s——瓶颈在单连接，不在出口带宽
FETCH_THREADS = 8


def _parts_in_order(src, key: str, parts: list[dict]):
    """按顺序逐段产出内容，后面几段并发预取（一段 64 MB 串行取，字体域 1.8 GB 要好几分钟）。"""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=FETCH_THREADS) as ex:
        futs = []
        for i, p in enumerate(parts):
            futs.append(ex.submit(_call, src, "GET", f"{key}/{p['name']}", raw=True))
            if i + 1 >= FETCH_THREADS:
                yield futs.pop(0).result()
        for f in futs:
            yield f.result()


def fetch_file(key: str, dest: Path, src=None) -> int:
    """取回 `push_file` 存的文件：逐段核 sha256、边取边写（manifest 记了 gzip 就边取边解），
    整份 sha256 对上才换到 `dest`。返回原文件字节数。"""
    import zlib
    src = src or _client()
    man = json.loads(_call(src, "GET", f"{key}/manifest.json", raw=True))
    z = zlib.decompressobj(31) if man.get("encoding") == "gzip" else None
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    whole = hashlib.sha256()
    n = 0
    try:
        with open(tmp, "wb") as out:
            for p, chunk in zip(man["parts"], _parts_in_order(src, key, man["parts"])):
                if "sha256" in p and hashlib.sha256(chunk).hexdigest() != p["sha256"]:
                    raise ValueError(f"{key}/{p['name']} sha256 对不上，不落盘")
                blk = z.decompress(chunk) if z is not None else chunk
                whole.update(blk)
                n += len(blk)
                out.write(blk)
            if z is not None:
                tail = z.flush()
                whole.update(tail)
                n += len(tail)
                out.write(tail)
        if whole.hexdigest() != man["sha256"]:
            raise ValueError(f"{key} sha256 对不上，不落盘")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return n


def push_rare_indexes(src=None) -> list[str]:
    """本机 models/*/emb_*.npz 里 R2 还没有的，存上去。"""
    src = src or _client()
    have = {r["key"].rsplit("/", 1)[0] for r in
            src._call("GET", "/v1/packs", query={"bucket": _bucket(src), "prefix": "rare-index/"})["packs"]
            if r["key"].endswith("/manifest.json")}
    done = []
    for f in sorted(_models_root().glob("*/emb_*.npz")):
        key = f"rare-index/{f.parent.name}/{f.name}"
        if key not in have:
            push_file(key, f, src=src)
            done.append(key)
    return done


def fetch_rare_indexes(src=None) -> list[str]:
    """R2 里有、本机 checkpoint 目录在、文件还没有的索引，取下来。"""
    src = src or _client()
    got = []
    rows = src._call("GET", "/v1/packs", query={"bucket": _bucket(src), "prefix": "rare-index/"})["packs"]
    for r in rows:
        if not r["key"].endswith("/manifest.json"):
            continue
        key = r["key"].rsplit("/", 1)[0]
        _, ckpt, fname = key.split("/", 2)
        dest = _models_root() / ckpt / fname
        if (_models_root() / ckpt).is_dir() and not dest.exists():
            fetch_file(key, dest, src=src)
            got.append(str(dest))
    return got


# ---- 派生缓存：训好的语言模型（2026-10-20）----
# 本机缓存 `cache_root()/general_lm/<kind>-<键>.json` 的键已经按「语料内容 sha256 + 训练参数 + lm.py
# 代码指纹」算（`clustering.seeding._cached_lm`），各机器同一份输入得到同一个文件名，所以按文件名存取：
# `derived/lm/<文件名>/{part-000, manifest.json}`。取：本机没命中时自动取（要 `GUJI_DATA_TOKEN`，读令牌就够）；
# 存：手动 `guji products pack push-index`（要正式令牌），用户 10-20 定不自动推。
# 同一套按文件名存取的还有字体域预建件 `derived/fontdb/<edition>-<键>.sqlite`（gzip，一套 0.7–1.2 GB 压后），
# 取在 `glyph-db import-font`，存是 `glyph-db font-pack-push`（`clustering/font_pack.py`）。

def _lm_dir() -> Path:
    from ..core.workspace import cache_root
    return cache_root() / "general_lm"


def fetch_derived(kind_dir: str, name: str, dest: Path) -> bool:
    """R2 里有 `derived/<kind_dir>/<name>` 就取下来（核 sha256、原子落盘）返回 True；没设令牌、
    没有这份、网络出错都返回 False（调用方接着现算，不因取不到而失败）。`GUJI_DERIVED_FETCH=0` 关掉。"""
    import os
    if not os.environ.get("GUJI_DATA_TOKEN") or os.environ.get("GUJI_DERIVED_FETCH") == "0":
        return False
    try:
        fetch_file(f"derived/{kind_dir}/{name}", Path(dest))
        return True
    except Exception:  # noqa: BLE001 —— 取不到就现算
        return False


def push_derived(src=None) -> list[str]:
    """本机训好的语言模型（`cache_root()/general_lm/*.json`）里 R2 还没有的，存上去。"""
    src = src or _client()
    have = {r["key"].rsplit("/", 1)[0] for r in
            src._call("GET", "/v1/packs", query={"bucket": _bucket(src), "prefix": "derived/lm/"})["packs"]
            if r["key"].endswith("/manifest.json")}
    done = []
    for f in sorted(_lm_dir().glob("*.json")):
        if ".tmp" in f.name or not (f.name.startswith("book-") or f.name.startswith("general-")):
            continue
        key = f"derived/lm/{f.name}"
        if key not in have:
            push_file(key, f, src=src)
            done.append(key)
    return done
