# -*- coding: utf-8 -*-
"""出大模型判文意的批次文件（盲判：只给前后各 30 字，不给整理本、字形、机器判断、真值）。

用法：llm_batches.py <out_dir> <tag> <seed> <n_per_batch> [--ids ids.txt | --strong]
输出：<out_dir>/<tag>_NN.json（交给判官）与 <out_dir>/<tag>_key.json（id→批号，不给判官）。
muse 版：同一份输入、同一提示词（PROMPT）、输出 schema 同 SCHEMA，可原样交 muse exec（见 HANDOFF）。
"""
import json, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common

PROMPT = """你在判《四庫全書總目》刻本里一个字位该是「己」「已」「巳」中的哪一个。
这三个字刻本里刻得几乎一样，**只能按上下文文意判**，不要管字形。判法：
- 干支（年份/日期里「X己丑」「癸巳」）：天干用「己」，地支用「巳」；
- 虚词「已」：而已、已經、已而、已久、已有、業已、不得已、已矣；表示「已经做了某事」；
- 「己」指自己：自己、克己、以己意、參以己見、斷以己意、遷就己說、爲己。
每条给出 目标位前 30 字（left）与后 30 字（right）（□ 表示未知字，读序已连成一串，可能夹有小注字）。
只输出 JSON 数组，每条 {"id":…, "char":"己|已|巳", "conf":"high|mid|low", "why":"≤20字，写出依据的词组"}。
拿不准就选最可能的并把 conf 标 low；不要查文件、不要联网。"""
SCHEMA = {"type": "array", "items": {"type": "object", "required": ["id", "char", "conf"],
          "properties": {"id": {"type": "string"}, "char": {"enum": ["己", "已", "巳"]},
                         "conf": {"enum": ["high", "mid", "low"]}, "why": {"type": "string"}}}}

if __name__ == "__main__":
    out, tag, seed, n = Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4])
    items = common.load_items()
    if "--ids" in sys.argv:
        ids = set(Path(sys.argv[sys.argv.index("--ids") + 1]).read_text().split())
        rows = [x for x in items if x["id"] in ids]
    else:
        rows = common.strong(items)
    rows.sort(key=lambda x: x["id"])
    random.Random(seed).shuffle(rows)
    out.mkdir(parents=True, exist_ok=True)
    key = {}
    nb = (len(rows) + n - 1) // n
    for b in range(nb):
        chunk = rows[b::nb]
        key.update({x["id"]: b for x in chunk})
        (out / f"{tag}_{b:02d}.json").write_text(json.dumps(
            [{"id": x["id"].replace(":", "_"), "left": common.ctx(x)[0], "right": common.ctx(x)[1]} for x in chunk],
            ensure_ascii=False, indent=0), encoding="utf-8")
    (out / f"{tag}_key.json").write_text(json.dumps(key), encoding="utf-8")
    (out / "PROMPT.txt").write_text(PROMPT, encoding="utf-8")
    print(len(rows), "格", nb, "批")
