# -*- coding: utf-8 -*-
"""全字表字形向量包（hanzi 库 B2，`doc/design/汉字字形与关系库-总设计.md`）。

Step5-b 稀见字候选与「以字找字」都要「每个字的字体模板向量」：四套字体（8 个字体档）渲染成 64² 图、
过 CNN 主干、取均值再单位化（`cnn_candidates.build_emb_matrix`）。每台机器现建 7 万字约 40 分钟，
这里改成**一处建好、按版本发布、各机按需拉**。

## 版本（用户 10-20：将来会重新训练，向量会不一样，必须做版本控制）

一个字的向量只取决于四样东西，全部进版本号，任何一样变了就是另一版，旧版照留：

| 规格字段 | 是什么 | 取法 |
|---|---|---|
| `ckpt_fp` | 模型 checkpoint 内容指纹 | `cnn_candidates.fingerprint`（sha256 前 12 位） |
| `font_fp` | 模板字体集内容指纹 | `font_candidates.font_set_fingerprint` |
| `code_fp` | 渲染与前向的代码 | `build_emb_matrix`、`synth.render_char`、`_build_net` 的源码哈希 |
| `extra` | 额外真刻本图源 | `cnn_candidates.EMB_EXTRA_SPECS` 里就绪的那些（现为空） |

版本号 `emb-<规格的 sha1 前 12 位>`。清单 `config/hanzi/emb/<版本>.json` 进 git（记规格、文件 sha、行数），
向量文件按 sha 进 R2（取法同 hanzi 库：`hanzi.pack.get_blob`，公开域名、不要令牌、下完核 sha）。

**取用只认当前规格**：`find(current_spec())` 找不到同规格的版本就返回 None，调用方照旧本地现建——
换了模型、字体或代码而包还没出，绝不会拿旧向量冒充。

## 文件

- `vectors-NN.npy`：float32 `[n, 256]` 按行切成每片 32,768 行（约 32 MB，Worker 单次上传有上限），
  拼起来逐行与 `chars.txt` 对应（不用 float16：R 道 09-27 实测 top-1 会变 1%）；
- `chars.txt`：建成的字，一行一字，码位序；
- `failed.txt`：全部字体都渲染不出的字（产线建索引时同样会跳过，materialize 据此逐位复现）。

不在任何 Step 的 `code_deps` 里；Step5-b 的磁盘缓存 `emb_<key>.npz` 由 `guji cache pull-rare-index`
用本包落成（建包在 `ops/emb_pack_build.py`），`_emb_index` 照旧按原 key 命中，产线代码一行不改。
"""
from __future__ import annotations

import hashlib
import inspect
import io
import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
EMB_DIR = REPO / "config" / "hanzi" / "emb"
FILES = ("chars.txt", "failed.txt")       # 另有向量分片 vectors-NN.npy，见清单 files


def code_fingerprint() -> str:
    """渲染与前向代码的指纹：这几段源码一改，同一模型同一字体算出的向量就可能不同。"""
    from . import cnn_candidates as cc
    from . import synth
    src = "".join(inspect.getsource(f) for f in (cc.build_emb_matrix, synth.render_char, cc._build_net))
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:12]


def current_spec(ckpt: Path | None = None) -> dict:
    """本机现役的规格（模型、字体、代码、额外图源）。"""
    from . import cnn_candidates as cc
    from .font_candidates import font_set_fingerprint
    ckpt = Path(ckpt or cc.DEFAULT_CKPT)
    return {"ckpt": ckpt.parent.name, "ckpt_fp": cc.fingerprint(ckpt), "font_fp": font_set_fingerprint(),
            "code_fp": code_fingerprint(),
            "extra": sorted(sp for sp in cc.EMB_EXTRA_SPECS if cc._spec_ready(sp))}


SPEC_KEYS = ("ckpt_fp", "font_fp", "code_fp", "extra")


def version_of(spec: dict) -> str:
    core = {k: spec[k] for k in SPEC_KEYS}
    return "emb-" + hashlib.sha1(json.dumps(core, sort_keys=True).encode()).hexdigest()[:12]


