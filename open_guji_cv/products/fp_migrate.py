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


#: 指纹是「整体哈希」、没有 path_params 也没有老公式可回放的步：只能按新公式重写（`--trust`）。
#: `rare_candidates`（K#238c）：`model_fingerprint` 进 `params_hash`，其中真刻例 store 路径
#: 改成相对工作区根后，所有已有产物的指纹变一次。
WHOLE_HASH_STEPS = frozenset({"rare_candidates"})


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


def _producers_of(kind: str) -> list[str]:
    """全部注册步里产出 `kind` 的步 id（含别的管线的，归因时要看得全）。"""
    return [sid for sid, st in STEPS.items() if kind in st.spec.produces]


def _attribute(eng: Engine, kind: str, page: int, sha: str) -> list[str]:
    """这个 sha 是哪个（哪些）步这一页现在的产物？——用来回答「记录里的 cells 到底是谁的」。
    只认磁盘上现有产物，找不到返回空（记录来自现在已不在的产物）。"""
    key = page_key(page)
    hit = []
    for sid in _producers_of(kind):
        try:
            if eng.store.exists(eng.book.id, sid, key) and eng.store.sha(eng.book.id, sid, key) == sha:
                hit.append(sid)
        except Exception:
            continue
    return hit


def diff_upstream(eng: Engine, step, page: int, recorded: dict[str, str],
                  now: dict[str, str]) -> list[dict]:
    """记录的 upstream 与现算 upstream 的逐键差异（只列有差的键）。
    每条：kind / recorded / now / producer_now（本管线里现在认哪个步产它）/
    recorded_from（记录的 sha 现在对得上哪个步的产物）/ how（sha 不同｜仅记录有｜仅现算有）。"""
    out = []
    for kind in sorted(set(recorded) | set(now)):
        a, b = recorded.get(kind), now.get(kind)
        if a == b:
            continue
        try:
            prod = eng.pipeline.producer_of(kind).spec.id if kind != "raw_page" else "原图"
        except Exception:
            prod = "?"
        out.append({
            "kind": kind, "recorded": a, "now": b, "producer_now": prod,
            "recorded_from": _attribute(eng, kind, page, a) if a and kind != "raw_page" else [],
            "how": "仅记录有" if b is None else "仅现算有" if a is None else "sha 不同",
        })
    return out


def _short(sha: str | None) -> str:
    return "—" if not sha else sha[:8]


def format_diff(d: dict) -> str:
    src = ("（记录的 sha 现对应 " + "/".join(d["recorded_from"]) + " 的产物）") if d["recorded_from"] else ""
    return (f"{d['kind']}: 记录 {_short(d['recorded'])} ≠ 现算 {_short(d['now'])} "
            f"[{d['how']}；现由 {d['producer_now']} 产出]{src}")


def rare_fingerprint_parts(eng: Engine) -> list[dict]:
    """`rare_candidates` 指纹里所有「可能随机器变」的量，逐项列出（`--explain` 用）。
    该步没有 `path_params`，所以 fp-migrate 帮不上它——但它的 `model_fingerprint`
    （params_hash 的一个字段）里混着路径和外部文件状态，换机器就对不上。"""
    from ..clustering import cnn_candidates as cc
    from ..clustering.font_candidates import font_set_fingerprint
    step = STEPS.get("rare_candidates")
    if step is None:
        return []
    p = eng.ctx.params_for(step)
    parts = [{"name": "checkpoint(内容)", "value": cc.fingerprint(), "machine": False},
             {"name": "字体集(内容)", "value": font_set_fingerprint(), "machine": False},
             {"name": "外部模板集 stamp", "value": cc.template_set_fingerprint(), "machine": False,
              "note": "EMB_EXTRA_SPECS 自 2026-09-08 起为空元组，故恒为空输入的 sha1"
                      "（da39a3ee…前 16 位）——是常量、不是 bug；将来填了 spec 才随机器数据变"}]
    en, specs = cc.book_real_proto(getattr(eng.book, "font", None))
    parts.append({"name": "real_proto 开关", "value": str(en), "machine": False})
    if en:
        for sp in specs:
            parts.append({"name": "real_proto store 标签（进哈希）",
                          "value": cc._portable_store_label(sp), "machine": False,
                          "note": "K#238c 起相对工作区根，同内容跨机器一致"})
        parts.append({"name": "real_proto 指纹", "value": cc.real_proto_fingerprint(specs, enabled=en),
                      "machine": True})
    if p.struct_probe:
        parts.append({"name": "struct_probe 路径（params 里原文，进哈希）", "value": p.struct_probe,
                      "machine": True, "note": "路径字段未登记 path_params"})
    parts.append({"name": "model_fingerprint(整体，进 params_hash)", "value": p.model_fingerprint,
                  "machine": False})
    return parts


