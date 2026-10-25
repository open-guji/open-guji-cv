#!/usr/bin/env python3
"""修过的页回传 Commons（设计稿 `doc/design/古籍图片全流程-源件页图管线与IIIF.md` §十三 第 2–4 步），给 GitHub runner 跑。

会话连不上 Commons（429），所以 workflow `commons-upload.yml` 在 runner 上跑本脚本。数据全从公开地址取（页表、根、页图都在
`blob.open-guji.com`），不用中心库令牌：

1. 读该册最新页表，取根 DjVu（核 sha256）和修过的页图（核 sha256），用 `sources.pack_for_commons` 出新版（逐页解码核对）。
2. 上传前检查：Commons 上的当前版本必须就是页表记的根（sha1 相同，免得盖掉别人后来的修改）；文件被维基文库等引用时停
   （`globalusage`，页数一变 Page: 页号会错位），这种得人来定。
3. `--upload` 才真传：BotPassword 登录（`COMMONS_BOT_USER`／`COMMONS_BOT_PASSWORD`），`action=upload` 上传新版本，
   摘要用 `sources.commons_comment`。传完再查一次，Commons 的 sha1 必须等于本地文件的。
4. 每册写 `<out>/<册>.commons.json`（Commons imageinfo），之后在会话里跑
   `guji source commons <书id> <册> --djvu <新版> --commons-json <它> --reroot --why …` 换根。

    python scripts/commons_upload.py --book-id 96mid1ogzk --vols 03,07 --out out/            # 只出文件、做检查
    python scripts/commons_upload.py --book-id 96mid1ogzk --vols 03,07 --out out/ --upload   # 真传（对外发布，要用户点头）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_guji_cv.datastore import sources as S  # noqa: E402

BLOB = os.environ.get("GUJI_PAGES_BASE", "https://blob.open-guji.com")
API = S.COMMONS_API
UA = "open-guji-commons-upload/0.1 (https://github.com/open-guji/open-guji-cv)"


def _get(client, url: str) -> bytes:
    for i in range(4):
        r = client.get(url, timeout=300)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(10 * (i + 1))
            continue
        r.raise_for_status()
        return r.content
    r.raise_for_status()
    return r.content


def latest_table(client, book_id: str, vol: str) -> dict:
    table, rev = None, 1
    while True:
        r = client.get(f"{BLOB}/pack/{S.table_key(book_id, vol, rev)}", timeout=60)
        if r.status_code == 404:
            if table is None:
                raise SystemExit(f"✗ {book_id}/{vol} 没有页表")
            return table
        r.raise_for_status()
        table, rev = r.json(), rev + 1


def fetch_root(client, root: dict, dest: Path) -> None:
    man = json.loads(_get(client, f"{BLOB}/pack/{root['r2']}/manifest.json"))
    with open(dest, "wb") as f:
        for part in man["parts"]:
            data = _get(client, f"{BLOB}/pack/{root['r2']}/{part['name']}")
            if hashlib.sha256(data).hexdigest() != part["sha256"]:
                raise SystemExit(f"✗ 根 {root['r2']} 的 {part['name']} sha256 不符")
            f.write(data)
    if man.get("encoding") == "gzip":
        import gzip
        dest.write_bytes(gzip.decompress(dest.read_bytes()))
    if S.sha256(dest.read_bytes()) != root["sha256"]:
        raise SystemExit(f"✗ 根 {root['r2']} 整份 sha256 不符")


def page_png(client, sha: str) -> bytes:
    data = _get(client, f"{BLOB}/sha256/{sha[:2]}/{sha}.png")
    if hashlib.sha256(data).hexdigest() != sha:
        raise SystemExit(f"✗ 页图 {sha} sha256 不符")
    return data


def commons_query(client, **params) -> dict:
    r = client.get(API, params={"action": "query", "format": "json", "formatversion": 2, **params}, timeout=60)
    r.raise_for_status()
    return r.json()


def commons_now(client, title: str) -> dict:
    page = commons_query(client, titles=title, prop="imageinfo|globalusage",
                         iiprop="url|sha1|size|timestamp")["query"]["pages"][0]
    ii = page["imageinfo"][0]
    return {"title": page["title"], "url": ii["url"].split("?", 1)[0], "sha1": ii["sha1"], "size": ii["size"],
            "timestamp": ii["timestamp"], "pagecount": ii.get("pagecount"), "globalusage": page.get("globalusage", [])}


def login(client) -> str:
    user, pw = os.environ.get("COMMONS_BOT_USER"), os.environ.get("COMMONS_BOT_PASSWORD")
    if not (user and pw):
        raise SystemExit("✗ 没配 COMMONS_BOT_USER／COMMONS_BOT_PASSWORD（Special:BotPasswords 建，放仓库 secret）")
    tok = commons_query(client, meta="tokens", type="login")["query"]["tokens"]["logintoken"]
    r = client.post(API, data={"action": "login", "format": "json", "lgname": user, "lgpassword": pw, "lgtoken": tok})
    if r.json().get("login", {}).get("result") != "Success":
        raise SystemExit(f"✗ 登录 Commons 失败：{r.json().get('login', {}).get('reason', r.text[:200])}")
    return commons_query(client, meta="tokens")["query"]["tokens"]["csrftoken"]


def upload(client, csrf: str, title: str, path: Path, comment: str) -> dict:
    with open(path, "rb") as f:
        r = client.post(API, data={"action": "upload", "format": "json", "filename": title.removeprefix("File:"),
                                   "comment": comment, "ignorewarnings": "1", "token": csrf},
                        files={"file": (path.name, f, "image/vnd.djvu")}, timeout=600)
    body = r.json()
    if body.get("upload", {}).get("result") != "Success":
        raise SystemExit(f"✗ 上传 {title} 失败：{json.dumps(body, ensure_ascii=False)[:400]}")
    return body["upload"]


def main(argv=None) -> int:
    import httpx
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--book-id", required=True)
    ap.add_argument("--vols", required=True, help="册号，逗号分隔")
    ap.add_argument("--out", required=True)
    ap.add_argument("--upload", action="store_true", help="真传（对外发布，要用户点头）")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report, bad = [], 0
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=120) as client:
        csrf = login(client) if a.upload else None
        for v in [S.norm_vol(x) for x in a.vols.split(",") if x.strip()]:
            t = latest_table(client, a.book_id, v)
            root = S.root_source(t)
            fixes = {p["sha256"] for p in t["pages"] if S.is_fix(p)}
            if not fixes:
                print(f"· {a.book_id}/{v} r{t['rev']:03d}：没有修过的页，不用回传")
                continue
            rp = out / f"root-{root['file']}"
            fetch_root(client, root, rp)
            pngs = {s: page_png(client, s) for s in fixes}
            new = out / root["file"]
            res = S.pack_for_commons(t, rp, pngs.__getitem__, new)
            comment = S.commons_comment(t, res)
            now = commons_now(client, root["commons_title"])
            row = {"vol": v, "title": now["title"], "pages": f"{res['pages_before']}→{res['pages_after']}",
                   "sha1": res["sha1"], "comment": comment}
            print(f"{a.book_id}/{v}：{now['title']} {row['pages']} 页，新版 sha1 {res['sha1'][:12]}…（逐页解码核过）")
            if now["sha1"] == res["sha1"]:
                print("  ✓ Commons 上已经是这一版，不用再传")
                row["status"] = "already"
            elif now["sha1"] != root["commons_sha1"]:
                print(f"  ✗ Commons 当前版本（{now['timestamp']}）不是页表记的根（{root['commons_timestamp']}），有人改过，停")
                row["status"] = "root-changed"
                bad += 1
            elif now["globalusage"]:
                print(f"  ✗ 被引用：{[g.get('wiki') + ':' + g.get('title', '') for g in now['globalusage']][:5]}，页数一变会错位，停")
                row["status"] = "in-use"
                bad += 1
            elif not a.upload:
                print("  · 检查都过了（没加 --upload，不传）")
                row["status"] = "ready"
            else:
                upload(client, csrf, now["title"], new, comment)
                after = commons_now(client, now["title"])
                if after["sha1"] != res["sha1"]:
                    print(f"  ✗ 传完 Commons sha1 {after['sha1']} ≠ 本地 {res['sha1']}")
                    row["status"] = "mismatch"
                    bad += 1
                else:
                    after.pop("globalusage", None)
                    (out / f"{v}.commons.json").write_text(json.dumps(after, ensure_ascii=False, indent=1) + "\n",
                                                          encoding="utf-8")
                    print(f"  ✓ 已传（{after['timestamp']}）；会话里 guji source commons … --reroot 换根")
                    row["status"] = "uploaded"
                    row["timestamp"] = after["timestamp"]
            report.append(row)
            rp.unlink()
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("| 册 | Commons 文件 | 页数 | 状态 |\n|---|---|---|---|\n")
            for r in report:
                f.write(f"| {r['vol']} | {r['title']} | {r['pages']} | {r['status']} |\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
