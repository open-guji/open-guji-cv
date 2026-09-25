"""每步一份 `_manifest.jsonl`：一行一个单位键的最新执行记录，追加写、后写覆盖。

字段：key, fingerprint, sha256（数值产物文件）, params_hash, upstream{kind: sha},
code_rev（git HEAD）, ts, elapsed, status（ok | failed | skipped）, error
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ManifestEntry:
    key: str
    fingerprint: str
    sha256: str | None = None
    params_hash: str | None = None
    upstream: dict[str, str] = field(default_factory=dict)
    code_rev: str | None = None
    ts: float = field(default_factory=time.time)
    elapsed: float = 0.0
    status: str = "ok"
    error: str | None = None
    self_hash: str | None = None
    """本步自身的指纹（版本 + 参数 + 代码 + 册配置，**不含上游**；2026-09-20，
    `engine.self_hash`）。格级复用（`core/reuse.py`）拿它判「这一步自己没变、只是
    上游变了」——只有这种情况才允许把旧记录搬过来。老条目没有这个字段 → 不复用。"""
    invalidated: str | None = None
    """显式失效理由（2026-09-13）。指纹只认「代码 / 参数 / 上游产物」三样，人裁
    不在里面——一条切线裁决落定后该页 Step3 该重跑，却没有任何指纹会变。这里给
    消费者一个入口：置了理由，引擎就把这一页当 stale（`engine.page_status`），
    重跑写回新条目时自然清空。只标不自动跑，与指纹过期同一纪律。"""
    recheck: list[str] | None = None
    """格级失效（2026-09-25）：与 `invalidated` 同时出现时，只有这些格 id 要重算，
    其余格走格级复用（`core/reuse.py`）照搬旧记录。None = 整页失效（老语义）。
    `guji recheck` 写它；整页失效与格级失效相遇时整页优先（见 `Manifest.invalidate`）。"""
    soft: dict[str, str] | None = None
    """跑这一页时软参数的值（`StepSpec.soft_params`，2026-09-25）。不进指纹，
    `status` 拿它与现值比，报「漂移」而不是「过期」。"""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self._entries: dict[str, ManifestEntry] | None = None

    def _load(self) -> dict[str, ManifestEntry]:
        if self._entries is None:
            self._entries = {}
            if self.path.exists():
                with open(self.path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        d = json.loads(line)
                        d.setdefault("upstream", {})
                        self._entries[d["key"]] = ManifestEntry(**{
                            k: v for k, v in d.items() if k in ManifestEntry.__dataclass_fields__})
        return self._entries

    def get(self, key: str) -> ManifestEntry | None:
        return self._load().get(key)

    def all(self) -> dict[str, ManifestEntry]:
        return dict(self._load())

    def put(self, entry: ManifestEntry) -> None:
        self._load()[entry.key] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(entry.to_json() + "\n")

    def invalidate(self, key: str, reason: str, cells: list[str] | None = None) -> bool:
        """把 `key` 的最新条目标成显式失效（追加一条带 `invalidated` 的副本）。
        没有条目（从没跑过）返回 False——没产物就没什么可失效的。

        `cells` 给了 = 只失效这些格（`recheck`），重跑时其余格复用；已有格级失效时并集。
        整页失效（`cells=None`）压过格级失效；已经整页失效了再来格级，不降级。"""
        cur = self.get(key)
        if cur is None:
            return False
        if cur.invalidated:
            if cur.recheck is None:
                return True                       # 已整页失效
            if cells is not None and set(cells) <= set(cur.recheck):
                return True
        prev = set(cur.recheck or []) if cur.invalidated else set()
        recheck = None if cells is None else sorted(set(cells) | prev)
        why = reason if not cur.invalidated else f"{cur.invalidated}; {reason}"
        new = ManifestEntry(**{**asdict(cur), "invalidated": why, "recheck": recheck,
                               "ts": time.time()})
        self.put(new)
        return True

    def compact(self) -> None:
        """重写文件，只留每个 key 的最后一条。"""
        entries = self._load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for e in entries.values():
                f.write(e.to_json() + "\n")
        tmp.replace(self.path)
