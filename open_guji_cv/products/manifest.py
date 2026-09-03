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

    def compact(self) -> None:
        """重写文件，只留每个 key 的最后一条。"""
        entries = self._load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for e in entries.values():
                f.write(e.to_json() + "\n")
        tmp.replace(self.path)