def manifests(emb_dir: Path = EMB_DIR) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(emb_dir).glob("emb-*.json"))]


def find(spec: dict, emb_dir: Path = EMB_DIR) -> dict | None:
    """与 `spec` 同规格的已发布版本；没有 → None（调用方本地现建）。"""
    v = version_of(spec)
    return next((m for m in manifests(emb_dir) if m["version"] == v), None)


# ── 读 ─────────────────────────────────────────────────

class EmbPack:
    """一版向量包：`row(字)`、`vectors(字…)`、`materialize(字表)`。"""

    def __init__(self, manifest: dict, mat: np.ndarray, chars: list[str], failed: set[str]):
        self.manifest = manifest
        self.version = manifest["version"]
        self.mat = mat
        self.chars = chars
        self.index = {c: i for i, c in enumerate(chars)}
        self.failed = failed

    @classmethod
    def load(cls, manifest: dict, blob_dir: Path | None = None, fetch=None,
             download: bool = True) -> EmbPack | None:
        """按清单取全部文件（本机 blob 缓存 → R2）；`download=False` 时本机缺任何一个就返回 None。"""
        from ..hanzi.pack import blob_cache_path, get_blob
        paths = {}
        for name in sorted(manifest["files"]):
            sha = manifest["files"][name]["sha256"]
            if not download and not blob_cache_path(sha, blob_dir).exists():
                return None
            paths[name] = get_blob(sha, blob_dir, fetch, label=f"{manifest['version']}/{name}")
        shards = [np.load(io.BytesIO(paths[n].read_bytes()), allow_pickle=False)
                  for n in sorted(paths) if n.startswith("vectors")]
        mat = np.concatenate(shards) if shards else np.zeros((0, manifest["dim"]), np.float32)
        chars = paths["chars.txt"].read_text(encoding="utf-8").splitlines()
        failed = set(paths["failed.txt"].read_text(encoding="utf-8").splitlines())
        if mat.shape != (len(chars), manifest["dim"]):
            raise ValueError(f"{manifest['version']}：向量 {mat.shape} 与字数 {len(chars)} 对不上")
        return cls(manifest, mat, chars, failed)

    def vectors(self, chars) -> dict[str, np.ndarray]:
        return {c: self.mat[self.index[c]] for c in chars if c in self.index}

    def materialize(self, cs, compute=None) -> tuple[np.ndarray, list[str]]:
        """字表 → `(mat, names)`，与产线 `build_emb_matrix(cs)` 逐位相同：按 `cs` 原顺序取行，
        包里记为渲染失败的字跳过（产线也跳过）；包外的字（建包时没在全字表里）交 `compute(字…)` 现算，
        没给 `compute` 就报错——宁可不出，不出一份缺行的索引。"""
        cs = tuple(cs)
        todo = [c for c in cs if c not in self.index and c not in self.failed]
        got: dict[str, np.ndarray] = {}
        if todo:
            if compute is None:
                raise KeyError(f"{len(todo)} 字不在向量包 {self.version} 里（如 {''.join(todo[:10])}），要现算")
            m, ns = compute(tuple(todo))
            got = dict(zip(ns, m))
        rows, names = [], []
        for c in cs:
            if c in self.index:
                rows.append(self.mat[self.index[c]])
            elif c in got:
                rows.append(got[c])
            else:
                continue
            names.append(c)
        mat = np.stack(rows).astype(np.float32) if rows else np.zeros((0, self.manifest["dim"]), np.float32)
        return mat, names


def load_current(download: bool = True, blob_dir: Path | None = None, fetch=None,
                 emb_dir: Path = EMB_DIR) -> EmbPack | None:
    """本机现役规格对应的包；没有同规格的版本、或 `download=False` 而本机没缓存 → None。"""
    m = find(current_spec(), emb_dir)
    return EmbPack.load(m, blob_dir, fetch, download) if m else None
