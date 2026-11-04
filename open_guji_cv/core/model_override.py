# -*- coding: utf-8 -*-
"""一个环境里两本书钉同一模型的不同版本（`doc/design/模型系统.md` 4.2 第 4 条）。

cv 仓 ``models/`` 只有一份。册钉了 ``model: N``、而清单里某个 cv 仓模型（``root: repo``）的内容和仓里那份不同时，
把这版清单的**全部** cv 仓模型按 sha 摆进 ``$GUJI_DATA_HOME/model-cache/<清单摘要>/<原相对路径>``（仓里内容对得上的
直接拷，对不上的从 R2 取），再把读模型的模块的缺省路径改指那里。仓里内容与清单一致的册什么都不改。

**为什么不改 Step 代码**：读模型的模块（``seg.cut_select``、``clustering.cnn_candidates``、``utils.rr_clf``、
``groups.ids_online``）在各 Step 的 ``code_deps`` 里，一改各书产物判过期。这里只在运行时换模块属性（缺省路径、
函数缺省参数），模块源码不动；各处模型指纹本来就按**文件内容**算，所以换过去的产物指纹跟着钉住的内容走——
内容和仓里一样就逐位不变，不一样就该过期。

切换点：``Engine`` 建立时（按册 ``activate(book)``；没钉或不需要时还原）、并行 worker 初始化时（同一册再算一遍，
缓存已摆好）、``guji pipeline``／``step`` 起跑前（`ops/prep.ensure_model_pin`，传 ``placer`` 联网取缺的文件）。
``Engine`` 和 worker 不联网：缺的文件起跑前校验（`model_pack.require_model_clean`）拒跑。
"""
from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

from . import model_pack as mp

CACHE_DIR = "model-cache"

#: (模块, 属性)：模块级缺省路径（调用时才读，换属性即可）
_ATTRS: tuple[tuple[str, str], ...] = (
    ("open_guji_cv.pagetype_model.model", "DEFAULT_MODEL"),
    ("open_guji_cv.shadow.model", "DEFAULT_MODEL"),
    ("open_guji_cv.shadow.model", "PROMOTE_MODEL"),
    ("open_guji_cv.utils.rr_clf", "MODEL_DIR"),
    ("open_guji_cv.seg.cut_select", "DEFAULT_CKPT"),
    ("open_guji_cv.clustering.cnn_candidates", "DEFAULT_CKPT"),
)
#: 定义时就把缺省路径写进参数缺省值的函数（``def f(ckpt=DEFAULT_CKPT)``）
_CNN = "open_guji_cv.clustering.cnn_candidates"
_CNN_FUNCS = ("fingerprint", "full_fingerprint", "shared", "CnnCandidates.__init__")
_IDS = "open_guji_cv.groups.ids_online"

_ORIG: dict[tuple[str, str], object] = {}     # 原值，还原用
_ACTIVE: list = [None]                         # 当前生效的缓存根（None＝用仓里的）


def active_root() -> Path | None:
    return _ACTIVE[0]


def cache_root(man: dict) -> Path:
    from .workspace import data_home
    return data_home() / CACHE_DIR / str(man.get("digest") or "")[:16]


def repo_drift(man: dict) -> list[dict]:
    """清单里 cv 仓模型中，仓里有但内容不同的（缺的不算：缺的照旧取回仓里）。"""
    out = []
    for it in man.get("items") or []:
        if it["root"] != "repo":
            continue
        p = mp.REPO_ROOT / it["path"]
        if p.is_file() and mp._sha_cached(p) != it["sha256"]:
            out.append(it)
    return out


