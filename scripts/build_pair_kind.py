# -*- coding: utf-8 -*-
"""生成 config/dicts/variants.pairkind.tsv（字对关系表，见 open_guji_cv/pair_kind.py）。

来源优先级：已有「人定」行（原样保留）> never_group.json（C）> CV4判 > A31初判（下面两张名单，按字义自动定）。
用法：python scripts/build_pair_kind.py   （重生成；人定行不丢）
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "dicts" / "variants.pairkind.tsv"
NEVER = ROOT / "config" / "variants" / "never_group.json"

# A31 初判（2026-11-21）：只有 twedu／汉语大字典单一来源的对，按字义定。每项两个字连写。
V="變𠮓 䜿豎 㕘參 鳧鳬 明眀 㣲微 凟瀆 㝠冥 瓉瓚 攜𢹂 彝𢑴 象𧰼 䘏卹 竄𥨥 祇祗 䆒究 潁頴 埤𡌨 隸𨽻 那郍 派𣲖 撰𢰅 漾𣻌 䝉蒙 厎底 狶豨 隱𨼆 䍐罕 侯𠋫 㓂寇 裦襃 選𨕖 䨇雙 涵𣹢 倚𠋣 麓𪋤 巂雟 彝𢑱 閻𨶒 濂濓 㝷尋 㳫沓 淫滛 棻𦯳 贑贛 慿憑 盡𥁞 弻弼 虗虛 傳𫝊 䴡麗 㓨刺 發𤼵 圖圗 確礭 瑣𤨏 䆳邃 妃𡚱 急𢚩 隸𨽾 㑹會 樹𣗳 裦褒 䜟讖 卑𤰞 䧟陷 䘮喪 㸃點 冡冢 䕫夔 䟦跋 敶陳 傚效 仝全".split()
C="辦辨 戴載 冐冑 摸模 晝畫 摳樞 壬王 朿束 閣閤 觧鮮 庭廷 脯酺 伺司 俸奉 壯牡 壙曠 土士 冐胄 例列 卣鹵 且旦 廬盧 卬卯 簿薄 儀義 昂昴 東柬 宄究 大太 曼蔓 戌戍 刀刁 管菅 丹舟 戊戌 爪瓜 閈閉".split()

# CV4 判（2026-11-23，GM3 复核全唐文异体闸时提出；依据见 config/dicts/variants.tsv 同日注释）。
# 巿(fú，韍)与市(shì)：形近不同义，edges.tsv 只有 zi:UCV／zi:link 字形统一类的边，不是异体，按文意判。
CV4_V = {"䕶護": "教育部異體字字典 護 A03894_012；全唐文 001:47:5:1",
         "蹖踳": "chǔn 义同踳（集韻、魏都賦李善注）；全唐文 013:106:4:20",
         "梁鿄": "鿄 U+9FC4 木部6画 liáng，梁省一点（TC-4A76、JARIB）；GM3 全唐文金标 11-24"}
CV4_C = {"巿市": "巿 fú＝韍、市 shì，形近不同义；全唐文异体闸复核 4 格"}

HEAD = ("# 字对关系表：V 同义异体 / C 纯形近。说明见 open_guji_cv/pair_kind.py；由 scripts/build_pair_kind.py 生成，人定行保留。\n"
        "# 字甲\t字乙\tV|C\t来源\t备注\n")


def _pair(s):
    cs = list(s)
    assert len(cs) == 2, s
    return tuple(sorted(cs))


def main():
    rows = {}
    for s in V:
        rows[_pair(s)] = ("V", "A31初判", "")
    for s in C:
        rows[_pair(s)] = ("C", "A31初判", "")
    for s, note in CV4_V.items():
        rows[_pair(s)] = ("V", "CV4判", note)
    for s, note in CV4_C.items():
        rows[_pair(s)] = ("C", "CV4判", note)
    if NEVER.exists():
        for p in json.loads(NEVER.read_text(encoding="utf-8")).get("pairs", []):
            if len(p) == 2 and p[0] != p[1]:
                rows[_pair("".join(p))] = ("C", "never_group", "")
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) >= 4 and f[3] == "人定":
                rows[tuple(sorted((f[0], f[1])))] = (f[2], "人定", f[4] if len(f) > 4 else "")
    # 与手工语义表（variants.tsv，人工确认）直接矛盾的 C 对不写，留给人定（例：回/迴，never_group 说不是、手工表说是）
    manual = {}
    for line in (ROOT / "config" / "dicts" / "variants.tsv").read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if len(f) >= 2 and not line.startswith("#"):
            manual[f[0]] = f[1]
    for key in [k for k, v in rows.items() if v[0] == "C" and v[1] != "人定"
                and (manual.get(k[0]) == k[1] or manual.get(k[1]) == k[0])]:
        print("与手工表矛盾，未写入:", "".join(key))
        del rows[key]
    lines = [HEAD] + [f"{a}\t{b}\t{k}\t{s}\t{n}\n" for (a, b), (k, s, n) in sorted(rows.items())]
    OUT.write_text("".join(lines), encoding="utf-8")
    nv = sum(1 for v in rows.values() if v[0] == "V")
    print(f"{OUT.name}: V {nv}、C {len(rows) - nv}")


if __name__ == "__main__":
    main()
