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
    """阅读序字串（`〓` 保留）＋每个 `〓` 的原码位。按册（半叶顺序）连起来；跨页的窗口对不上就当没找到。

    `alt`：同一份源、双行小注改成「右一字、左一字」交错读的另一条串。本书产物的小注常是交错读序，
    源里是右行读完再读左行，窗口对不上（A24 R01 深挖 E 类，sheldon 11-07 同意）；主串查不到再查它。"""

    def __init__(self, stream: str, codes: dict[int, str], alt: "PuaIndex | None" = None):
        self.stream = stream
        self.codes = codes              # 串内下标 → "daizhige:U+XXXX"（只含有码位的 `〓`）
        self.alt = alt

    @classmethod
    def from_source(cls, files: list[Path]) -> "PuaIndex":
        """从源 jsonl（`corpus/daizhige/NNNN.jsonl`）建；用 `build_halves`，与 dzg_import convert 同一套读法。"""
        halves = build_halves([Path(f) for f in files])
        alt = cls(*_stream(halves, interleave=True))
        return cls(*_stream(halves, interleave=False), alt=alt)


def _stream(halves, interleave: bool) -> tuple[str, dict[int, str]]:
    out, codes = [], {}

    def put(ch, code):
        if ch == UNMAPPED and code:
            codes[len(out)] = code
        out.append(ch)

    for h in halves:
        for col in h.cols:
            for run in col.get("runs", []):
                if run.get("t") == "note":
                    sides = {}
                    for side in ("r", "l"):
                        pos = {(k, i): c for k, i, c in run.get("pua_" + side, [])}
                        sides[side] = [(off + i, ch, pos.get((k, i)))
                                       for k, (off, s) in enumerate(run.get(side, [])) for i, ch in enumerate(s)]
                    if interleave:          # 按格位：同一格位先右后左
                        seq = sorted([(o, 0, ch, c) for o, ch, c in sides["r"]] + [(o, 1, ch, c) for o, ch, c in sides["l"]])
                        for _, _, ch, c in seq:
                            put(ch, c)
                    else:
                        for side in ("r", "l"):
                            for _, ch, c in sides[side]:
                                put(ch, c)
                else:
                    pos = {i: c for i, c in run.get("pua", [])}
                    for i, ch in enumerate(run.get("s", "")):
                        put(ch, pos.get(i))
    return "".join(out), codes


def resolve_pua_code(idx: PuaIndex, left: str, right: str, k: int = K, min_ratio: float = MIN_RATIO) -> str | None:
    """这一格整理本前文 `left`、后文 `right`（只取靠近的各 k 字）→ 源里那个 `〓` 的码位；对不上或不唯一给 None。
    主串对不上时再查小注交错读序的 `idx.alt`。"""
    got = _resolve(idx, left, right, k, min_ratio)
    if got is None and idx.alt is not None:
        got = _resolve(idx.alt, left, right, k, min_ratio)
    return got


def _resolve(idx: PuaIndex, left: str, right: str, k: int, min_ratio: float) -> str | None:
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