def migrate_book(eng: Engine, pages: list[int], *, old_paths: dict[str, dict[str, str]] | None = None,
                 trust: bool = False, apply: bool = False,
                 steps: list[str] | None = None, explain: bool = False) -> dict:
    """逐步逐页迁移。返回 {step: {"migrated": n, "already": n, "skipped": {原因: n}}}。
    `apply=False` 是干跑：算得一模一样，只是不写 manifest。"""
    old_paths = old_paths or {}
    report: dict[str, dict] = {}
    for name in steps or ():
        if name not in eng.pipeline.steps:
            report[name] = {"na": "不在本管线里"}
    for sid in eng.pipeline.steps:
        step = STEPS[sid]
        if steps and sid not in steps:
            continue
        whole = sid in WHOLE_HASH_STEPS
        if not step.spec.path_params and not whole:
            if steps:      # 点了名的步不许静默
                report[sid] = {"na": "无路径参数，不适用"}
            continue
        params = eng.ctx.params_for(step)
        if whole and sid in old_paths:
            report[sid] = {"na": f"{sid} 是整体哈希、没有老路径公式，只能 --trust，不接 --old-path"}
            continue
        old_params = _old_params(step, params, old_paths[sid]) if sid in old_paths else None
        row = {"migrated": 0, "already": 0, "skipped": {}}
        if explain:
            row["detail"] = {}
        report[sid] = row
        manifest = eng.store.manifest(eng.book.id, sid)

        def skip(why: str, pg: int, diffs: list[dict] | None = None) -> None:
            row["skipped"][why] = row["skipped"].get(why, 0) + 1
            if explain:
                row["detail"][pg] = {"why": why, "diffs": diffs or []}

        for pg in pages:
            key = page_key(pg)
            entry = manifest.get(key)
            if entry is None:
                continue
            if entry.status != "ok":
                skip("状态非 ok", pg)
                continue
            ups = eng.upstream_shas(step, pg)
            if ups is None:
                skip("上游缺失", pg, [{"kind": k, "recorded": (entry.upstream or {}).get(k), "now": None,
                                       "producer_now": eng.pipeline.producer_of(k).spec.id
                                       if k != "raw_page" else "原图", "recorded_from": [],
                                       "how": "现算缺失"} for k in eng.missing_upstream(step, pg)]
                     if explain else None)
                continue
            new_fp, new_ph = _fp(step, eng.book, params, ups, path_in_hash=False)
            if entry.fingerprint == new_fp and entry.params_hash == new_ph:
                row["already"] += 1
                continue
            if (entry.upstream or {}) != ups:
                skip("上游产物变了", pg,
                     diff_upstream(eng, step, pg, entry.upstream or {}, ups) if explain else None)
                continue
            sha = eng.store.sha(eng.book.id, sid, key) if eng.store.exists(eng.book.id, sid, key) else None
            if sha is None or (entry.sha256 and entry.sha256 != sha):
                skip("产物文件缺失或与条目记的 sha 不符", pg)
                continue
            if whole:
                # 整体哈希：没有「老公式」可重算来证明只变了路径，只剩 trust（上游 sha 与
                # 产物文件 sha 已在上面查过）。不 trust 就一律不动。
                if not trust:
                    skip("整体哈希步只能 --trust 迁移（上游 sha 与产物文件 sha 已核）", pg)
                    continue
            elif old_params is not None:
                old_fp, _ = _fp(step, eng.book, old_params, ups, path_in_hash=True)
                if entry.fingerprint != old_fp:
                    skip("按老路径重算对不上（不只是路径变了，或 --old-path 给错）", pg)
                    continue
            elif not trust:
                skip("没给 --old-path、也没开 --trust：无法证明只有路径变了", pg)
                continue
            row["migrated"] += 1
            if apply:
                manifest.put(replace(entry, fingerprint=new_fp, params_hash=new_ph,
                                     self_hash=eng.self_hash(step)))
    return report
