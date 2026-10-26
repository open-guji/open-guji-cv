"""语料库（corpus-vN）的清单读取、册钉子与指纹替换（设计见 doc/design/语料库版本化方案.md）。

放在 core 是因为 `Engine.params_for` 要用它；`guji corpus build|verify|list`（`ops/corpus_pack.py`）
在它上面加「出新版」和代码常量校验。

**册钉子**：册 yaml 写 `corpus: 1`（或 `v1`）。钉了之后，`params_for` 把参数里**属于语料库的内容指纹**
（`PIN_FIELDS`）统一换成 `corpus-<清单内容哈希>`（`corpus_token`）：不含版本号；没钉的册一字不变。
钉住的版本必须有清单，否则报错；清单之后文件被改过只警告一次（该出新版本，或把文件改回去）。
算指纹时（``guji status`` 等）只警告；真开跑读语料的步之前 ``require_pin_clean`` 硬校验，改了或缺了就拒绝。
两级清单（共享方案 S2）：书库 ``v<N>`` 写 ``base: M`` 时并上底库 ``b<M>``（中心库 ``corpus-base``）的条目。
册 yaml 再写 ``corpus_dev: true`` = 这个总号的语料还在开发，跳过校验。三层（doc/design/语料库分层版本.md）：全局（底库 ``b<M>``）＋整套书（书库 ``v<N>``）＋册（``vol/<册>/v<K>``）；
册 yaml 的 ``corpus: N`` 是总号，在该册的钉子账 ``pins/<册>.json`` 里对应三层各自的版本，任一层变总号就升；
指纹仍只取 ``corpus-vN``。没有钉子账的册，``N`` 按旧做法解释为书库 ``v<N>``（它清单里写的 ``base``）。
"""
from __future__ import annotations

import sys
from pathlib import Path

PACK_DIR = "corpus-pack"
REPO_ROOT = Path(__file__).resolve().parents[2]

#: (分组, 根, 相对根的通配)。根："repo" = 本仓，"ws" = 工作区。通配按 `Path.glob`，目录递归用 `**/*`。
ITEMS: tuple[tuple[str, str, str], ...] = (
    ("reference", "ws", "corpus/**/*.txt"),
    ("reference", "repo", "corpus/external/*.txt"),
    ("freq", "ws", "config/groups/freq.json"),
    ("l2", "ws", "config/groups/l2/*.json"),
    ("rules", "repo", "config/groups/*/*"),
    ("ids", "repo", "config/ids/*"),
    ("variants", "repo", "config/dicts/variants*.tsv"),
    ("variants", "repo", "config/variants/*.json"),
    ("variants", "repo", "config/variants/books/*.json"),
    ("variants", "ws", "config/variants/**/*.json"),
    ("notes", "repo", "config/jiazhu/*.json"),
    ("confusable", "repo", "config/confusable_*.json"),
    ("confusable", "repo", "config/iron_extra_confusable.json"),
    ("charset", "repo", "config/charset/*"),
    ("charset", "repo", "config/kangxi/*"),
)

_SKIP_NAMES = {"README.md", ".gitkeep"}

#: 大静态文件（≥1MB 的 .txt／.tsv／.json）在清单条目里加 ``"store": "r2"``：内容在 R2 按 sha256 存（``guji corpus upload`` 传，
#: ``fetch`` 取回），清单只记哈希做索引。目前 R2 只收 png／txt（`datastore.r2.CONTENT_TYPES`）。不进指纹（`items_digest` 只看 root、path、sha256）。
BLOB_MIN = 1_000_000
#: 文本类才走 R2（桶里统一按 .txt 键存，content-type 为 text/plain；取回按 sha 还原到登记的路径，后缀不影响）。
#: `.npz` 是 U-Net 权重（`config/groups/<组>/unet.npz`，约 1MB，sheldon 2026-10-22 要求训完都存 R2 免得重训）：同样按哈希存，字节原样。
BLOB_SUFFIXES = (".txt", ".tsv", ".json", ".npz")


