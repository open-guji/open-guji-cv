"""发布闸（text_release.py）用的小工具：章号／数据目录、网站票、票账、读者侧冒烟。

2026-11-27 整张换单脚本退役（republish.py 等）时从其中抽出；各格独立，没有 rev／整张单。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CV = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

def _book_dict(book: str) -> dict:
    """生效的册配置（册 yaml ∪ 基础配置），读不到给空。"""
    try:
        from open_guji_cv.core.book import _book_yaml_path
        from open_guji_cv.core.book_config import effective_book_dict
        return effective_book_dict(_book_yaml_path(book), apply_override=False)
    except Exception:  # noqa: BLE001
        return {}


def chapter_of(book: str) -> str:
    """册号 → book-text 章号，按册配置（`core/volume_id`）；认不出就停（以前推成 000）。"""
    from open_guji_cv.core.volume_id import chapter_of as _chapter_of
    ch = _chapter_of(book)
    if not ch:
        sys.exit(f"✗ {book} 推不出章号：册 yaml 写上 volume（见 open_guji_cv/core/volume_id.py），或给 --chapter NNN")
    return ch


def text_id_of(ws: Path) -> str:
    """book-text 条目 id = 书目录名 `<id>-<书名>` 的 id 段（四庫總目 96mid1ogzk）。"""
    return ws.name.split("-", 1)[0]



def data_dir(ws: Path) -> Path:
    """迁了中心库的工作区是数据目录，没迁的就是工作区自己（`core.workspace.data_root`）。"""
    sys.path.insert(0, str(CV))
    from open_guji_cv.core.workspace import data_root
    return data_root(ws)


def proofing_path(ws: Path, text_id: str, chapter: str) -> Path:
    return data_dir(ws) / "feedback" / "lists" / "proofing" / text_id / f"{chapter}.pending.json"



SITE = "https://www.openguji.com"


def _get_json_retry(req, tries: int = 5) -> dict:
    """读网站票的接口时不时断连（11-16 实测 ConnectionResetError 多次），退避重试，别让一次断连挡住出单。"""
    import time
    import urllib.error
    import urllib.request
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == tries - 1:
                raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if i == tries - 1:
                raise
        wait = 2 ** (i + 1)
        print(f"  读网站票断连，{wait}s 后重试（{i + 1}/{tries - 1}）", file=sys.stderr)
        time.sleep(wait)
    raise AssertionError("unreachable")


def _fetch_votes(q: dict, tok: str) -> list[dict]:
    import urllib.parse
    import urllib.request
    items, cursor = [], ""
    while True:
        qq = {**q, "limit": "256", **({"cursor": cursor} if cursor else {})}
        req = urllib.request.Request(f"{SITE}/api/cellreview?{urllib.parse.urlencode(qq)}",
                                     headers={"Authorization": f"Bearer {tok}", "User-Agent": "open-guji-cv/release"})
        d = _get_json_retry(req)
        if not d.get("success"):
            sys.exit(f"✗ 读网站票失败：{d.get('error')}")
        items += d.get("items") or []
        cursor = d.get("cursor") or ""
        if not d.get("hasMore") or not cursor:
            return items


#: 「各格独立」口径下票账的 rev 占位：票只按条目认（`?items=1`），不再分哪一版单；`latest_votes` 要求 rev 相符，
#: 这里给每张票盖同一个占位。清理计划 v2 第二节：没有 rev／批次概念。

CURRENT = "current"


def old_rev_votes(ws: Path, text_id: str, rev: str | None, chapter: str | None = None) -> tuple[list[dict], str]:
    """一章的全部精校票，**两种记法都读**（11-13 第五册 005-r13 的 25 票因只查一种而漏落）：
    ① 按单版记的票（`?rev=`，旧网站）；② 按条目记的票（`?items=1`，新网站，11-10 起），按条目换成该册现在的格号、rev 记成 `rev`。
    **`rev=None` 是各格独立口径**（发布闸用）：只读②（按条目的票），不分哪一版单，票上的 rev 记成 `CURRENT`，要给 `chapter`。
    有 CELLREVIEW_TOKEN 就直接读网站 KV（刚投的票每日同步还没并进中心库），否则读数据目录里每日同步存下的
    `feedback/lists/web/<书>/<rev>.jsonl` 与 `items.jsonl`。**没有令牌又没有快照 → 停**（以前当成「0 票」静默放行）。
    返回 (票, 来源)。"""
    tok = os.environ.get("CELLREVIEW_TOKEN")
    chap = chapter or (rev or "").split("-r")[0]
    tag = rev or CURRENT
    if tok:
        by_rev = _fetch_votes({"rev": rev, "book": text_id}, tok) if rev else []
        raw_items = _fetch_votes({"items": "1", "book": text_id}, tok)
        where = "网站 KV"
    else:
        wd = data_dir(ws) / "feedback" / "lists" / "web" / text_id
        f, fi = wd / f"{rev}.jsonl", wd / "items.jsonl"
        if not (rev and f.exists()) and not fi.exists():
            sys.exit(f"✗ 读不到{'旧单 ' + rev if rev else '这章'}的票：没设 CELLREVIEW_TOKEN，数据目录也没有 {fi}"
                     + (f" 和 {f}" if rev else "") + "。先 guji db pull（或设令牌直读网站），别当成「0 票」往下走。")
        rd = lambda p: [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
        by_rev, raw_items = (rd(f) if rev else []), rd(fi)
        where = "中心库快照（每日同步之后的票看不到，设 CELLREVIEW_TOKEN 读 KV）"
    out = list(by_rev)
    n_item = 0
    if raw_items:
        from guji_manager.review import pending_items as P
        store = P.ItemStore.open(data_dir(ws), text_id, chap)
        for v in raw_items:
            if str(v.get("vol") or "").zfill(3) != chap.zfill(3):
                continue
            it = store.items.get(v.get("item") or "")
            if it is None:
                continue
            out.append({**v, "a": it["cell"], "rev": tag, "item": it["id"]})
            n_item += 1
    return out, f"{where}：" + (f"按单版 {len(by_rev)} 票＋" if rev else "") + f"按条目 {n_item} 票"



DATA = "https://data.openguji.com"


def _http(url: str, method: str = "GET", timeout: int = 30, first_byte: bool = False):
    import urllib.request
    # data.openguji.com 的图有防盗链（无 Referer 一律 403），读者侧冒烟要带上，否则云端容器里必误报
    headers = {"User-Agent": "open-guji-cv/release", "Referer": "https://www.openguji.com/"}
    if first_byte:              # 只取第 1 个字节：查图在不在，不下整张
        headers["Range"] = "bytes=0-0"
    req = urllib.request.Request(url, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, (r.read() if method == "GET" else b"")


def _img_ok(url: str) -> int | str:
    """读者侧查一张图：GET 只取首字节（200／206 都算到）。CDN 新对象 HEAD 常 403 好几分钟、GET 已 200
    （史記 001-r2／013-r2，11-25），所以不用 HEAD。返回 200 或失败原因。"""
    try:
        code, _ = _http(url, first_byte=True)
    except Exception as e:  # noqa: BLE001
        return str(e)
    return 200 if code in (200, 206) else code


def smoke(text_id: str, chapter: str, rev: str | None = None, tries: int = 10, wait_s: int = 60) -> list[str]:
    """读者侧冒烟：单上引用的每张图都取得到（CDN 刚清，旧单可能还要一会儿才换掉）；给了 `rev` 还要线上单就是这一版
    （整张换单流程用），`rev=None` 不看版本（各格独立口径，发布闸用）。返回问题列表。

    最多等约 10 分钟：册006 r5（10-24）发布跑完后新图 403 了 3 分钟以上，过一会儿全是 200（CDN 生效慢）。"""
    import time
    for i in range(tries):
        bad = []
        try:
            # 11-27 起整张单不再上传 COS（`/proof/<书>/<章>.pending.json` 新章号一直 404），改查网站由条目现拼的 /api/pending
            _, body = _http(f"{SITE}/api/pending?book={text_id}&vol={chapter}&x={int(time.time())}")
            doc = json.loads(body)
            if not isinstance(doc.get("cells"), list):
                doc, bad = {}, ["网站 /api/pending 没给出这一章的 cells"]
        except Exception as e:  # noqa: BLE001
            doc, bad = {}, [f"取不到线上单：{e}"]
        if doc and rev and doc.get("rev") and doc.get("rev") != rev:
            bad = [f"线上单还是 {doc.get('rev')}，不是 {rev}"]
        elif doc:
            for name in sorted(_sprite_refs(doc)):
                code = _img_ok(f"{DATA}/proof/{text_id}/{chapter}/{name}")
                if code != 200:
                    bad.append(f"{name} → {code}")
        if not bad:
            return []
        if i < tries - 1:
            time.sleep(wait_s)
    return bad



def book_text_dir(repo: Path, text_id: str) -> Path:
    hit = sorted(Path(repo).glob(f"Book/*/*/*/{text_id}/default"))
    if not hit:
        sys.exit(f"✗ {repo} 里没有 Book/…/{text_id}/default")
    return hit[0]


def _sprite_refs(doc: dict) -> set[str]:
    """单子引用的全部图名：格的 `img.s`、相似字的 `alt[].g.s`。"""
    out: set[str] = set()
    for c in doc.get("cells") or ():
        if isinstance(c.get("img"), dict) and c["img"].get("s"):
            out.add(c["img"]["s"])
        for x in c.get("alt") or ():
            if isinstance(x.get("g"), dict) and x["g"].get("s"):
                out.add(x["g"]["s"])
    return out


def ticket_ledger(ws: Path, book: str, text_id: str, rev: str, votes: list[dict], held=None) -> dict:
    """票账（1.0 发布标准 G0）：每格最后一票归到 写入／与已有人裁一致／看不出／挂起／未落 之一。账要平。
    写入 = 该格有晚于这一票的定字人裁；一致 = 定字人裁早于这一票；看不出 = 只投了「看不出」；
    挂起 = 在 cellvotes draft 的挂起清单里；其余未落。各格独立，格号一律是现行格号（票按条目记）。"""
    import datetime as dt
    sys.path.insert(0, str(CV))
    sys.path.insert(0, str(HERE))
    from guji_manager.feedback.web_votes import latest_votes
    from pending_route import cell_of, deciding, figure_ruling
    from open_guji_cv.core.event_files import RevGate, iter_event_dicts
    latest, dropped = latest_votes(votes, text_id, rev)
    held = set(held or ())
    last: dict[str, float] = {}
    gate = RevGate(books_dir=data_dir(ws) / "books")
    for e in iter_event_dicts(data_dir(ws) / "feedback" / "events", gate=gate):
        c = cell_of(e, book) if (deciding(e) or figure_ruling(e)) else None
        if c:
            try:
                t = dt.datetime.fromisoformat(str(e.get("ts")).replace("Z", "+00:00")).timestamp()
            except ValueError:
                t = 0.0
            last[c] = max(last.get(c, 0.0), t)
    if gate.note():
        print(f"  ⓘ {gate.note()}", file=sys.stderr)
    rows = {"写入": [], "与已有人裁一致": [], "看不出": [], "挂起": [], "未落": []}
    for v in latest:
        a, ts = v["a"], float(v.get("ts") or 0)
        ts = ts / 1000 if ts > 1e11 else ts       # KV 里是毫秒
        if v["choice"] == "unsure":
            rows["看不出"].append(v)
        elif a in last:
            rows["写入" if last[a] >= ts else "与已有人裁一致"].append(v)
        elif a in held:
            rows["挂起"].append(v)
        else:
            rows["未落"].append(v)
    return {"rev": rev, "votes": len(latest), "dropped": dropped, "rows": rows,
            "counts": {k: len(x) for k, x in rows.items()}}


def _vote_cell(v: dict) -> str:
    return v["a"]


def ledger_md(led: dict) -> str:
    c = led["counts"]
    ok = "账平" if sum(c.values()) == led["votes"] else "账不平"
    s = (f"票账（各格独立）：有效 {led['votes']} 格 = 写入 {c['写入']} ＋ 一致 {c['与已有人裁一致']} ＋ 看不出 {c['看不出']}"
         f" ＋ 挂起 {c['挂起']} ＋ 未落 {c['未落']}（{ok}）")
    if c["未落"]:
        s += "；未落：" + " ".join(f"{_vote_cell(v)}({v['choice']})" for v in led["rows"]["未落"][:20])
    return s