def materialize(man: dict, placer=None) -> tuple[Path, list[str]]:
    """把清单的 cv 仓模型摆进缓存根，返回 (根, 摆不出来的路径)。``placer([(sha, 目标路径)])`` 从 R2 取
    （`ops/model_blobs._place`；core 不反向依赖 ops，由调用方传）；不给就不联网。"""
    root = cache_root(man)
    todo: list[tuple[str, Path]] = []
    for it in man.get("items") or []:
        if it["root"] != "repo":
            continue
        dst = root / it["path"]
        if dst.is_file() and mp._sha_cached(dst) == it["sha256"]:
            continue
        src = mp.REPO_ROOT / it["path"]
        if src.is_file() and mp._sha_cached(src) == it["sha256"]:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".part")
            shutil.copyfile(src, tmp)
            tmp.replace(dst)
        else:
            todo.append((it["sha256"], dst))
    if todo and placer is not None:
        placer(todo)
    bad = [str(p.relative_to(root)) for sha, p in todo if not (p.is_file() and mp._sha_cached(p) == sha)]
    return root, bad


def plan(book, placer=None) -> Path | None:
    """这册该用的缓存根；不需要换（没钉、仓里一致、没有工作区）时 None。摆不齐也返回根（之后起跑前校验拒跑）。"""
    v = getattr(book, "model", None)
    if not v:
        return None
    from .workspace import workspace_root
    ws = workspace_root()
    if ws is None:
        return None
    try:
        man = mp.load_manifest(ws, v)
    except FileNotFoundError:
        return None
    if not repo_drift(man):
        return None
    root, bad = materialize(man, placer)
    if bad:
        print(f"  ⚠️  模型总号 m{v} 有 {len(bad)} 个 cv 仓模型摆不进本册缓存（{bad[:3]}），起跑前校验会拒跑",
              file=sys.stderr)
    return root


def activate(book, placer=None) -> Path | None:
    """按册切换：要换就换到缓存根，不要就还原。返回生效的根。"""
    root = plan(book, placer)
    apply(root)
    return root


def _remap(p, root: Path | None):
    """仓里的路径换到缓存根下同一相对位置（缓存里有才换）。"""
    if root is None or not isinstance(p, (str, Path)):
        return p
    try:
        rel = Path(p).resolve().relative_to(mp.REPO_ROOT)
    except ValueError:
        return p
    q = root / rel
    if not q.exists():
        return p
    return str(q) if isinstance(p, str) else q


def _get(mod, dotted: str):
    obj = mod
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return getattr(obj, "__wrapped__", obj)


def apply(root: Path | None) -> None:
    """把读模型模块的缺省路径换到 ``root``（None＝还原成原值）。同一根可重复调用：缓存后来摆齐了的项再调一次就换上。"""
    if root is None and _ACTIVE[0] is None:
        return                                   # 没换过：什么都不碰（没钉的册零开销）
    for modname, attr in _ATTRS:
        mod = importlib.import_module(modname)
        key = (modname, attr)
        if key not in _ORIG:
            _ORIG[key] = getattr(mod, attr)
        setattr(mod, attr, _remap(_ORIG[key], root))
    cnn = importlib.import_module(_CNN)
    for name in _CNN_FUNCS:
        fn = _get(cnn, name)
        key = (_CNN, name)
        if key not in _ORIG:
            _ORIG[key] = fn.__defaults__
        orig = _ORIG[key]
        fn.__defaults__ = tuple(_remap(d, root) for d in orig) if orig else orig
    cnn.shared.cache_clear()                     # lru_cache 按实参缓存：缺省参数换了要清
    ids = importlib.import_module(_IDS)
    key = (_IDS, "unet_path")
    if key not in _ORIG:
        _ORIG[key] = ids.unet_path
    orig_unet = _ORIG[key]
    if root is None:
        ids.unet_path = orig_unet
    else:
        ids.unet_path = lambda g, _f=orig_unet, _r=root: _remap(_f(g), _r)
    for fn in ("bank_path", "whole_bank_path"):          # 模板库也是模型（ids_bank／ids_whole_bank）：同 unet_path 的换法
        key = (_IDS, fn)
        if key not in _ORIG:
            _ORIG[key] = getattr(ids, fn)
        orig_fn = _ORIG[key]
        if root is None:
            setattr(ids, fn, orig_fn)
        else:
            setattr(ids, fn, lambda g, _f=orig_fn, _r=root: _remap(_f(g), _r))
    _ACTIVE[0] = root
    mp.REPO_OVERRIDE[0] = root