def _item(group: str, root: str, rel: str, p: Path, sha) -> dict:
    size = p.stat().st_size
    it = {"group": group, "root": root, "path": rel, "size": size, "sha256": sha(p)}
    if size >= BLOB_MIN and p.suffix in BLOB_SUFFIXES:
        it["store"] = "r2"
    return it


def _not_corpus(root: str, rel: str) -> bool:
    """不算语料的文件：说明文件；字组的 ``prompt.md``（只给离线 L2 批量拼消息用，Step 不读，
    改它不该让钉了版本的册拒跑）。老清单里登记过的这类条目，核对时也跳过。"""
    name = rel.rsplit("/", 1)[-1]
    if name in _SKIP_NAMES:
        return True
    return root == "repo" and name == "prompt.md" and rel.startswith("config/groups/")


def _sha256(p: Path) -> str:
    from ..products.store import sha256_file
    return sha256_file(p)


_SHA_CACHE: dict[tuple[str, int, int], str] = {}


def _sha256_stat_cached(p: Path) -> str:
    """同一进程里按 (路径, 大小, 修改时间) 缓存的哈希：指纹每次算都要扫一遍语料，别每次都读 60MB。"""
    st = p.stat()
    key = (str(p), st.st_size, st.st_mtime_ns)
    h = _SHA_CACHE.get(key)
    if h is None:
        h = _SHA_CACHE[key] = _sha256(p)
    return h


def _base(root: str, pat: str, ws: Path) -> Path:
    """根目录。工作区里 ``config/`` 下的表迁到中心库数据目录后在 ``data_root``（GUJI-608）。"""
    if root == "repo":
        return REPO_ROOT
    if pat.startswith("config/"):
        from .workspace import data_root
        return data_root(ws) or ws
    if pat.startswith("corpus/"):                      # 整理本也进了中心库（共享方案 2.2 节）
        from .workspace import corpus_dir
        return corpus_dir(ws).parent
    return ws


def collect(ws: Path, cached: bool = False) -> list[dict]:
    """按 ITEMS 扫出当前所有语料文件，返回 manifest 的 items（按 (root, path) 排序，输出稳定）。"""
    seen: dict[tuple[str, str], dict] = {}
    for group, root, pat in ITEMS:
        base = _base(root, pat, ws)
        for p in sorted(base.glob(pat)):
            if not p.is_file():
                continue
            rel = p.relative_to(base).as_posix()
            if _not_corpus(root, rel):
                continue
            key = (root, rel)
            if key in seen:
                continue
            seen[key] = _item(group, root, rel, p, _sha256_stat_cached if cached else _sha256)
    return [seen[k] for k in sorted(seen)]


def pack_root(ws: Path) -> Path:
    """清单目录。迁到中心库的工作区在数据目录 ``config/corpus-pack/``（随 ``config/`` 进 ``files`` 表，
    共享方案 2.2 节）；没迁的工作区照旧 ``<工作区>/corpus-pack/``。迁过但还没补迁、旧目录还在工作区根时
    退回旧目录。只是挪地方：钉子指纹是 ``corpus-vN``，与清单放哪无关。"""
    from .workspace import data_root
    ws = Path(ws)
    old = ws / PACK_DIR
    d = data_root(ws)
    if d is None or d == ws:
        return old
    new = d / "config" / PACK_DIR
    if not new.is_dir() and old.is_dir():
        return old
    return new


# ── 底库（共享，两级清单，共享方案 2.1 节）────────────────────────────────────────

#: 底库清单所在的中心库特殊工作区（只读，升级脚本 ``guji corpus build-base`` 才写）
BASE_WS = "corpus-base"
BASE_DIR = "config/corpus-base"


