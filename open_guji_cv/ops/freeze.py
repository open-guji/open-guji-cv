# -*- coding: utf-8 -*-
"""冻结基线（GUJI-601）：到 0.1.0／1.0.0 的册，`close-check` 1a 改比快照，不比现行指纹。

规矩见 ai-team `domain/CV/规范/冻结基线与重跑分级.md`（用户 2026-10-18 定）：

| 原因 | 冻结册 |
|---|---|
| 代码变（cv 升版） | 不报警，只计数 |
| 字形库内容／人裁变 | 不报警，计「基线后新人裁 N 条待落地」 |
| 册配置变 | 报警 |
| 产物 sha 与快照不符 | 报警 |

册 yaml 写法：

    freeze:
      at: "0.1.0"                    # 文本版本
      cv_version: "0.2.0"            # 生成快照的 cv 版本（登记用）
      snapshot: snap/96mid1ogzk/vol01/20261017T1243   # 工作区 git 里的快照分支
      # 或 manifest: snapshots/vol01-r1/manifest.json （相对工作区）
      # 或 pack: freeze-1.0.0-20261023T1800   （`guji freeze register` 写；R2 冻结包旁的 baseline.json）

只读，不改产物。本模块在 `ops/`，不在任何 Step 的 `code_deps`。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..snap.manifest import sha256_file


class FreezeError(RuntimeError):
    """冻结配置写错了，或快照 manifest 读不到。"""


def is_frozen(book) -> bool:
    fz = getattr(book, "freeze", None) or {}
    return bool(fz.get("snapshot") or fz.get("manifest") or fz.get("pack"))


def load_baseline(book, ws: Path) -> dict:
    """读冻结基线的快照 manifest（guji-snap/1）。"""
    fz = getattr(book, "freeze", None) or {}
    if fz.get("pack"):                      # `guji freeze register` 写的：R2 冻结包旁的 baseline.json（GUJI-694）
        from .freeze_register import load_pack_baseline
        try:
            return load_pack_baseline(fz["pack"], book.id, ws)
        except Exception as e:  # noqa: BLE001 —— 取不到就说清楚，不让 close-check 崩
            raise FreezeError(f"取不到冻结包 {fz['pack']} 的 baseline.json：{e}") from e
    if fz.get("manifest"):
        p = Path(fz["manifest"])
        p = p if p.is_absolute() else Path(ws) / p
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise FreezeError(f"读不到冻结基线 manifest {p}：{e}") from e
    ref = fz.get("snapshot")
    if not ref:
        raise FreezeError("册配置 freeze: 没写 pack、snapshot 或 manifest")
    for r in (ref, f"origin/{ref}"):
        out = subprocess.run(["git", "-C", str(ws), "show", f"{r}:manifest.json"],
                             capture_output=True, text=True, encoding="utf-8")
        if out.returncode == 0:
            try:
                return json.loads(out.stdout)
            except ValueError as e:
                raise FreezeError(f"快照 {r} 的 manifest.json 不是 JSON：{e}") from e
    raise FreezeError(f"工作区 git 里找不到快照分支 {ref}（先 `git fetch origin {ref}`）")


def compare_products(baseline: dict, products_root: Path) -> dict:
    """快照里每个产物文件与现有产物逐个比 sha256。返回 {same, changed[], missing[]}。"""
    same, changed, missing = 0, [], []
    for rel, meta in sorted((baseline.get("files") or {}).items()):
        # 各步的 `_manifest.jsonl` 不比：快照里那份是打包时去重、按页过滤后重写的，
        # 线上那份只追加、导入也是追加，跑过就有历史行，sha 永远对不上。
        # 产物本身逐个比 sha 已经够了；manifest 的新旧由下面的 stale 原因另算。
        if rel.rsplit("/", 1)[-1] == "_manifest.jsonl":
            continue
        # 快照里的路径是 `products/<册>/<步>/<文件>`，落到产物根下去掉 `products/`
        sub = rel[len("products/"):] if rel.startswith("products/") else rel
        f = Path(products_root) / sub
        if not f.is_file():
            missing.append(rel)
        elif sha256_file(f) != meta.get("sha256"):
            changed.append(rel)
        else:
            same += 1
    return {"same": same, "changed": changed, "missing": missing}


def human_events_since(book_id: str, since: str, feedback_root: Path | None) -> int:
    """基线之后新增的、算人裁的事件条数（`counts_as_human`）。`since` 是 ISO UTC 时戳。"""
    from ..feedback.events import counts_as_human
    root = Path(feedback_root) if feedback_root else None
    ev_dir = root / "events" if root else None
    if not ev_dir or not ev_dir.is_dir():
        return 0
    n = 0
    from ..core.event_files import iter_event_dicts
    for d in iter_event_dicts(ev_dir):
        if (d.get("target") or {}).get("book") != book_id:
            continue
        if str(d.get("ts") or "") <= since:
            continue
        e = type("E", (), {"kind": d.get("kind"), "payload": d.get("payload") or {}})()
        if counts_as_human(e):
            n += 1
    return n


def fresh_frozen(eng, pages, ws: Path, feedback_root: Path | None = None) -> dict:
    """冻结册的 1a。返回 close_check 的一项（dict）。"""
    from .close_check import FAIL, PASS, _item, _shared_only
    book = eng.book
    fz = book.freeze
    base = load_baseline(book, ws)
    cmp = compare_products(base, eng.store.root)
    st = eng.status(pages=pages)
    # 规矩表：册配置／参数变 → 报警；代码、字形库、人裁变 → 不报警。
    # 旧条目没记册配置原值时 engine 只能说「代码或册配置变了」，分不清，单列请人核，不判失败。
    # 只因共享输入（语料、证人、格位表、字组……，`close_check.SHARED_PARAMS`）被别处更新：单列一句，不报警（复盘 I）。
    cfg_changed, unclear, shared, not_counted = {}, {}, {}, 0
    for sid, d in st["steps"].items():
        for reason, n in (d.get("stale_reasons") or {}).items():
            fields = _shared_only(reason)
            if fields is not None:
                for f in fields:
                    shared[f] = shared.get(f, 0) + n
            elif reason.startswith("册配置") or reason.startswith("参数变了"):
                cfg_changed[sid] = cfg_changed.get(sid, 0) + n
            elif reason.startswith("代码或册配置变了"):
                unclear[sid] = unclear.get(sid, 0) + n
            else:
                not_counted += n
    n_new = human_events_since(book.id, str(base.get("created") or ""), feedback_root)
    label = (f"冻结基线 {fz.get('pack') or fz.get('snapshot') or fz.get('manifest')}"
             f"（文本 {fz.get('at', '?')}，cv {fz.get('cv_version') or (base.get('cv') or {}).get('version') or '?'}）")
    bad = bool(cmp["changed"] or cmp["missing"] or cfg_changed)
    parts = [label,
             f"产物与快照一致 {cmp['same']} 个文件",
             *([f"被改 {len(cmp['changed'])} 个"] if cmp["changed"] else []),
             *([f"缺 {len(cmp['missing'])} 个"] if cmp["missing"] else []),
             *([f"册配置或参数被改：{', '.join(f'{k} {v} 页' for k, v in cfg_changed.items())}"]
               if cfg_changed else []),
             *([f"分不清是代码还是册配置变（旧条目没记原值，请人核）："
                f"{', '.join(f'{k} {v} 页' for k, v in unclear.items())}"] if unclear else []),
             *([f"共享输入被别处更新（不算失败，冻结记录里记一笔）：{'、'.join(f'{k}×{v}' for k, v in sorted(shared.items()))}"]
               if shared else []),
             f"基线后新人裁 {n_new} 条待落地",
             f"代码／字形库变带来的过期 {not_counted} 页不计"]
    data = {"frozen": True, "changed": cmp["changed"][:50], "missing": cmp["missing"][:50],
            "config_changed": cfg_changed or None, "unclear_code_or_config": unclear or None,
            "shared_inputs": shared or None,
            "new_human_events": n_new,
            "stale_not_counted": not_counted}
    return _item("1a", "产物新鲜（冻结基线）", FAIL if bad else PASS, "；".join(parts), data)
