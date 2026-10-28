import json, time, urllib.request, urllib.parse, sys
UA = "open-guji-research/1.0 (lisdpku@gmail.com)"
API = "https://commons.wikimedia.org/w/api.php"
def get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    for i in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as e:
            print("retry", i, e, file=sys.stderr)
            time.sleep(10 * (i + 1))
    raise SystemExit("fail")
out = []
p = {"action": "query", "format": "json", "generator": "categorymembers",
     "gcmtitle": "Category:欽定全唐文", "gcmtype": "file", "gcmlimit": "50",
     "prop": "imageinfo", "iiprop": "size|sha1|url"}
while True:
    d = get(p)
    for pg in d.get("query", {}).get("pages", {}).values():
        ii = (pg.get("imageinfo") or [{}])[0]
        out.append({"title": pg["title"], "size": ii.get("size"), "pagecount": ii.get("pagecount"),
                    "sha1": ii.get("sha1"), "w": ii.get("width"), "h": ii.get("height")})
    if "continue" in d:
        p.update(d["continue"])
    else:
        break
out.sort(key=lambda x: x["title"])
json.dump(out, open("out/cadal_files.json", "w"), ensure_ascii=False, indent=0)
print(len(out))