def base_root(ws: Path) -> Path | None:
    """本机的底库清单目录：``corpus-base`` 工作区自己 → 它的数据目录；别的迁过的工作区 →
    ``db pull`` 拉的只读副本（``core.workspace.borrowed_root``）；没迁的工作区 → None（不能用底库）。"""
    from .workspace import borrowed_root, central_marker, data_root
    m = central_marker(Path(ws))
    if not m:
        return None
    if m.get("ws") == BASE_WS:
        return (data_root(Path(ws)) or Path(ws)) / BASE_DIR
    return borrowed_root(BASE_WS, str(m.get("branch") or "main")) / BASE_DIR


def base_versions(ws: Path) -> list[int]:
    d = base_root(ws)
    if d is None or not d.is_dir():
        return []
    return sorted(int(p.name[1:]) for p in d.iterdir()
                  if p.is_dir() and p.name.startswith("b") and p.name[1:].isdigit()
                  and (p / "manifest.json").exists())


def base_manifest_path(ws: Path, version: int) -> Path:
    d = base_root(ws)
    if d is None:
        raise FileNotFoundError(f"{ws} 没迁到中心库，用不了底库（共享方案 2.1 节）")
    return d / f"b{version}" / "manifest.json"


_KEEP = object()


def _load_book_manifest(ws: Path, version: int, base=_KEEP) -> dict:
    """书库 v<N> 的清单；写了 ``base: M`` 的，底库 b<M> 的条目并进来（书库只登记工作区里的文件）。
    ``base`` 给了就用它覆盖清单里写的（钉子账里的全局层版本，``None`` = 不并底库）。"""
    import json
    mp = manifest_path(ws, version)
    if not mp.exists():
        raise FileNotFoundError(f"没有语料库 v{version} 的清单：{mp}")
    man = json.loads(mp.read_text(encoding="utf-8"))
    b = man.get("base") if base is _KEEP else base
    if b is None:
        return man
    bp = base_manifest_path(ws, int(b))
    if not bp.exists():
        raise FileNotFoundError(f"语料库 v{version} 写着底库 b{b}，本机没有它的清单 {bp}"
                                f"（先 guji db pull -w {ws}）")
    base_man = json.loads(bp.read_text(encoding="utf-8"))
    bad = [i["path"] for i in base_man["items"] if i["root"] != "repo"] + \
          [i["path"] for i in man["items"] if i["root"] != "ws"]
    if bad:
        raise ValueError(f"两级清单的条目根不对（底库只放引擎仓文件，书库只放工作区文件）：{bad[:5]}")
    return {**man, "base": int(b),
            "items": sorted(base_man["items"] + man["items"], key=lambda i: (i["root"], i["path"])),
            "code_tables": base_man.get("code_tables", {}),
            "base_manifest": {k: base_man.get(k) for k in ("base_version", "repo_commit", "created")}}


def load_manifest(ws: Path, version: int, vol: str | None = None) -> dict:
    """册 yaml 的 ``corpus: N`` 对应的完整清单。

    不给 ``vol``：``N`` 就是书库版本（旧做法）。给了 ``vol``（册 id）：按该册的钉子账把 ``N`` 解成
    三层（全局、整套书、册）版本再并起来；册没有钉子账时退回旧做法。"""
    if vol is None:
        return _load_book_manifest(ws, version)
    pin = resolve_pin(ws, vol, version)
    man = _load_book_manifest(ws, pin["book"], base=pin["global"])
    if pin.get("vol") is None:
        return man
    vm = _load_vol_manifest(ws, vol, pin["vol"])
    return {**man, "vol_manifest": {"vol": vol, "vol_version": pin["vol"]},
            "items": sorted(man["items"] + vm["items"], key=lambda i: (i["root"], i["path"]))}


# ── 册层与钉子账（分层版本）──────────────────────────────────────────────────────

#: 册层语料所在目录（工作区数据根下，每册一个子目录）
VOL_DIR = "config/corpus-vol"


