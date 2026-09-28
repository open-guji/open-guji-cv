#!/usr/bin/env python3
"""拉取 zdic.net 字头页面，供 87 对异体试金石核查用。
zdic 条款页 (https://www.zdic.net/terms/) 声明「归公宣告：汉典奉行 CC0 1.0 公约，
将本站字词、古籍、诗词、书法诸作，悉数贡献天下，放弃著作专权及邻接法益，任人取用」，
robots.txt 只 Disallow /api/ /e/ /zadmin/ /member/，字头页 /hans/<char> 不在禁止之列。
本脚本按 1.5s 间隔顺序请求，不并发，避免给服务器加压。
"""
import json, re, sys, time, urllib.parse, urllib.request, os

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "zdic_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def fetch(char, retries=3):
    cp = f"{ord(char):04X}"
    path = os.path.join(CACHE_DIR, f"{cp}.html")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    url = "https://www.zdic.net/hans/" + urllib.parse.quote(char)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", "ignore")
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            return html
        except Exception as e:
            sys.stderr.write(f"[{cp} {char}] attempt {attempt+1} failed: {e}\n")
            time.sleep(3)
    return None

def strip_tags(html):
    html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    html = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    text = re.sub(r"<[^>]+>", "\n", html)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()

def extract_fields(html, char):
    out = {"char": char, "basic": None, "kangxi": None, "shuowen": None,
           "pinyin": None, "variants_widget": []}
    if not html:
        out["error"] = "fetch_failed"
        return out
    text = strip_tags(html)
    # 拼音（页面顶部 "拼音\ncuō" 这种结构，取“拼音”标签后紧跟的一行）
    m = re.search(r"\n拼音\s*\n([^\n]+)", text)
    if m: out["pinyin"] = m.group(1).strip()
    # 基本解释段：从 " 基本解释 " 到下一个已知小节标题
    def section(name, stops):
        pat = re.escape(f" {name} ")
        m = re.search(pat + r"\n(.*?)(?=\n(?:" + "|".join(re.escape(s) for s in stops) + r")\n \1|\n(?:" + "|".join(re.escape(s) for s in stops) + r")|$)", text, re.S)
        return m.group(1).strip() if m else None
    stops = ["康熙字典", "说文解字", "字源字形", "字形对比", "同音字", "反馈"]
    out["basic"] = section("基本解释", stops)
    out["kangxi"] = section("康熙字典", stops)
    out["shuowen"] = section("说文解字", stops)
    # 异体字部件（页面里的 "异体字" glyph-evolution 小节，取其后的汉字候选，抓不到就算了）
    m = re.search(r'<h3 class="dict-sub-title">异体字</h3>(.*?)</div></div>', html, re.S)
    if m:
        chars = re.findall(r'title="([^"]{1,3})"', m.group(1))
        out["variants_widget"] = list(dict.fromkeys(chars))
    return out

def main():
    data_path = sys.argv[1]
    out_path = sys.argv[2]
    with open(data_path, encoding="utf-8") as f:
        d = json.load(f)
    chars = sorted({r["a"] for r in d["rows"]} | {r["b"] for r in d["rows"]})
    results = {}
    for i, ch in enumerate(chars):
        cp = f"U+{ord(ch):04X}"
        html = fetch(ch)
        info = extract_fields(html, ch)
        results[cp] = info
        sys.stderr.write(f"[{i+1}/{len(chars)}] {ch} {cp} basic={'Y' if info.get('basic') else 'N'} kangxi={'Y' if info.get('kangxi') else 'N'}\n")
        time.sleep(1.5)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"done: {len(results)} chars -> {out_path}")

if __name__ == "__main__":
    main()
