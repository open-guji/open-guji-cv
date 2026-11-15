# -*- coding: utf-8 -*-
"""模型系统第一期：模型卡、模型总号清单、册钉 ``model: N``（设计见 `doc/design/模型系统.md`）。

和语料（`core/corpus_pin.py`）、字形（`core/glyph_pin.py`）并列的第三个系统。一期只做**登记与钉住**，
模型文件还在原处（cv 仓 ``models/``、数据目录 ``config/groups/``），各 Step 读模型的路径不变：

- ``KINDS``：已知的模型种类（在哪、归哪层、谁读它）。新模型先在这里登记，才进清单。
- ``collect(ws)``：按 ``KINDS`` 扫出这本书现在用的模型，每个文件一张卡（``model/1``）：
  kind、root、path、size、sha256、level（global／group／book，**按从哪里来**定，用户 11-04）、owner。
- 清单 ``config/model-pack/m<N>/manifest.json``（数据目录，随 ``guji db sync`` 进中心库）：
  一本书的模型总号。任何一个模型文件变了，``guji model build`` 出 ``m<N+1>``；清单只写一次。
- 册 yaml ``model: N``：钉住这本书的模型总号。钉了之后

  1. 起跑前硬校验（``require_model_clean``）：清单里的文件和当前文件对不上就拒跑
     （``GUJI_MODEL_DRIFT=warn`` 临时放行）；
  2. **补缺口**：册同时钉了语料时，``seed_admit.group_flow_fingerprint`` 不再只剩 ``corpus-…``，
     而是 ``corpus-…+model-…``——L2 小头、rr_clf、rr_shape、book_knn、IDS 模型换了，这册要过期。
     没写 ``model:`` 的册指纹逐位不变（opt-in）。

二期（另开 PR）：大文件按 sha256 进 R2、本机 blob 缓存按 hash 取（``resolve``），cv 仓 ``models/`` 搬走；
global／group 层清单放中心库共用工作区。本模块不引 ``datastore``（架构守卫）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

PACK_DIR = "config/model-pack"
SCHEMA = "model-pack/1"
CARD_SCHEMA = "model/1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DRIFT_ENV = "GUJI_MODEL_DRIFT"

#: 殿本（武英殿刻本四庫全書總目）的书 ID：在它上面训的模型归这本书（按从哪里来）。
DIANBEN = "96mid1ogzk"


@dataclass(frozen=True)
class Kind:
    """一种模型：文件在哪（``root`` = repo／data，``pat`` = glob），归哪层、谁的，谁读它。"""
    kind: str
    root: str
    pat: str
    level: str            # global／group／book：按训练数据从哪里来
    owner: str            # global → "global"；book → 书 ID；group → 组名；"*" = 文件所在的那本书
    consumers: tuple[str, ...]
    note: str = ""


KINDS: tuple[Kind, ...] = (
    # cv 仓 models/（进 git）。owner 按训练数据来源：殿本训的归殿本，合成／公开数据训的归 global。
    Kind("glyph_cnn", "repo", "models/glyph_cnn_r*/best.pt", "book", DIANBEN,
         ("rare_candidates", "glyph_match"), "殿本人裁字形训的识别 CNN；换了要重标 3 个门槛"),
    Kind("partition_unet", "repo", "models/partition_unet_v2/model.pt", "global", "global",
         ("cut_select",), "合成对训练的切分判官"),
    Kind("pagetype", "repo", "models/pagetype/pagetype_v1.*", "book", DIANBEN,
         ("border_detect_gate",), "殿本页型标注训的页型分类"),
    Kind("shadow_gate", "repo", "models/shadow_admit/shadow_gate_v*.*", "book", DIANBEN,
         ("seed_admit",), "殿本 vol02/03 人裁训的（见 shadow_gate_v2.json train_books）"),
    # 字组 IDS 切分 U-Net：原先算在语料底库（config/groups/<组>/），11-04 挪进模型系统
    Kind("ids_unet", "repo", "config/groups/*/unet.npz", "book", DIANBEN,
         ("seed_admit",), "殿本本组人标切线训的三段切分 U-Net（纯 numpy）"),
    # 字组 IDS 模板库：从殿本人裁字块挖出来的（source.labels），按「从哪里来」归殿本；11-04 起不再算 global 语料
    Kind("ids_bank", "repo", "config/groups/*/ids_bank.json", "book", DIANBEN,
         ("seed_admit",), "殿本人裁挖的部件模板库（在线 IDS 判法）"),
    Kind("ids_whole_bank", "repo", "config/groups/*/whole_bank.json", "book", DIANBEN,
         ("seed_admit",), "殿本人裁挖的整字模板库（两路一致的整字 HOG）"),
    Kind("rr_clf", "repo", "models/rr_clf/*", "book", DIANBEN,
         ("seed_admit",), "入人八 字形分类（殿本刻形）"),
    # 数据目录 config/groups/（各书自己的，中心库同步）
    Kind("l2_head", "data", "config/groups/l2model/*.json", "book", "*", ("seed_admit",),
         "文意 L2 小头（SikuRoBERTa 上的线性头）"),
    Kind("rr_shape", "data", "config/groups/rr_shape.json", "book", "*", ("seed_admit",), "入人八 书级刻形判法"),
    Kind("pair_shape", "data", "config/groups/pair_shape*.json", "book", "*", ("seed_admit",), "两字刻形二选一"),
    Kind("book_knn", "data", "config/groups/book_knn/*.json", "book", "*", ("seed_admit",), "书级刻形近邻库"),
    Kind("ids_model", "data", "config/groups/ids/*", "book", "*", ("seed_admit",), "在线 IDS 判法"),
)

#: 外部模型：不在本机文件里，按版本号钉（内容哈希由上游保证）。进清单的 ``external`` 段。
EXTERNAL: dict[str, dict] = {
    "sikuroberta": {"kind": "lm_encoder", "level": "global", "owner": "global",
                    "repo": "SIKU-BERT/sikuroberta", "revision": "bb25260d5c321924fe4fb353c09191c0aaf5c5c6",
                    "consumers": ["seed_admit"], "note": "L2 小头的底座；换 revision 要重训小头"},
}

_SKIP = {"README.md", ".gitkeep"}


def _data_root(ws: Path) -> Path:
    from .workspace import data_root
    return data_root(ws) or Path(ws)


#: 本册改用的 cv 仓模型根（`core/model_override`：两本书钉同一模型的不同版本）；``[None]``＝仓本身
REPO_OVERRIDE: list = [None]


def _base(root: str, ws: Path, real: bool = False) -> Path:
    if root == "repo":
        return REPO_ROOT if real or REPO_OVERRIDE[0] is None else REPO_OVERRIDE[0]
    return _data_root(ws)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


_SHA_CACHE: dict[tuple[str, int, int], str] = {}


def _sha_cached(p: Path) -> str:
    st = p.stat()
    key = (str(p), st.st_size, st.st_mtime_ns)
    h = _SHA_CACHE.get(key)
    if h is None:
        h = _SHA_CACHE[key] = _sha256(p)
    return h


def _book_id(ws: Path) -> str:
    """工作区对应的书：中心库工作区名（``.central.json`` 的 ``ws``），没迁的用目录名。"""
    from .workspace import central_marker
    m = central_marker(Path(ws)) or {}
    return str(m.get("ws") or Path(ws).name)


def collect(ws: Path, cached: bool = False, real: bool = False) -> list[dict]:
    """这本书现在用的模型，每个文件一张卡；按 (root, path) 排序。``real``：cv 仓模型一律看仓本身（出新号用），
    不看本册改用的缓存根。"""
    sha = _sha_cached if cached else _sha256
    book = _book_id(ws)
    seen: dict[tuple[str, str], dict] = {}
    for k in KINDS:
        base = _base(k.root, ws, real)
        for p in sorted(base.glob(k.pat)):
            if not p.is_file() or p.name in _SKIP:
                continue
            rel = p.relative_to(base).as_posix()
            if (k.root, rel) in seen:
                continue
            card = {
                "schema": CARD_SCHEMA, "kind": k.kind, "root": k.root, "path": rel,
                "size": p.stat().st_size, "sha256": sha(p), "level": k.level,
                "owner": book if k.owner == "*" else k.owner, "consumers": list(k.consumers)}
            src = provenance(k.kind, rel)
            if src:
                card["source"] = src
            seen[(k.root, rel)] = card
    return [seen[x] for x in sorted(seen)]


PROVENANCE = "config/model-provenance.json"
_PROV: dict[str, dict] = {}


def provenance(kind: str, rel: str = "") -> dict:
    """模型卡的出处（训练脚本、训练数据、联动门槛；``config/model-provenance.json``）。不进清单哈希。"""
    key = str(REPO_ROOT)
    if key not in _PROV:
        try:
            _PROV[key] = json.loads((REPO_ROOT / PROVENANCE).read_text(encoding="utf-8")).get("kinds") or {}
        except (OSError, ValueError):
            _PROV[key] = {}
    e = dict(_PROV[key].get(kind) or {})
    if e.get("path") and e["path"] != rel:
        return {}
    return e


def items_digest(items: list[dict], external: dict | None = None) -> str:
    """清单内容的哈希（不含总号）：指纹里的「模型内容」。"""
    body = "\n".join(sorted(f'{i["root"]}\t{i["path"]}\t{i["sha256"]}' for i in items))
    for name in sorted(external or {}):
        body += f"\next\t{name}\t{(external or {})[name].get('revision', '')}"
    return "model-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def pack_root(ws: Path) -> Path:
    return _data_root(ws) / PACK_DIR


def versions(ws: Path) -> list[int]:
    d = pack_root(ws)
    if not d.is_dir():
        return []
    return sorted(int(x.name[1:]) for x in d.iterdir()
                  if x.name.startswith("m") and x.name[1:].isdigit() and (x / "manifest.json").is_file())


def manifest_path(ws: Path, version: int) -> Path:
    return pack_root(ws) / f"m{version}" / "manifest.json"


def load_manifest(ws: Path, version: int) -> dict:
    p = manifest_path(ws, version)
    if not p.is_file():
        have = versions(ws)
        raise FileNotFoundError(f"没有模型清单 m{version}（{p}；已有 {['m%d' % v for v in have] or '无'}）")
    return json.loads(p.read_text(encoding="utf-8"))


def build(ws: Path, version: int | None = None, note: str = "", dry_run: bool = False) -> dict:
    """出新的模型总号清单；内容和最新一版一样就不出（返回 ``{"unchanged": N}``）。清单只写一次。"""
    items = collect(ws, real=True)
    have = versions(ws)
    if have and version is None:
        last = load_manifest(ws, have[-1])
        if items_digest(last["items"], last.get("external")) == items_digest(items, EXTERNAL):
            return {"unchanged": have[-1], "path": str(manifest_path(ws, have[-1]))}
    n = version if version is not None else (have[-1] + 1 if have else 1)
    if n in have:
        raise ValueError(f"模型清单 m{n} 已存在，清单只写一次；不给 --version 出下一号")
    man = {"schema": SCHEMA, "version": n, "book": _book_id(ws), "note": note,
           "items": items, "external": EXTERNAL, "digest": items_digest(items, EXTERNAL)}
    p = manifest_path(ws, n)
    if not dry_run:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"version": n, "path": str(p), "items": len(items), "digest": man["digest"], "dry_run": dry_run}


def check_files(ws: Path, man: dict) -> dict:
    """清单 vs 当前文件：changed／missing（清单有、文件没了）／extra（新出现、没登记）。"""
    listed = {(i["root"], i["path"]): i["sha256"] for i in man.get("items") or []}
    now = {(i["root"], i["path"]): i["sha256"] for i in collect(ws, cached=True)}
    fmt = lambda k: f"{k[0]}:{k[1]}"                       # noqa: E731
    return {"changed": sorted(fmt(k) for k in listed if k in now and now[k] != listed[k]),
            "missing": sorted(fmt(k) for k in listed if k not in now),
            "extra": sorted(fmt(k) for k in now if k not in listed)}


def parse_pin(v) -> int | None:
    """册 yaml 的 ``model:``：``1``／``"m1"`` → 1；空 → None。"""
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    s = s[1:] if s.startswith("m") else s
    if not s.isdigit() or int(s) < 1:
        raise ValueError(f"册 yaml 的 model: 应是正整数模型总号（如 1 或 m1），收到 {v!r}")
    return int(s)


class ModelDrift(RuntimeError):
    """钉住的模型总号与当前文件不符：起跑前拒绝。"""


#: 读模型的 Step（钉了 ``model:`` 时这些步起跑前要校验）
MODEL_STEPS: frozenset[str] = frozenset(c for k in KINDS for c in k.consumers)

_TOKEN: dict[tuple[str, int], str] = {}
_CLEAN: dict[tuple[str, int], tuple] = {}


def model_token(ws: Path | None, version: int) -> str:
    """钉住的总号的指纹串：清单内容哈希（不含号）。清单不可变，算一次缓存。"""
    if ws is None:
        raise FileNotFoundError(f"册 yaml 钉了 model: {version}，但不知道工作区（设 GUJI_WORKSPACE 或给 -w）")
    key = (str(ws), version)
    if key not in _TOKEN:
        man = load_manifest(ws, version)
        _TOKEN[key] = man.get("digest") or items_digest(man["items"], man.get("external"))
    return _TOKEN[key]


def require_model_clean(ws: Path | None, version: int) -> None:
    """清单里的模型文件有改动或缺失就拒跑（``ModelDrift``）；新出现没登记的只警告。"""
    if ws is None:
        raise ModelDrift(f"册 yaml 钉了 model: {version}，但不知道工作区（设 GUJI_WORKSPACE 或给 -w）")
    try:
        man = load_manifest(ws, version)
    except FileNotFoundError as e:
        raise ModelDrift(f"{e}（先跑 guji model build -w {ws}）") from e
    sig = tuple(sorted((i["root"], i["path"]) for i in man["items"]))
    key = (str(ws), version)
    r = check_files(ws, man)
    bad = r["changed"] + r["missing"]
    if bad:
        msg = (f"模型总号 m{version} 的清单与当前文件不符（改了 {len(r['changed'])}，缺 {len(r['missing'])}）："
               f"{bad[:5]}。出新总号（guji model build）并改钉，或把文件换回去；临时绕过设 {DRIFT_ENV}=warn")
        if os.environ.get(DRIFT_ENV, "").lower() != "warn":
            raise ModelDrift(msg)
        print(f"  ⚠️  {msg}", file=sys.stderr)
        return
    if r["extra"] and _CLEAN.get(key) != sig:
        print(f"  ⚠️  模型总号 m{version} 之后新出现 {len(r['extra'])} 个模型文件（{r['extra'][:3]}），"
              f"不在这版里，出下一号时会收进去", file=sys.stderr)
    _CLEAN[key] = sig


def pinned_group_flow(tok: str, book) -> str:
    """钉了语料的册：``group_flow_fingerprint`` 的替换值。也钉了 ``model:`` 时并上模型内容（补缺口）。"""
    v = getattr(book, "model", None)
    if not v:
        return tok
    from .workspace import workspace_root
    return f"{tok}+{model_token(workspace_root(), v)}"


# ── cv 自带的模型表（二期 4.2 第 1 条）────────────────────────────────────────────
#: cv 仓 ``models/`` 里每个模型文件的路径 → sha256。没钉 ``model:`` 的书靠它取模型：
#: ``models/`` 搬出 git 以后，cv 只带这张表，文件按 sha 从 R2 取回、放回 ``models/<路径>``。
REGISTRY = "config/model-registry.json"


def repo_items() -> list[dict]:
    """cv 仓 ``models/`` 里登记过种类的模型文件（root=repo 的卡）。"""
    return [i for i in collect(REPO_ROOT, real=True) if i["root"] == "repo"]


def build_registry() -> dict:
    """按当前 ``models/`` 重写模型表（只在文件都在时跑；发版删文件前最后一次）。"""
    items = [{k: i[k] for k in ("kind", "path", "size", "sha256", "level", "owner")} for i in repo_items()]
    reg = {"schema": "model-registry/1", "items": items}
    p = REPO_ROOT / REGISTRY
    p.write_text(json.dumps(reg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"path": str(p), "items": len(items)}


def load_registry() -> list[dict]:
    p = REPO_ROOT / REGISTRY
    if not p.is_file():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("items") or []


def missing_repo_models() -> list[dict]:
    """模型表里登记、本机 ``models/`` 下没有的文件。"""
    return [i for i in load_registry() if not (REPO_ROOT / i["path"]).exists()]