def vol_prefix(vol: str) -> str:
    return f"{VOL_DIR}/{vol}/"


def vol_versions(ws: Path, vol: str) -> list[int]:
    d = pack_root(ws) / "vol" / vol
    if not d.is_dir():
        return []
    return sorted(int(p.name[1:]) for p in d.iterdir()
                  if p.is_dir() and p.name.startswith("v") and p.name[1:].isdigit()
                  and (p / "manifest.json").exists())


def vol_manifest_path(ws: Path, vol: str, version: int) -> Path:
    return pack_root(ws) / "vol" / vol / f"v{version}" / "manifest.json"


def collect_vol(ws: Path, vol: str, cached: bool = False) -> list[dict]:
    """扫出这册的册层语料文件（``config/corpus-vol/<册>/**``），都在工作区数据根下，root=ws。"""
    base = _base("ws", VOL_DIR + "/", ws)
    out = []
    for p in sorted((base / VOL_DIR / vol).glob("**/*")) if (base / VOL_DIR / vol).is_dir() else []:
        if p.is_file() and p.name not in _SKIP_NAMES:
            out.append(_item("vol", "ws", p.relative_to(base).as_posix(), p,
                             _sha256_stat_cached if cached else _sha256))
    return out


def _load_vol_manifest(ws: Path, vol: str, version: int) -> dict:
    import json
    mp = vol_manifest_path(ws, vol, version)
    if not mp.exists():
        raise FileNotFoundError(f"没有册层语料库 {vol} v{version} 的清单：{mp}")
    man = json.loads(mp.read_text(encoding="utf-8"))
    bad = [i["path"] for i in man["items"] if i["root"] != "ws" or not i["path"].startswith(vol_prefix(vol))]
    if bad:
        raise ValueError(f"册层清单的条目只能是 {vol_prefix(vol)} 下的工作区文件：{bad[:5]}")
    return man


def pins_path(ws: Path, vol: str) -> Path:
    return pack_root(ws) / "pins" / f"{vol}.json"


def load_pins(ws: Path, vol: str) -> list[dict]:
    """这册的钉子账（只追加）：每行 ``{n, global, book, vol, date, note}``，``n`` 是总号。"""
    import json
    p = pins_path(ws, vol)
    return json.loads(p.read_text(encoding="utf-8"))["rows"] if p.exists() else []


def _check_layers_exist(ws: Path, vol: str, new: dict) -> None:
    if new["book"] not in versions(ws):
        raise FileNotFoundError(f"整套书层没有 v{new['book']}（有 {versions(ws)}）")
    if new["global"] is not None and new["global"] not in base_versions(ws):
        raise FileNotFoundError(f"全局层没有 b{new['global']}（本机有 {base_versions(ws)}；先 guji db pull）")
    if new["vol"] is not None and new["vol"] not in vol_versions(ws, vol):
        raise FileNotFoundError(f"册 {vol} 没有册层 v{new['vol']}（有 {vol_versions(ws, vol)}）")


def release_pin(ws: Path, vol: str, n: int) -> dict:
    """开发中的总号发版：三层清单都已出齐（版本号对得上）才放行，账里去掉 ``dev``。
    册 yaml 的 ``corpus_dev: true`` 由调用方去掉。"""
    import json
    rows = load_pins(ws, vol)
    row = next((r for r in rows if r["n"] == n), None)
    if row is None:
        raise FileNotFoundError(f"册 {vol} 的钉子账里没有总号 {n}")
    if not row.get("dev"):
        raise ValueError(f"册 {vol} 的总号 {n} 不是开发中的，不用发版")
    _check_layers_exist(ws, vol, row)
    row.pop("dev")
    pins_path(ws, vol).write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return row


