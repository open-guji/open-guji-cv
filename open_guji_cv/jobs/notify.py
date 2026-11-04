"""一批单跑完，主动告诉提交人（2026-11-04）。

走 claude-relay 的 send-to-roster（和 ai-team 的 process/send.py 同一条路，只在内部）：按 `submitted_by`
（提交时的 GUJI_JOBS_WHO 名字）找花名册里的人叫醒。需要环境变量 CLAUDE_RELAY_TOKEN，或本机 ~/.config/claude-relay/token；
没有令牌就静默跳过（单子已落库，提交人仍可 `guji_jobs ls／wait`）。
发送失败不影响任何单的结果：认领退回，下次有单收尾再试；名字不在花名册（HTTP 404）就不再试。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import store as S

DEFAULT_URL = "https://relay.open-guji.com/send/send-to-roster"
_disabled = False      # 库里还没有 notified_at 列（没跑 guji_jobs init）：本进程不再试，领单照常
_ICON = {"succeeded": "✓", "failed": "✗", "blocked": "拦", "cancelled": "停"}


def _token() -> str | None:
    t = os.environ.get("CLAUDE_RELAY_TOKEN")
    if t:
        return t
    f = os.path.expanduser("~/.config/claude-relay/token")
    try:
        return open(f, encoding="utf-8").read().strip() or None
    except OSError:
        return None


def message(jobs: list[dict]) -> str | None:
    """通知正文；全是被取消的单就不打扰（返回 None）。"""
    if all(j["status"] == "cancelled" for j in jobs):
        return None
    n_ok = sum(j["status"] == "succeeded" for j in jobs)
    bad = [j for j in jobs if j["status"] in ("failed", "blocked")]
    head = f"【任务库】你提交的 {len(jobs)} 条单已全部结束：{n_ok} 成功" + (f"，{len(bad)} 未成" if bad else "") + "。"
    lines = []
    for j in jobs:
        tail = f"：{(j['error'] or '').splitlines()[0][:120]}" if j["status"] != "succeeded" and j["error"] else ""
        lines.append(f"#{j['id']} {j['book'] or j['kind']} {_ICON.get(j['status'], j['status'])}{tail}")
    more = f"（另有 {len(lines) - 30} 条略）" if len(lines) > 30 else ""
    tip = "详情 `guji_jobs show <单号>`；失败的可 `guji_jobs retry <单号>`。" if bad else "详情 `guji_jobs show <单号>`。"
    return head + "\n" + "\n".join(lines[:30]) + more + "\n" + tip


def _send(to: str, text: str) -> str:
    """返回 'ok' | 'gone'（名字不在花名册，别再试）| 'retry'。"""
    tok = _token()
    if not tok:
        return "gone"
    req = urllib.request.Request(
        os.environ.get("CLAUDE_RELAY_URL", DEFAULT_URL), method="POST",
        data=json.dumps({"to": to, "message": text}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}",
                 "User-Agent": "guji-jobs-notify/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60):
            return "ok"
    except urllib.error.HTTPError as e:
        return "gone" if e.code in (400, 404) else "retry"
    except Exception:       # noqa: BLE001 —— 网络问题不能影响执行方
        return "retry"


def notify_submitters(db, say=print) -> int:
    """执行方每收尾一条单后调用。返回发出的通知数。任何错都吞掉，只打日志。"""
    global _disabled
    if _disabled:
        return 0
    sent = 0
    try:
        due = db(S.notify_due)
    except Exception as e:  # noqa: BLE001
        if "notified_at" in str(e) or type(e).__name__ == "UndefinedColumn":
            _disabled = True
            say("通知：任务库还没有 notified_at 列（需跑一次 guji_jobs init），本进程暂不发通知，领单不受影响")
        else:
            say(f"通知：认领失败 {type(e).__name__}: {str(e)[:120]}")
        return 0
    for g in due:
        ids = [j["id"] for j in g["jobs"]]
        text = message(g["jobs"])
        if text is None:
            continue
        r = _send(g["by"], text)
        if r == "ok":
            sent += 1
            say(f"已通知 {g['by']}：{len(ids)} 条单跑完")
        elif r == "retry":
            say(f"通知 {g['by']} 失败，稍后再试")
            try:
                db(S.notify_undo, ids)
            except Exception:       # noqa: BLE001
                pass
        else:
            say(f"通知 {g['by']} 跳过（花名册里没有这个名字或本机无中转站令牌）")
    return sent
