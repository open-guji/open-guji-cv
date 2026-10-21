#!/usr/bin/env python3
"""看图交外部模型（M9 D5，GUJI-665）：联系页每格问一遍视觉模型，再和会话（或另一家模型）的结论合并。

S8／S10 的看图原来全靠会话一格一格看（vol06 一册约 10 分钟、180 格）。本脚本把同一批格交给外部视觉模型
各看一遍，两家一致才算数，不一致的一律记「看不清」进请审单第 5 节，不替人拍板：

  ask    读 `reports/<册>/联系页/tiles.json`（zl.py contact 步出的单格图与索引），逐格问模型，
         写 `reports/<册>/看图结论.<模型>.jsonl`（格式同 `feedback/vision.py`，judge＝模型名）。已问过的格跳过，可断点续。
  merge  两份结论逐格合并成 `看图结论.jsonl`：都判对 → ok；都判错且认的字相同 → wrong；
         其余（一家对一家错、认的字不同、任一家看不清）→ unsure，note 里写两家各说什么。只有一家看过的格照抄那一家。
  score  拿一份当参照（比如会话人工核过的），报另一份的一致率、错判对、对判错（选模型、调提示词用）。

模型走智谱开放平台（云端代理已注入凭据，不需要也不要写密钥）；缺省 `glm-4.1v-thinking-flash`。
用法：
  python scripts/zhengli/vision_ask.py ask   --reports $WS/reports/vol06 --book vol06 [--model glm-4v-flash] [--limit 20]
  python scripts/zhengli/vision_ask.py merge --reports $WS/reports/vol06 --a 看图结论.session.jsonl --b 看图结论.glm-4.1v-thinking-flash.jsonl
  python scripts/zhengli/vision_ask.py score --ref 看图结论.session.jsonl --hyp 看图结论.glm-4.1v-thinking-flash.jsonl
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

API = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-4.1v-thinking-flash"

PROMPT = """这是一张古籍刻本（清武英殿本）的竖排局部图，从上到下读。红框里是一个字（左上角数字是序号，不是字）。
机器认为红框里的字是「{char}」。{witness}{ctx}
请只看红框里的字形，判断它是不是「{char}」。异体字、新旧字形算不同的字（如 已／己／巳、曰／日、卷／巻 要分清）。
只输出一行 JSON，不要别的话：{{"v": "ok 或 wrong 或 unsure", "char": "你认出的字（v 为 wrong 时必填）", "note": "一句理由"}}
红框里不是字（框线、墨点、空白）时 v 填 wrong，char 留空。看不清就填 unsure。"""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def prompt_for(e: dict) -> str:
    wit = e.get("witness") or {}
    if isinstance(wit, dict) and wit:
        w = "；".join(f"{k}作「{v}」" for k, v in wit.items() if v)
        wit_s = f"参照本：{w}。" if w else ""
    else:
        wit_s = ""
    ctx_s = f"上下文（【】是这一格）：{e['ctx']}。" if e.get("ctx") else ""
    return PROMPT.format(char=e.get("char") or "□", witness=wit_s, ctx=ctx_s)


def parse_answer(text: str) -> dict | None:
    """模型回答里取最后一个 JSON 对象；思考型模型会先吐 <think>…</think>，跳过。"""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    for m in reversed(list(re.finditer(r"\{[^{}]*\}", text))):
        try:
            d = json.loads(m.group(0))
        except ValueError:
            continue
        if d.get("v") in ("ok", "wrong", "unsure"):
            return d
    return None


def ask_one(img: Path, prompt: str, model: str, timeout: int = 120) -> str:
    b64 = base64.b64encode(img.read_bytes()).decode()
    body = {"model": model, "temperature": 0.1, "max_tokens": 2048 if "thinking" in model else 1024,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": prompt}]}]}
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"]["content"]


def read_jsonl(p: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                out[d["cell"]] = d
    return out


def cmd_ask(a) -> int:
    rep = Path(a.reports)
    entries = json.loads((rep / "联系页" / "tiles.json").read_text(encoding="utf-8"))
    out = rep / f"看图结论.{a.model}.jsonl"
    done = read_jsonl(out)
    todo = [e for e in entries if e.get("tile") and e["id"] not in done][: a.limit or None]
    print(f"{len(entries)} 格，已问 {len(done)}，这次问 {len(todo)}（{a.model}）", flush=True)
    bad = 0
    with out.open("a", encoding="utf-8") as f:
        for i, e in enumerate(todo, 1):
            ans = None
            for attempt in range(3):
                try:
                    ans = parse_answer(ask_one(rep / "联系页" / e["tile"], prompt_for(e), a.model))
                    break
                except Exception as ex:  # noqa: BLE001 —— 网络、限流：退避重试，三次不行记 unsure
                    print(f"  {e['id']}：{type(ex).__name__} {ex}", file=sys.stderr)
                    time.sleep(2 ** (attempt + 1))
            if ans is None:
                bad += 1
                ans = {"v": "unsure", "note": "模型没给出可解析的回答"}
            row = {"cell": e["id"], "v": ans["v"], "shown": e.get("char"), "judge": a.model, "ts": now(),
                   **({"char": ans["char"]} if ans.get("char") and ans["v"] == "wrong" else {}),
                   **({"note": str(ans["note"])[:200]} if ans.get("note") else {})}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if i % 20 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
            time.sleep(a.sleep)
    print(f"→ {out}（答不上 {bad} 格）")
    return 0


def merge(a: dict[str, dict], b: dict[str, dict]) -> dict[str, dict]:
    """两家结论合并：一致才算数，不一致记 unsure（进请审单「看不清」）。"""
    out: dict[str, dict] = {}
    for cell in sorted(set(a) | set(b)):
        x, y = a.get(cell), b.get(cell)
        if x is None or y is None:
            out[cell] = dict(x or y)
            continue
        if x["v"] == y["v"] == "ok":
            v, note = "ok", ""
        elif x["v"] == y["v"] == "wrong" and (x.get("char") or "") == (y.get("char") or ""):
            v, note = "wrong", x.get("note") or y.get("note") or ""
        else:
            v = "unsure"
            note = f"两家不一致：{x['judge']} {x['v']}{('「' + x['char'] + '」') if x.get('char') else ''}；" \
                   f"{y['judge']} {y['v']}{('「' + y['char'] + '」') if y.get('char') else ''}"
        row = {"cell": cell, "v": v, "shown": x.get("shown") or y.get("shown"), "judge": f"{x['judge']}+{y['judge']}",
               "ts": max(x.get("ts", ""), y.get("ts", ""))}
        if v == "wrong" and x.get("char"):
            row["char"] = x["char"]
        if note:
            row["note"] = note
        out[cell] = row
    return out


def score(ref: dict[str, dict], hyp: dict[str, dict]) -> dict:
    both = [c for c in ref if c in hyp]
    agree = sum(1 for c in both if ref[c]["v"] == hyp[c]["v"])
    return {"n": len(both), "agree": agree,
            "missed_wrong": sorted(c for c in both if ref[c]["v"] == "wrong" and hyp[c]["v"] == "ok"),
            "false_wrong": sorted(c for c in both if ref[c]["v"] == "ok" and hyp[c]["v"] == "wrong"),
            "hyp_unsure": sum(1 for c in both if hyp[c]["v"] == "unsure")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("ask")
    p.add_argument("--reports", required=True, help="reports/<册>/ 目录")
    p.add_argument("--book", required=True)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--sleep", type=float, default=0.5)
    p = sp.add_parser("merge")
    p.add_argument("--reports", required=True)
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.add_argument("--out", default="看图结论.jsonl")
    p = sp.add_parser("score")
    p.add_argument("--ref", required=True)
    p.add_argument("--hyp", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "ask":
        return cmd_ask(a)
    if a.cmd == "merge":
        rep = Path(a.reports)
        m = merge(read_jsonl(rep / a.a), read_jsonl(rep / a.b))
        (rep / a.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in m.values()), encoding="utf-8")
        from collections import Counter
        print(f"合并 {len(m)} 格：{dict(Counter(r['v'] for r in m.values()))} → {rep / a.out}")
        return 0
    s = score(read_jsonl(Path(a.ref)), read_jsonl(Path(a.hyp)))
    print(json.dumps(s, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