def resolve_pin(ws: Path, vol: str, n: int) -> dict:
    """总号 N → 三层版本。账里有就按账；这册没有钉子账时退回旧做法：N 是书库版本，全局层取它清单里写的 ``base``。"""
    import json
    rows = load_pins(ws, vol)
    for r in rows:
        if r["n"] == n:
            return {"n": n, "global": r.get("global"), "book": r["book"], "vol": r.get("vol")}
    if rows:
        raise FileNotFoundError(f"册 {vol} 的钉子账里没有总号 {n}（有 {[r['n'] for r in rows]}）：{pins_path(ws, vol)}")
    mp = manifest_path(ws, n)
    if not mp.exists():
        raise FileNotFoundError(f"没有语料库 v{n} 的清单：{mp}")
    return {"n": n, "global": json.loads(mp.read_text(encoding="utf-8")).get("base"), "book": n, "vol": None}


def append_pin(ws: Path, vol: str, *, from_n: int | None = None, global_ver=_KEEP, book_ver=_KEEP,
               vol_ver=_KEEP, note: str = "", dev: bool = False) -> dict:
    """给这册追加一行钉子账。没写的层沿用最新一行；组合与最新一行相同就拒绝（不空升）。

    没有钉子账时 ``from_n`` 必给（册 yaml 现在的 ``corpus:``），先把它按旧做法登成首行再追加。
    ``dev=True``：开发中的总号，各层版本号可以指向还没出的清单（先升号，再改语料，发版时 ``release_pin``）。
    只写账，不改册 yaml、不推中心库——新总号由调用方写进册 yaml（开发中再加 ``corpus_dev: true``）。"""
    import datetime
    import json
    rows = load_pins(ws, vol)
    if not rows:
        if from_n is None:
            raise ValueError(f"册 {vol} 还没有钉子账：要给册 yaml 现在的 corpus: 号（from_n）来登首行")
        first = resolve_pin(ws, vol, from_n)
        rows = [{**first, "date": datetime.date.today().isoformat(), "note": "迁移：原 corpus: %d" % from_n,
                 "legacy_token": True}]
    cur = rows[-1]
    new = {"global": cur.get("global") if global_ver is _KEEP else global_ver,
           "book": cur["book"] if book_ver is _KEEP else book_ver,
           "vol": cur.get("vol") if vol_ver is _KEEP else vol_ver}
    if new == {"global": cur.get("global"), "book": cur["book"], "vol": cur.get("vol")}:
        raise ValueError(f"册 {vol} 的三层版本与最新总号 {cur['n']} 相同（{new}），不空升")
    if not dev:
        _check_layers_exist(ws, vol, new)
    row = {"n": max(r["n"] for r in rows) + 1, **new,
           "date": datetime.date.today().isoformat(), "note": note}
    if dev:
        row["dev"] = True
    rows.append(row)
    p = pins_path(ws, vol)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return row


def versions(ws: Path) -> list[int]:
    d = pack_root(ws)
    if not d.is_dir():
        return []
    return sorted(int(p.name[1:]) for p in d.iterdir()
                  if p.is_dir() and p.name.startswith("v") and p.name[1:].isdigit()
                  and (p / "manifest.json").exists())


def manifest_path(ws: Path, version: int) -> Path:
    return pack_root(ws) / f"v{version}" / "manifest.json"


def check_files(ws: Path, man: dict) -> dict:
    """拿清单对当前文件：changed／missing／extra（清单之外新出现的）。"""
    changed, missing, listed = [], [], set()
    for it in man["items"]:
        listed.add((it["root"], it["path"]))
        if _not_corpus(it["root"], it["path"]):
            continue
        p = _base(it["root"], it["path"], ws) / it["path"]
        if not p.is_file():
            missing.append(f'{it["root"]}:{it["path"]}')
        elif _sha256(p) != it["sha256"]:
            changed.append(f'{it["root"]}:{it["path"]}')
    extra = [f'{i["root"]}:{i["path"]}' for i in collect(ws) if (i["root"], i["path"]) not in listed]
    return {"changed": changed, "missing": missing, "extra": extra}


