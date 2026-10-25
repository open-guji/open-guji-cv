import json, re, sys
mined = json.load(open("mined.json"))
CV = "/home/user/open-guji-cv/config/groups"
DIG = set("一二三四五六七八九十百")
HEAD = {
 "zy": """schema: ctx_l1/1
group: zy
# 于千子干（2026-10-24，A24「强化于千子干等形近判别」）：千干 qg 并入。原 qg 规则里 qg-千-r1（◎古年里…）、qg-干-l1（[無若翻]◎）
# 碰上 子 有冲突（朱子九圖、若子男、無子者），删掉；其余原规则对 vol04–20 已放行格与整理本零冲突，留下。
# mined-a24：vol04–20 已放行格按册分两半（04–12／13–20），两半各 ≥3 格（含数字的词组不收）、合计零冲突的两字词组，再对整理本对位字回测零冲突（research/m7/ctx/mine_l1/）。
rules:
  - {id: qg-千-l2, char: 千, src: corpus-pure, re: '(?:虞稷)◎', note: 整理本奇偶册交叉验证零冲突；n≥3}
  - {id: qg-千-r2, char: 千, src: corpus-pure, re: '◎(?:古之|頃堂|百年)', note: 整理本奇偶册交叉验证零冲突；n≥3}
  - {id: qg-千-m, char: 千, src: corpus-pure, re: '(?:稷◎頃|二◎年)', note: 整理本奇偶册交叉验证零冲突；n≥3}
  - {id: qg-干-l2, char: 干, src: corpus-pure, re: '(?:虞翻)◎', note: 整理本奇偶册交叉验证零冲突；n≥2}
  - {id: qg-干-r1, char: 干, src: corpus-pure, re: '◎[寶支]', note: 整理本奇偶册交叉验证零冲突；n≥2}
  - {id: qg-干-r2, char: 干, src: corpus-pure, re: '◎(?:支之|寶諸)', note: 整理本奇偶册交叉验证零冲突；n≥2}
  - {id: qg-干-m, char: 干, src: corpus-pure, re: '(?:翻◎寶)', note: 整理本奇偶册交叉验证零冲突；n≥2}
""",
}
def head(g, name):
    return f"""schema: ctx_l1/1
group: {g}
# {name}（2026-10-24，A24「强化于千子干等形近判别」）。
# mined-a24：vol04–20 已放行格按册分两半（04–12／13–20），两半各 ≥3 格（含数字的词组不收）、合计零冲突的两字词组，再对整理本对位字回测零冲突（research/m7/ctx/mine_l1/）。
rules:
"""
NAMES = {"yz": "予子", "guan": "官宫宮（宫族的规则给「宫」，族内形由库形最近定）", "hou": "侯候𠉀俟（候族的规则给「候」）", "liang": "兩雨"}
for g, rules in mined.items():
    out = HEAD.get(g) or head(g, NAMES[g])
    seen = set()
    for ch, f, a, b in rules:
        ctx = f.replace("◎", "")

        pat = re.escape(f)
        rid = f"{g}-m-{ch}-{f}"
        if rid in seen: continue
        seen.add(rid)
        out += f"  - {{id: '{rid}', char: {ch}, src: mined-a24, re: '{pat}', note: 已放行 {a}+{b}}}\n"
    open(f"{CV}/{g}/rules.yaml", "w").write(out)
    print(g, len(seen))
