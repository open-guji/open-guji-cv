"""构建单字速查释义表 config/gloss/gloss.json。

用途：人工审阅界面的候选按钮旁给一条**一行装得下**的释义 + 读音，帮审阅者
快速判断哪个候选在上下文里通顺。所以构建时就把释义截短（GLOSS_MAX 字），
长释义查原书去——这张表只服务「扫一眼」。

分层合并（先到先得，后层只补缺）：
  1. moe     萌典/重編國語辭典（中文，常用字质量最好）
  2. kangxi  康熙字典点校文本（文言，生僻字覆盖主力）
  3. unihan  kDefinition（英文兜底）
读音单独一列：kMandarin（拼音）。

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


def load_unihan() -> tuple[dict[str, str], dict[str, str]]:
    """Unihan.zip → (kDefinition, kMandarin)。复用 variants 的缓存。"""
    if not UNIHAN_ZIP.exists():
        fetch(UNIHAN_URL, UNIHAN_ZIP)
    kdef, kman = {}, {}
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
    return kdef, kman


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-download", action="store_true")
    args = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)

    layers: list[tuple[str, dict[str, str]]] = []
    # TODO(P0-gloss): moe / kangxi 两层等数据源核实后接入（见
    # glyph_db_expansion_research.md §9），当前先出 unihan 层。
    kdef, kman = load_unihan()
    layers.append(("unihan", kdef))

    gloss: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for src, table in layers:
        added = 0
        for ch, text in table.items():
            if ch not in gloss:
                gloss[ch] = {"d": text, "s": src}
                added += 1
        counts[src] = added
    for ch, py in kman.items():
        gloss.setdefault(ch, {})["p"] = py

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