def dev_pins(ws: Path) -> list[str]:
    """册 yaml 里写着 ``corpus_dev: true``（语料在开发）的册：只在本机用，不许推中心库（中心库只收正式版本号）。"""
    import yaml
    d = data_root_books(ws)
    out = []
    for f in sorted(d.glob("*.yaml")) if d is not None and d.is_dir() else []:
        try:
            from .book_config import effective_book_dict
            dev = effective_book_dict(f, apply_override=False).get("corpus_dev")   # 基础配置 ∪ 册 yaml；运行覆盖不是要推库的东西
        except Exception:                          # noqa: BLE001 —— 读不了的册配置不归这里管
            continue
        if dev:
            out.append(f"册 {f.stem} 写着 corpus_dev: true（语料还在开发），中心库只收正式版本号：先 "
                       f"guji corpus release 发版并去掉 corpus_dev，或改回上一个正式总号再推")
    return out


def data_root_books(ws: Path) -> Path | None:
    from .workspace import books_dir
    return books_dir(ws)


def push_problems(ws: Path) -> list[str]:
    """推进中心库前的保护（用户 10-20：语料库里任何内容变了，都要改版本号）。

    ① 最新一版清单登记的工作区文件被改了、缺了，或清单之外多了新语料文件：先 ``guji corpus build`` 出新版本一起推；
    ② 本机已有的某一版清单和库里不一样：旧版本不可改。
    只看工作区里的文件（root=ws）；引擎仓里的表随 cv 版本走，由起跑前硬校验管。"""
    out: list[str] = dev_pins(ws)
    vs = versions(ws)
    if not vs:
        return out
    last = vs[-1]
    r = check_files(ws, load_manifest(ws, last))
    live = lambda xs: [x for x in xs if x.startswith("ws:")]          # noqa: E731
    changed, missing, extra = live(r["changed"]), live(r["missing"]), live(r["extra"])
    if changed or missing or extra:
        out.append(f"语料库 v{last} 登记的文件内容变了（改了 {len(changed)}，缺 {len(missing)}，新增 {len(extra)}："
                   f"{(changed + missing + extra)[:4]}）；语料库任何内容变了都要改版本号——先 "
                   f"guji corpus build -w <工作区> 出 v{last + 1} 再推，或把文件改回去")
    return out


# ── 册钉子 ─────────────────────────────────────────────────────────────────────

#: 属于语料库的内容指纹字段（各 Step 参数类里自动填的那些）。钉了版本就整体换成 `corpus-vN`。
#: 不含：`db_fingerprint`／`human_fingerprint`（字形库）、`exclusions_fingerprint`（人裁累积）、
#: `model_fingerprint`／`shadow_model_fingerprint`（模型）——它们不是语料。
PIN_FIELDS: tuple[str, ...] = (
    "corpus_fingerprint", "witness_fingerprint", "lane_witness_fingerprint",
    "ledger_fingerprint", "variants_fingerprint", "variant_graph_fingerprint",
    "note_fingerprint", "iron_config_fingerprint", "group_flow_fingerprint",
)


#: 读语料库的 Step。册钉了版本后，这些步的指纹**整步**多带一个 `corpus-vN`（`engine._self_payload`），
#: 补上没有内容指纹的输入：形近表、`NEVER_MATCH_FAMILIES`、异体表／异体图、`rare_candidates` 的字表与部件库。
#: 登记在这里而不是各 Step 的 `StepSpec`：改 Step 模块源码会让 `code_hash` 变，没钉的册也跟着过期。
CORPUS_STEPS: frozenset[str] = frozenset({
    "glyph_match", "rare_candidates", "context_decide", "align_ref", "seed_admit",
})


