"""用钉住的旧版 cv 跑 `guji …` 命令，读中心库事件时跳过旧版不认的事件种类。

proof_cycle apply 的全册重跑用它：`python engine_run.py <guji 参数…>`，PYTHONPATH 指向旧版 cv 的 worktree。

为什么（2026-10-24，册006）：中心库是全书共用的，dev 上新加的事件种类（如 `inverted_band`，#485）
一推库，旧版引擎读全部事件时 pydantic 就拒收，seed_admit 150 页全部失败。旧引擎本来就不认这些种类、
不会按它们做任何事，跳过后产物与出单时一致。

只改「读」：`EventLog.read` 跳过不认的种类；会改写批次文件的 `compact` 一律拒绝，免得把跳过的事件写丢。
引擎代码一行不动（产物指纹不变）。按 fork 起的多进程会继承这个改动。
"""
from __future__ import annotations

import json
import sys
import typing


def patch_events() -> dict[str, int]:
    from open_guji_cv.feedback import events as ev

    known = set(typing.get_args(ev.Kind))
    skipped: dict[str, int] = {}

    def read(self, batch):
        path = self.batch_path(batch)
        if not path.exists():
            return []
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                kind = json.loads(line).get("kind")
                if kind not in known:
                    skipped[kind] = skipped.get(kind, 0) + 1
                    continue
                out.append(ev.Event.model_validate_json(line))
        return sorted(out, key=lambda e: e.order)

    def no_compact(self, *a, **kw):
        raise RuntimeError("engine_run：旧引擎兼容模式下不许 compact 事件批次")

    ev.EventLog.read = read
    ev.EventLog.compact = no_compact
    return skipped


def main(argv: list[str]) -> int:
    skipped = patch_events()
    from open_guji_cv import cli_v2

    sys.argv = ["guji", *argv]
    try:
        rc = cli_v2.main()
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    if skipped:
        print("ⓘ engine_run：旧引擎跳过不认的事件 " + "、".join(f"{k}×{n}" for k, n in sorted(skipped.items())),
              file=sys.stderr)
    return rc or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
