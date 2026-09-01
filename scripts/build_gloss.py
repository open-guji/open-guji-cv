"""构建单字速查释义表 config/gloss/gloss.json。

用途：人工审阅界面的候选按钮旁给一条**一行装得下**的释义 + 读音，帮审阅者
快速判断哪个候选在上下文里通顺。所以构建时就把释义截短（GLOSS_MAX 字），
长释义查原书去——这张表只服务「扫一眼」。

分层合并（先到先得，后层只补缺）：
  1. moe     萌典/重編國語辭典修訂本（中文白话，常用字质量最好；
             CC BY-ND 3.0 TW——教育部明示改作限制仅及文字本身、
             不限格式转换，故**首义项原样收录不截短**，截短显示交给界面）
  2. kangxi  康熙字典点校文本《開放康熙》（文言带反切书证，生僻字主力；
             CC BY-SA 3.0，可截短）
  3. wikt    zh 维基词典 kaikki 抽取（中文，扩展区兜底；CC BY-SA 4.0）
  4. unihan  kDefinition（英文最后兜底；Unicode License）
读音：p=拼音（moe 优先，Unihan kMandarin 补缺）、b=注音（moe）、
fq=反切（Unihan kFanqie）。每条记录带 s=来源，授权署名见
config/gloss/README.md——合并文件是汇编，不做整体 relicense。

数据源缓存到 config/gloss/cache/（gitignore），产物确定性输出。
用法：python scripts/build_gloss.py [--skip-download]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "config" / "gloss" / "cache"
OUT = ROOT / "config" / "gloss" / "gloss.json"
REPORT = ROOT / "config" / "gloss" / "report.json"
UNIHAN_ZIP = ROOT / "config" / "variants" / "cache" / "Unihan.zip"

GLOSS_MAX = 64        # 释义截短长度（按字符）
UNIHAN_URL = "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip"


def fetch(url: str, dest: Path) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载 {url}")
    with urllib.request.urlopen(url, timeout=120) as r:
        dest.write_bytes(r.read())


def clip(text: str, limit: int = GLOSS_MAX) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


MOE_URL = ("https://raw.githubusercontent.com/g0v/moedict-data/master/"
           "dict-revised.json")
KANGXI_URL = ("https://raw.githubusercontent.com/7468696e6b/kangxiDictText/"
              "master/kangxizidian-v3f.txt")
WIKT_URL = "https://kaikki.org/dictionary/downloads/zh/zh-extract.jsonl.gz"

_CJK_ORD = 0x3400


def _is_han(w: str) -> bool:
    return len(w) == 1 and ord(w) >= _CJK_ORD


def load_unihan_full() -> tuple[dict, dict, dict]:
    """Unihan.zip → (kDefinition, kMandarin, kFanqie)。复用 variants 的缓存。"""
    if not UNIHAN_ZIP.exists():
        fetch(UNIHAN_URL, UNIHAN_ZIP)
    kdef, kman, kfq = {}, {}, {}
    with zipfile.ZipFile(UNIHAN_ZIP) as z, z.open("Unihan_Readings.txt") as f:
        for raw in f:
            line = raw.decode("utf-8")
            if line.startswith("#") or not line.strip():
                continue
            cp_s, field, val = line.rstrip("\n").split("\t", 2)
            ch = chr(int(cp_s[2:], 16))
            if field == "kDefinition":
                kdef[ch] = clip(val)
            elif field == "kMandarin":
                kman[ch] = val.split()[0]
            elif field == "kFanqie":
                kfq[ch] = val.split()[0] + "切"
    return kdef, kman, kfq


def load_moe() -> tuple[dict[str, str], dict[str, tuple]]:
    """萌典 dict-revised.json → (首义项原文, (拼音, 注音))。

    CC BY-ND：义项文字**原样收录，不截短不改写**（「选取首义项」是汇编
    行为，教育部解释明示不限格式转换）；界面显示时才截。义项带词性时
    以「〔词性〕」前缀原样保留结构信息。
    """
    dest = CACHE / "dict-revised.json"
    fetch(MOE_URL, dest)
    data = json.loads(dest.read_text(encoding="utf-8"))
    defs: dict[str, str] = {}
    reads: dict[str, tuple] = {}
    for e in data:
        w = e.get("title", "")
        if not _is_han(w):
            continue
        hs = e.get("heteronyms") or []
        if not hs:
            continue
        h = hs[0]
        ds = h.get("definitions") or []
        if ds and ds[0].get("def"):
            d0 = ds[0]
            pos = f"〔{d0['type']}〕" if d0.get("type") else ""
            defs[w] = pos + d0["def"]
        reads[w] = (h.get("pinyin", ""), h.get("bopomofo", ""))
    return defs, reads


_KX_LOCATOR = re.compile(r"^《康熙字典》〈[^〉]*〉【[^】]*】頁\d+第\d+")


def load_kangxi() -> dict[str, str]:
    """《開放康熙》点校文本 → 释文（剥掉卷页定位前缀，截短）。CC BY-SA。"""
    dest = CACHE / "kangxizidian-v3f.txt"
    fetch(KANGXI_URL, dest)
    out: dict[str, str] = {}
    for line in dest.read_text(encoding="utf-8").splitlines():
        if "\t" not in line:
            continue
        ch, body = line.split("\t", 1)
        ch = ch.strip()
        if not _is_han(ch):
            continue
        body = _KX_LOCATOR.sub("", body.strip().lstrip("\t"))
        if body:
            out[ch] = clip(body)
    return out


def load_wikt() -> dict[str, str]:
    """zh 维基词典（kaikki 抽取）→ 首两条 gloss 合并截短。CC BY-SA 4.0。"""
    import gzip
    dest = CACHE / "zh-extract.jsonl.gz"
    fetch(WIKT_URL, dest)
    out: dict[str, str] = {}
    with gzip.open(dest, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            w = e.get("word", "")
            if not _is_han(w) or w in out:
                continue
            glosses = [g for s in e.get("senses", [])
                       for g in (s.get("glosses") or [])]
            if glosses:
                out[w] = clip("；".join(glosses[:2]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-download", action="store_true")
    args = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)

    moe_def, moe_read = load_moe()
    kx = load_kangxi()
    wikt = load_wikt()
    kdef, kman, kfq = load_unihan_full()
    layers = [("moe", moe_def), ("kangxi", kx), ("wikt", wikt),
              ("unihan", kdef)]

    gloss: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for src, table in layers:
        added = 0
        for ch, text in table.items():
            if ch not in gloss:
                gloss[ch] = {"d": text, "s": src}
                added += 1
        counts[src] = added
    # 读音：moe 的拼音/注音优先，kMandarin 补缺；反切来自 kFanqie
    for ch, (py, bopo) in moe_read.items():
        rec = gloss.setdefault(ch, {})
        if py:
            rec["p"] = py
        if bopo:
            rec["b"] = bopo
    for ch, py in kman.items():
        gloss.setdefault(ch, {}).setdefault("p", py)
    for ch, fq in kfq.items():
        gloss.setdefault(ch, {})["fq"] = fq

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(gloss, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")) + "\n", encoding="utf-8")
    report = {
        "chars": len(gloss),
        "with_def": sum(1 for v in gloss.values() if "d" in v),
        "with_pinyin": sum(1 for v in gloss.values() if "p" in v),
        "by_source": counts,
        "gloss_max": GLOSS_MAX,
        "bytes": OUT.stat().st_size,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