def step_pin_token(step_id: str, book) -> str | None:
    """这一步这册书该带的语料库内容串；没钉或这步不读语料 → None（指纹不变）。"""
    v = getattr(book, "corpus", None)
    if not v or step_id not in CORPUS_STEPS:
        return None
    from .workspace import workspace_root
    return corpus_token(workspace_root(), v, getattr(book, "id", None), getattr(book, "corpus_dev", False))


def parse_pin(v) -> int | None:
    """册 yaml 的 `corpus:`：`1`／`"1"`／`"v1"` → 1；空 → None。"""
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    s = s[1:] if s.startswith("v") else s
    if not s.isdigit() or int(s) < 1:
        raise ValueError(f"册 yaml 的 corpus: 应是正整数版本号（如 1 或 v1），收到 {v!r}")
    return int(s)


def items_digest(items: list[dict]) -> str:
    """清单条目（root、path、sha256）排序后的哈希：指纹里的「语料内容」，**不含版本号**。"""
    import hashlib
    body = "\n".join(sorted(f'{i["root"]}\t{i["path"]}\t{i["sha256"]}' for i in items))
    return "corpus-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


_TOKEN_CACHE: dict[tuple[str, int, str | None], str] = {}


def corpus_token(ws: Path | None, version: int, vol: str | None = None, dev: bool = False) -> str:
    """这册语料库的指纹串：只取内容（清单条目哈希），不含版本号（sheldon 10-21）。

    **兼容**：这册还没有钉子账（殿本现在的 ``corpus: 9``），或这个总号是迁移行（账里 ``legacy_token: true``，
    ``append_pin`` 登首行时写）时仍返回旧写法 ``corpus-vN``，已有产物不过期；之后新升的总号才用内容哈希。开发中的总号（``dev``）一律用内容哈希。
    钉死的总号：取清单里登记的条目，清单不可变，算一次就缓存；这样钉着的册不受工作副本改动影响。
    开发中的总号（``dev``）：取工作副本当前的文件，所以开发期间改了表产物自动判过期；
    发版时清单就是那一刻的文件，内容哈希不变，指纹不变，不用 ``fp-migrate``。"""
    if ws is None:
        raise FileNotFoundError(f"册 yaml 钉了 corpus: {version}，但不知道工作区（设 GUJI_WORKSPACE 或给 -w）")
    if dev:
        items = collect(ws, cached=True) + (collect_vol(ws, vol, cached=True) if vol else [])
        return items_digest(items)
    rows = load_pins(ws, vol or "")
    if not rows or any(r["n"] == version and r.get("legacy_token") for r in rows):
        return f"corpus-v{version}"                    # 没有钉子账，或迁移行（legacy_token）：旧写法，指纹逐位不变
    key = (str(ws), version, vol)
    tok = _TOKEN_CACHE.get(key)
    if tok is None:
        try:
            man = load_manifest(ws, version, vol)
        except FileNotFoundError as e:
            raise FileNotFoundError(f"册 yaml 钉了 corpus: {version}，但{e}（先跑 guji corpus build -w {ws}）") from e
        tok = _TOKEN_CACHE[key] = items_digest(man["items"])
    return tok


_CHECKED: dict[tuple[str, int, str | None], None] = {}


def _check_pin_once(ws: Path | None, version: int, vol: str | None = None) -> None:
    """钉住的版本必须有清单；清单之后文件被改只警告一次。"""
    if ws is None:
        raise FileNotFoundError(f"册 yaml 钉了 corpus: {version}，但不知道工作区（设 GUJI_WORKSPACE 或给 -w）")
    key = (str(ws), version, vol)
    if key in _CHECKED:
        return
    try:
        man = load_manifest(ws, version, vol)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"册 yaml 钉了 corpus: {version}，但{e}（先跑 guji corpus build -w {ws}）") from e
    r = check_files(ws, man)
    _CHECKED[key] = None
    if r["changed"] or r["missing"]:
        print(f"  ⚠️  语料库 v{version} 的清单与当前文件不符（改了 {len(r['changed'])}，缺 {len(r['missing'])}）："
              f"{(r['changed'] + r['missing'])[:5]}——指纹只看版本号，这些改动不会让产物过期；"
              f"该出新版本就 guji corpus build，或把文件改回去", file=sys.stderr)


