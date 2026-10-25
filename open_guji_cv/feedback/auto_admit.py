"""`guji db sync` 顺带把还没落库的人裁落进字形库（2026-10-24，A23）。

## 为什么

人裁要经消费者 `glyphdb_admit`（确认 → 字形库）、`glyph_audit`（体检撤库／改字）才进字形库。控制台裁完当场
`route_and_consume`，可别的路径写的事件——批量补标、网站审校收割、各线程用脚本写的事件文件——推进中心库就停在那里，
没人跑消费者。2026-10-24 盘点：10-22 起 967 条人裁确认一直没进库，g1 快照里一条都没有（`doc/受控重跑.md` 第六节）。

## 做什么

`sync` 拉完、合完之后，对**这两个消费者**未记账的事件跑一遍（不跑 `gold_add`、`crop_exclude` 等：那些改金标、
排除名单，牵动各册产物，仍由控制台和各自的命令管），库变了就再推一次。逐条记账：

- 消费者报错的那条（字块取不到、乱码字形、库里没有要改的条目……）**不记账**，留着下次、或有产物的机器再落；
- 绑定判不该采信、印章遮挡、`no_glyph_lib` 的照消费者的口径算处理过，记账；
- 本机没有那一页的产物与字块缓存、库里也没有这格时就是「取不到字块」，留着——落库最好在有产物的机器上跑。

`GUJI_AUTO_ADMIT=0` 关掉（排查用）；`--dry-run` 只数待落库的条数。
"""

from __future__ import annotations

import os

from .events import EventLog, replay_key

CONSUMER_IDS = ("glyphdb_admit", "glyph_audit")
NOTE = "db sync 自动落库"


def enabled() -> bool:
    return os.environ.get("GUJI_AUTO_ADMIT", "1") != "0"


def _event_key(consumer: str, e) -> str:
    if consumer == "glyph_audit":
        return (e.payload or {}).get("instance_id") or e.target.key
    return e.target.key


def _failed_ids(consumer: str, pairs, errors: list[str]) -> set[str]:
    """消费者的错误行（`<格键或事件 id>: …`）对回事件；同一格键的几条一起留着（宁可多留，不错记账）。"""
    bad: set[str] = set()
    for msg in errors:
        head = msg.split(": ", 1)[0]
        for e, _ in pairs:
            if head in (e.id, _event_key(consumer, e), e.target.key):
                bad.add(e.id)
    return bad


def pending_pairs(log: EventLog, table) -> dict[str, list]:
    """两个字形库消费者各自未记账的 (事件, 去向)，按时间序。"""
    evs = sorted(log.iter_all(), key=replay_key)
    out: dict[str, list] = {}
    for consumer in CONSUMER_IDS:
        done = log.consumed_ids(consumer)
        out[consumer] = [(e, d) for e in evs if e.id not in done
                         for d in table.destinations(e) if d.consumer == consumer]
    return out


def admit_pending(log: EventLog | None = None, *, dry_run: bool = False, consumers=None, **consumer_kw) -> dict:
    """跑两个字形库消费者、逐条记账。返回 `{消费者: {events, added, updated, …, marked, left: [事件 id]}}`。

    `consumers` 只给测试替换消费者用；`consumer_kw` 透传（如 `db_path`）。"""
    from .consumers import CONSUMERS
    from .lock import feedback_write_lock
    from .routes import RouteTable
    log = log or EventLog()
    fns = consumers or CONSUMERS
    out: dict = {}
    with feedback_write_lock(log.root):
        table = RouteTable.load(log.root / "routes.yaml")
        for consumer, pairs in pending_pairs(log, table).items():
            if not pairs:
                continue
            if dry_run:
                out[consumer] = {"events": len({e.id for e, _ in pairs}), "dry_run": True}
                continue
            res = fns[consumer](pairs, **consumer_kw)
            bad = _failed_ids(consumer, pairs, res.errors)
            seen: dict = {}
            for e, _ in pairs:
                if e.id not in bad:
                    seen.setdefault(e.id, e)
            n = log.mark_consumed(consumer, seen.values(), note=NOTE) if seen else 0
            out[consumer] = {**res.to_dict(), "marked": n, "left": sorted(bad)}
    return out


def touched(res: dict) -> bool:
    """这一轮记了账（库或消费记账变了）：要再推一次。"""
    return any(isinstance(r, dict) and r.get("marked") for r in res.values())
