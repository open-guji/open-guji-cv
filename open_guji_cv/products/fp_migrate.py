"""路径参数出指纹之后的 manifest 迁移：只重写指纹，不重算产物（K238，2026-09-29）。

背景：`StepSpec.path_params` 把 `glyph_match.db_path` 等路径字段剔出 `params_hash` /
`self_hash`。**升级后所有已有 manifest 里这几步的指纹都对不上新公式**——同机的旧产物
和云端整包导入服务器的产物都会判过期。产物本身没问题，只是指纹公式变了；这里把
manifest 条目的 `fingerprint` / `params_hash` / `self_hash` 按新公式重写，产物文件不动。

**只在「唯一的差别是路径」时才改写。** 老条目只存了哈希、没存参数，所以拿不到当时的
路径，做法是让调用方说出老路径（`--old-path glyph_match.db_path=/云端/路径`），本模块用
「老路径 + 老公式」重算一遍指纹，**与条目里记的逐位相等才改**——这一下同时证明了代码、
版本、其余参数、册配置、上游都没变，否则本来就该过期的条目会被这次迁移洗成新鲜。
对不上的条目原样不动，报原因。

老路径说不清时用 `trust=True`（CLI `--trust`）：不验老指纹，只要求上游产物 sha 与现值
一致、产物文件的 sha256 与条目记的一致。它**不能**发现代码/参数变了，所以是显式开关，
默认关。

不碰：已是新指纹的条目、`status != ok` 的条目、产物文件缺失或 sha 对不上的条目、上游
产物已变的条目。`invalidated` / `recheck` / `soft` / `book` 字段原样带过去（迁移只改指纹
三件，不把「显式失效」洗掉）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Iterable

from ..core.engine import Engine, _self_payload, params_hash
from ..core.spec import page_key
from ..core.step import STEPS


def parse_old_paths(items: Iterable[str]) -> dict[str, dict[str, str]]:
    """`["glyph_match.db_path=/x/glyph.db", ...]` → {step: {field: 老值}}。"""
    out: dict[str, dict[str, str]] = {}
    for it in items or ():
        key, sep, val = it.partition("=")
        sid, dot, field = key.partition(".")
        if not (sep and dot and sid and field):
            raise ValueError(f"--old-path 要写成 step.field=值，收到 {it!r}")
        out.setdefault(sid, {})[field] = val
    return out


def _fp(step, book, params, ups: dict[str, str], *, path_in_hash: bool) -> tuple[str, str]:
    """(fingerprint, params_hash)。`path_in_hash=True` = 2026-09-29 之前的老公式。"""
    ph = params_hash(params, step.spec.soft_params, () if path_in_hash else step.spec.path_params)
    payload = {**_self_payload(step, book, ph), "upstream": ups}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24], ph


def _old_params(step, params, old: dict[str, str]):
    """把路径字段换成老值。重新构造以外不需要别的——指纹类字段已在 dump 里，不会被重填。"""
    bad = [f for f in old if f not in step.spec.path_params]
    if bad:
        raise ValueError(f"{step.spec.id}: {bad} 不是路径参数（path_params={step.spec.path_params}）")
    return type(params)(**{**params.model_dump(), **old})


def migrate_book(eng: Engine, pages: list[int], *, old_paths: dict[str, dict[str, str]] | None = None,
                 trust: bool = False, apply: bool = False,
                 steps: list[str] | None = None) -> dict:
    """逐步逐页迁移。返回 {step: {"migrated": n, "already": n, "skipped": {原因: n}}}。
    `apply=False` 是干跑：算得一模一样，只是不写 manifest。"""
    old_paths = old_paths or {}
    report: dict[str, dict] = {}
    for sid in eng.pipeline.steps:
        step = STEPS[sid]
        if not step.spec.path_params or (steps and sid not in steps):
            continue
        params = eng.ctx.params_for(step)
        old_params = _old_params(step, params, old_paths[sid]) if sid in old_paths else None
        row = {"migrated": 0, "already": 0, "skipped": {}}
        report[sid] = row
        manifest = eng.store.manifest(eng.book.id, sid)

        def skip(why: str) -> None:
            row["skipped"][why] = row["skipped"].get(why, 0) + 1

        for pg in pages:
            key = page_key(pg)
            entry = manifest.get(key)
            if entry is None:
                continue
            if entry.status != "ok":
                skip("状态非 ok")
                continue
            ups = eng.upstream_shas(step, pg)
            if ups is None:
                skip("上游缺失")
                continue
            new_fp, new_ph = _fp(step, eng.book, params, ups, path_in_hash=False)
            if entry.fingerprint == new_fp and entry.params_hash == new_ph:
                row["already"] += 1
                continue
            if (entry.upstream or {}) != ups:
                skip("上游产物变了")
                continue
            sha = eng.store.sha(eng.book.id, sid, key) if eng.store.exists(eng.book.id, sid, key) else None
            if sha is None or (entry.sha256 and entry.sha256 != sha):
                skip("产物文件缺失或与条目记的 sha 不符")
                continue
            if old_params is not None:
                old_fp, _ = _fp(step, eng.book, old_params, ups, path_in_hash=True)
                if entry.fingerprint != old_fp:
                    skip("按老路径重算对不上（不只是路径变了，或 --old-path 给错）")
                    continue
            elif not trust:
                skip("没给 --old-path、也没开 --trust：无法证明只有路径变了")
                continue
            row["migrated"] += 1
            if apply:
                manifest.put(replace(entry, fingerprint=new_fp, params_hash=new_ph,
                                     self_hash=eng.self_hash(step)))
    return report
