import json, re, sys, time, urllib.parse, urllib.request, os, subprocess
UA = "open-guji-research/1.0 (lisdpku@gmail.com)"
API = "https://commons.wikimedia.org/w/api.php"
BATCH, PER = int(sys.argv[1]), 16

def get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    for i in range(8):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60))
        except Exception as e:
            print("retry", i, e, file=sys.stderr); time.sleep(15 * (i + 1))
    raise SystemExit("api fail")

files = []
p = {"action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": "Category:欽定全唐文",
     "gcmtype": "file", "gcmlimit": "50", "prop": "imageinfo", "iiprop": "size|sha1"}
while True:
    d = get(p)
    for pg in d.get("query", {}).get("pages", {}).values():
        ii = (pg.get("imageinfo") or [{}])[0]
        files.append({"title": pg["title"], "pagecount": ii.get("pagecount"), "sha1": ii.get("sha1"), "size": ii.get("size")})
    if "continue" in d:
        p.update(d["continue"])
    else:
        break
key = lambda x: int(re.search(r"CADAL(\d+)", x["title"]).group(1))
c = [x for x in files if x["title"].startswith("File:CADAL01") and "欽定全唐文" in x["title"]]
a = sorted([x for x in c if re.search(r"卷\d+-\d+\.djvu", x["title"])], key=key)
fm = sorted([x for x in c if re.search(r"CADAL0102(2799|2800|2801|2802|2803)", x["title"])], key=key)
seq = fm + a
groups = [seq[0:2], seq[2:4]] + [seq[i:i + 2] for i in range(4, len(seq), 2)]
assert len(groups) == 248, len(groups)
sel = groups[BATCH * PER:(BATCH + 1) * PER]
os.makedirs("out", exist_ok=True)
json.dump([{"ce": "%02d" % (BATCH * PER + i + 1), "files": g} for i, g in enumerate(sel)], open("out/batch.json", "w"), ensure_ascii=False, indent=1)
log = open("out/got.log", "a")
for g in sel:
    for x in g:
        name = x["title"][5:]
        cid = name.split(" ")[0]
        enc = urllib.parse.quote(name.replace(" ", "_"))
        dest = f"out/{cid}.djvu"
        for i in range(1, 7):
            subprocess.run(["curl", "-sSL", "-m", "900", "-A", UA, "-o", dest, "https://commons.wikimedia.org/wiki/Special:FilePath/" + enc])
            if os.path.getsize(dest) > 100000:
                break
            time.sleep(i * 20)
        sha = subprocess.run(["sha1sum", dest], capture_output=True, text=True).stdout.split()[0]
        log.write(f"{cid} {os.path.getsize(dest)} {sha} {'OK' if sha == x['sha1'] else 'MISMATCH'}\n"); log.flush()
        time.sleep(3)
