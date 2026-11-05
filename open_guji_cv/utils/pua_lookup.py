"""待收字：整理本这一位的私用码，出单时按前后文窗口回查源文件（A24 2026-11-05，A31 同意）。

背景：`utils/daizhige.fix_pua` 把映不上的僻字码写成 `〓`，下游（align_ref 等）只传字、不传位置，格上看不到码位。
不动 Step、不改指纹：出单时拿这格整理本前后各几字，回查殆知阁源文件的阅读序字串，找到那个 `〓` 的原码位
（`daizhige:U+XXXX`，`daizhige.pua_codes` 同一写法）。窗口对得上、且候选的码位唯一才认，否则给 None
（调用方仍记 `ref_lacuna`，不会误判成待收字）。2026-10-26 实测 3,946 格里 96% 窗口唯一。
"""
from __future__ import annotations

from pathlib import Path

from .daizhige import UNMAPPED, build_halves

#: 窗口各取几字、至少要对上几成
K, MIN_RATIO, MIN_CHARS = 6, 0.75, 6


class PuaIndex:
    """阅读序字串（`〓` 保留）＋每个 `〓` 的原码位。按册（半叶顺序）连起来；跨页的窗口对不上就当没找到。"""

    def __init__(self, stream: str, codes: dict[int, str]):
        self.stream = stream
        self.codes = codes              # 串内下标 → "daizhige:U+XXXX"（只含有码位的 `〓`）

    @classmethod
    def from_source(cls, files: list[Path]) -> "PuaIndex":
        """从源 jsonl（`corpus/daizhige/NNNN.jsonl`）建；用 `build_halves`，与 dzg_import convert 同一套读法。"""
        out, codes = [], {}
        for h in build_halves([Path(f) for f in files]):
            for col in h.cols:
                for run in col.get("runs", []):
                    if run.get("t") == "note":
                        for side in ("r", "l"):
                            pos = {(k, i): c for k, i, c in run.get("pua_" + side, [])}
                            for k, (_, s) in enumerate(run.get(side, [])):
                                for i, ch in enumerate(s):
                                    if ch == UNMAPPED and (k, i) in pos:
                                        codes[len(out)] = pos[(k, i)]
                                    out.append(ch)
                    else:
                        pos = {i: c for i, c in run.get("pua", [])}
                        for i, ch in enumerate(run.get("s", "")):
                            if ch == UNMAPPED and i in pos:
                                codes[len(out)] = pos[i]
                            out.append(ch)
        return cls("".join(out), codes)


def resolve_pua_code(idx: PuaIndex, left: str, right: str, k: int = K, min_ratio: float = MIN_RATIO) -> str | None:
    """这一格整理本前文 `left`、后文 `right`（只取靠近的各 k 字）→ 源里那个 `〓` 的码位；对不上或不唯一给 None。"""
    L, R = (left or "")[-k:], (right or "")[:k]
    total = len(L) + len(R)
    if total < MIN_CHARS or not idx.codes:
        return None
    s = idx.stream
    best, hits = 0, set()
    for p, code in idx.codes.items():
        sc = sum(1 for a, b in zip(reversed(L), reversed(s[max(0, p - len(L)):p])) if a == b)
        sc += sum(1 for a, b in zip(R, s[p + 1:p + 1 + len(R)]) if a == b)
        if sc > best:
            best, hits = sc, {code}
        elif sc == best:
            hits.add(code)
    if best < min_ratio * total or len(hits) != 1:
        return None
    return next(iter(hits))
