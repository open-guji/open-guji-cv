#!/usr/bin/env python3
"""GUJI-208ir：把 100 格抽检里「盲读 N 的 17 格」三份读数按格号拼成一张对照表（纯机械，不判对错）。

来源（只读）：
- 序号↔格号：Ezio 判读表 sample100_verdict-Ezio-208ht.tsv（序号、id 列；序号即 sample100.tsv 行序，脚本校验）
- Esme 盲读：scripts-Esme/盲读N17-Esme-208il.tsv（序号＝联系页红字序号）
- Enzo 判定：100格抽检推回与R3-3R3-4去留-Enzo.md（只给了 N 与不定的逐格结论，其余格未逐格记 → 写「缺」）

用法：python3 n17_join.py      输出：scripts-Emi/n17_对照表-Emi.tsv（重跑覆盖）
"""
import csv
import re
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent          # 图片初步数字化/进度
PROJ = PROG.parents[1]                                  # 项目进展
EZIO = PROG / "scripts-Ezio" / "sample100_verdict-Ezio-208ht.tsv"
ESME = PROG / "scripts-Esme" / "盲读N17-Esme-208il.tsv"
ENZO = PROJ / "CV候选字挑选/计划/100格抽检推回与R3-3R3-4去留-Enzo.md"
SAMPLE = PROJ / "CV候选字挑选/计划/B附/抽检100格/sample100.tsv"
OUT = PROG / "scripts-Emi" / "n17_对照表-Emi.tsv"

# Enzo 文档逐格结论（取自 Enzo 文档第一节与第二节原文）：
#   N：#14 #15 #17 #27 #52（框截，归切分）、#92（候选侧，真字脛）
#   不定：岡（#35）、概（#59）、燹（#96）
# 其余 17 格中的 38 46 66 69 77 84 87 89 Enzo 文档未逐格记，写「缺」。
ENZO_VERDICT = {
    14: "N（框截）", 15: "N（框截）", 17: "N（框截）", 27: "N（框截）", 52: "N（框截）",
    92: "N（候选侧）", 35: "不定（岡）", 59: "不定（概）", 96: "不定（燹）",
}
EXPECTED_N = 17  # Enzo 盲读 N 的数


def read_tsv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return [r for r in csv.reader(f, delimiter="\t")]


def n_lines(path):
    with open(path, encoding="utf-8") as f:
        return sum(1 for _ in f)


def main():
    ezio_rows = read_tsv(EZIO)
    ezio_hdr, ezio_body = ezio_rows[0], ezio_rows[1:]
    ezio = {}
    for r in ezio_body:
        ezio[int(r[0])] = {"id": r[1], "真字": r[3], "判": r[4], "首读": r[6]}

    # 序号↔id 校验：与 sample100.tsv 行序一致
    samp = read_tsv(SAMPLE)
    samp_ids = [r[0] for r in samp[1:]]
    for seq, d in ezio.items():
        if seq - 1 >= len(samp_ids) or samp_ids[seq - 1] != d["id"]:
            d["check"] = "序号与 sample100.tsv 行序不一致"

    esme_rows = read_tsv(ESME)
    esme = {}
    for r in esme_rows:
        if not r or r[0].startswith("#") or r[0] == "序号":
            continue
        seq = int(r[0])
        esme[seq] = {"读": r[1], "把握": r[2], "框截半字": r[3]}
    if len(esme) != EXPECTED_N:
        sys.exit(f"停：Esme 盲读只有 {len(esme)} 格，不是 {EXPECTED_N}，请问 Mila，不硬凑")

    lines = [
        f"# 来源：{ESME.relative_to(PROJ)}（{n_lines(ESME)} 行）；{EZIO.relative_to(PROJ)}（{n_lines(EZIO)} 行）",
        f"# 来源：{ENZO.relative_to(PROJ)}（{n_lines(ENZO)} 行）；序号↔格号取 Ezio 判读表，行序已与 {SAMPLE.relative_to(PROJ)} 校验",
        "# 说明：「三者是否同字」只做字面比较（Ezio 真字 vs Esme 读，逐字相等为同）；Enzo 文档不记字，故三者同字一律注「Enzo缺」。Ezio 首读为附加列。",
    ]
    header = ["格号", "联系页序号", "Ezio读", "Esme读", "Esme把握", "Esme是否已见Ezio读数",
              "Enzo verdict", "三者是否同字", "Ezio首读（附加）", "Esme框截半字（附加）"]
    lines.append("\t".join(header))

    pending = []
    for seq in sorted(esme):
        e = esme[seq]
        z = ezio.get(seq)
        if z is None:
            pending.append(seq)
            lines.append("\t".join([f"待映射", str(seq), "缺", e["读"], e["把握"], "缺", "缺", "缺", "缺", e["框截半字"]]))
            continue
        seen = "是" if "已见 Ezio" in e["框截半字"] else "否"
        enzo = ENZO_VERDICT.get(seq, "缺")
        same_ezio_esme = "同" if z["真字"] == e["读"] else "不同"
        same = f"{same_ezio_esme}（Enzo缺）"
        note = z.get("check", "")
        lines.append("\t".join([
            z["id"], str(seq), z["真字"], e["读"], e["把握"], seen,
            enzo, same, z["首读"], e["框截半字"] + (f" [{note}]" if note else ""),
        ]))

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写 {OUT}：{len(esme)} 格；待映射 {len(pending)} 格 {pending}")


if __name__ == "__main__":
    main()