class CorpusDrift(RuntimeError):
    """钉住的语料库版本与当前文件不符：起跑前硬校验拒绝（共享方案 2.3 节）。"""


#: 起跑前硬校验：设成 ``warn`` 只警告不拒绝（临时绕过，比如正在出新版本）
DRIFT_ENV = "GUJI_CORPUS_DRIFT"
_CLEAN: dict[tuple[str, int, str | None], tuple] = {}


def _stat_sig(ws: Path, man: dict) -> tuple:
    """清单里各文件的 (大小, 修改时间)：没变就不重算哈希（控制台常驻进程里每次起跑都会来问）。"""
    out = []
    for it in man["items"]:
        p = _base(it["root"], it["path"], ws) / it["path"]
        try:
            st = p.stat()
            out.append((st.st_size, st.st_mtime_ns))
        except OSError:
            out.append(None)
    return tuple(out)


def require_pin_clean(ws: Path | None, version: int, vol: str | None = None) -> None:
    """钉住的版本：清单里的文件有改动或缺失就拒绝跑（``CorpusDrift``）。

    只看清单里登记过的文件；清单之外新出现的文件（``extra``）只警告——它们不在承诺里，
    该进下一版。代码常量（``NEVER_MATCH_FAMILIES``）随 ``code_hash`` 管，``guji corpus verify`` 照报。"""
    if ws is None:
        raise CorpusDrift(f"册 yaml 钉了 corpus: {version}，但不知道工作区（设 GUJI_WORKSPACE 或给 -w）")
    import os
    try:
        man = load_manifest(ws, version, vol)
    except FileNotFoundError as e:
        raise CorpusDrift(str(e)) from e
    key, sig = (str(ws), version, vol), _stat_sig(ws, man)
    if _CLEAN.get(key) == sig:
        return
    r = check_files(ws, man)
    bad = r["changed"] + r["missing"]
    if bad:
        msg = (f"语料库 v{version} 的清单与当前文件不符（改了 {len(r['changed'])}，缺 {len(r['missing'])}）："
               f"{bad[:5]}。出新版本（guji corpus build）并改钉，或把文件改回去；"
               f"临时绕过设 {DRIFT_ENV}=warn")
        if os.environ.get(DRIFT_ENV, "").lower() != "warn":
            raise CorpusDrift(msg)
        print(f"  ⚠️  {msg}", file=sys.stderr)
        return
    if r["extra"]:
        print(f"  ⚠️  语料库 v{version} 之后新出现 {len(r['extra'])} 个语料文件（{r['extra'][:3]}），"
              f"不在这版承诺里，出下一版时会收进去", file=sys.stderr)
    _CLEAN[key] = sig


def with_corpus_pin(p, book):
    """册钉了语料库版本时，把参数里的语料内容指纹换成版本号；没钉原样返回。

    只换**已经有值**的字段（开关没开的步这些字段是空的，保持为空）。必须重新构造而不是
    `model_copy`——跟 `_with_book_corpus` 一样，参数类的派生指纹在 `model_post_init` 里填，
    非空就不再重填。"""
    v = getattr(book, "corpus", None)
    if not v:
        return p
    fields = [f for f in PIN_FIELDS if getattr(p, f, "")]
    if not fields:
        return p
    from .workspace import workspace_root
    dev = getattr(book, "corpus_dev", False)
    if not dev:
        _check_pin_once(workspace_root(), v, getattr(book, "id", None))
    tok = corpus_token(workspace_root(), v, getattr(book, "id", None), dev)
    return type(p)(**{**p.model_dump(), **{f: tok for f in fields}})
