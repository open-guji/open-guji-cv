"""证据包（设计第三节 ``evidence.py``、C1）：给会话或模型判一条意见用。

每条意见出一个目录 ``<out>/<意见 id>/``：
- ``target-<格>.png``：意见指的那几格的裁图（原图档，按 cord 框裁，四周留 ``pad`` 像素）；
- ``unit-<序>-<名>.png``：同列前后各 ``window`` 个单元（字格和 marks：排除名单、留白、印章）的裁图；
- ``strip.png``／``strip_marked.png``：这一段列条带原样、和画了框的（意见格红框、marks 蓝框、其余字格灰框）；
- ``evidence.json``：上下文 ±12 字、各单元的框与类别、marks 的说明（如「排除名单·非字」）、同格其他意见、``locate`` 结果、裁图 sha。

原图：cord 每页 ``canvas.id`` → IIIF manifest（``…/iiif/<书>/<册2位>/manifest.json``）里该 canvas 的 body
（Choice 取第一项），把 ``/full/1200,/`` 换成 ``/full/<canvas 宽>,/`` 即原图档。下载整页按内容 sha 缓存
（``$GUJI_DATA_HOME/_shared/iiif/``），再用 Pillow 裁。图宽与 canvas 不同时按比例换算框。

另出一页拼图 ``sheet.png``（每条一行：标了框的条带＋意见格裁图；图上只写 ASCII 编号）和 ``sheet.md``（中文详情）。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .schema import cell_key
from .textsrc import char_cells, cord_page

UA = {"user-agent": "open-guji-cv-opinions"}


def _http_get(url: str, timeout: float = 120) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def default_cache() -> Path:
    from ..core.workspace import data_home
    return data_home() / "_shared" / "iiif"


class ImageFetcher:
    """IIIF 整页原图：manifest 找 body，按内容 sha 缓存。``get`` 可换（测试用假的）。"""

    def __init__(self, cache: Path | None = None, get=_http_get):
        self.cache = Path(cache) if cache else default_cache()
        self.get = get
        self._manifests: dict[str, dict] = {}

    def _index(self) -> dict:
        p = self.cache / "urls.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}

    def _remember(self, url: str, sha: str, ext: str) -> None:
        idx = self._index()
        idx[url] = f"{sha}{ext}"
        self.cache.mkdir(parents=True, exist_ok=True)
        (self.cache / "urls.json").write_text(json.dumps(idx, indent=0, sort_keys=True), encoding="utf-8")

    def fetch(self, url: str) -> bytes:
        name = self._index().get(url)
        if name and (self.cache / name).is_file():
            return (self.cache / name).read_bytes()
        data = self.get(url)
        sha = hashlib.sha256(data).hexdigest()
        ext = Path(url.split("?")[0]).suffix[:6] or ".bin"
        self.cache.mkdir(parents=True, exist_ok=True)
        (self.cache / f"{sha}{ext}").write_bytes(data)
        self._remember(url, sha, ext)
        return data

    @staticmethod
    def manifest_url(canvas_id: str) -> str:
        m = re.match(r"^(.*)/canvas/(\d+)/\d+$", canvas_id)
        if not m:
            raise ValueError(f"认不出 canvas id：{canvas_id}")
        return f"{m.group(1)}/{m.group(2)}/manifest.json"

    def image_url(self, canvas: dict) -> str:
        """canvas → 原图档 URL（Choice 第一项，宽度换成 canvas 宽）。"""
        mu = self.manifest_url(canvas["id"])
        if mu not in self._manifests:
            self._manifests[mu] = json.loads(self.get(mu))
        man = self._manifests[mu]
        cv = next((c for c in man.get("items") or [] if c.get("id") == canvas["id"]), None)
        if cv is None:
            raise KeyError(f"manifest {mu} 里没有 canvas {canvas['id']}")
        body = cv["items"][0]["items"][0]["body"]
        if body.get("type") == "Choice":
            body = body["items"][0]
        width = int(canvas.get("width") or cv.get("width"))
        return re.sub(r"/full/[^/]+/", f"/full/{width},/", body["id"], count=1)

    def page(self, canvas: dict):
        from PIL import Image
        url = self.image_url(canvas)
        data = self.fetch(url)
        im = Image.open(io.BytesIO(data))
        im.load()
        return im.convert("RGB"), url, hashlib.sha256(data).hexdigest()


@dataclass
class Unit:
    """列里的一个单元：字格（``a``、``c``）或 mark（``kind``）。"""
    label: str
    box: list
    kind: str            # cell | excluded | blank | seal
    a: str | None = None
    c: str | None = None
    mark_id: str | None = None
    slot: int | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def column_units(cord_pg: dict, char_by_a: dict, col: int, order: list[str] | None = None) -> list[Unit]:
    """一列的字格加 marks。字格按 char 读序（``order``；不给按框上沿），marks 按框上沿插进去：
    排在第一个上沿比它低的字格之前。不按纯几何排字格：真书里有框互相重叠的（手补的格），几何序会颠倒。"""
    cells = []
    for c in cord_pg.get("cells") or []:
        a = c["a"]
        if int(a.split(":")[1]) != col:
            continue
        ch = char_by_a.get(a) or {}
        cells.append(Unit(label=a, box=c["box"], kind="cell", a=a, c=ch.get("c")))
    if order:
        pos = {a: i for i, a in enumerate(order)}
        cells.sort(key=lambda u: pos.get(u.a, len(pos)))
    else:
        cells.sort(key=lambda u: (u.box[1], -u.box[0]))
    marks = sorted((Unit(label=f"{m['kind']}@{m.get('slot', '?')}", box=m["box"], kind=m["kind"], mark_id=m.get("id"),
                         slot=m.get("slot"), note=m.get("note"))
                    for m in cord_pg.get("marks") or [] if m.get("col") == col), key=lambda u: u.box[1])
    out, mi = [], 0
    for u in cells:
        while mi < len(marks) and marks[mi].box[1] < u.box[1]:
            out.append(marks[mi])
            mi += 1
        out.append(u)
    return out + marks[mi:]


def _scale_box(box, s: float, pad: int, w: int, h: int) -> tuple[int, int, int, int]:
    x, y, bw, bh = box
    x0, y0 = int(round(x * s)) - pad, int(round(y * s)) - pad
    x1, y1 = int(round((x + bw) * s)) + pad, int(round((y + bh) * s)) + pad
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


def context(cells: list[dict], start: str, end: str, n: int = 12) -> str:
    seq = [c["a"] for c in cells]
    if start not in seq or end not in seq:
        return ""
    i, j = seq.index(start), seq.index(end)
    t = lambda xs: "".join(c["c"] for c in xs)   # noqa: E731
    return t(cells[max(0, i - n):i]) + "【" + t(cells[i:j + 1]) + "】" + t(cells[j + 1:j + 1 + n])


def _next_after(crops: list[dict]) -> dict | None:
    """意见格（最后一格）之后紧挨的那个单元。"""
    last = max((i for i, c in enumerate(crops) if c["target"]), default=None)
    return crops[last + 1] if last is not None and last + 1 < len(crops) else None


def build(op, char: dict, cord: dict, fetcher: ImageFetcher, out: Path, *, window: int = 3, pad: int = 6,
          others: list | None = None, located: dict | None = None) -> dict:
    """出一条意见的证据包，返回 evidence.json 的内容。"""
    from PIL import ImageDraw
    t = op.target or {}
    start, end = t.get("start"), t.get("end")
    if not start:
        raise ValueError(f"{op.id} 没有格号，先 normalize")
    cells = char_cells(char)
    by_a = {c["a"]: c for c in cells}
    page, col = int(start.split(":")[0]), int(start.split(":")[1])
    pg = cord_page(cord, page)
    if pg is None:
        raise KeyError(f"cord 里没有第 {page} 页")
    seq = [c["a"] for c in cells]
    tgt = seq[seq.index(start): seq.index(end) + 1] if start in seq and end in seq else [start]
    units = column_units(pg, by_a, col, seq)
    idx = [i for i, u in enumerate(units) if u.a in tgt]
    if not idx:
        raise KeyError(f"cord 第 {page} 页第 {col} 列找不到 {start}")
    lo, hi = max(0, min(idx) - window), min(len(units), max(idx) + window + 1)
    win = units[lo:hi]

    im, url, img_sha = fetcher.page(pg["canvas"])
    cw = float(pg["canvas"].get("width") or im.width)
    s = im.width / cw
    d = Path(out) / op.id
    d.mkdir(parents=True, exist_ok=True)

    def save(img, name):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        (d / name).write_bytes(buf.getvalue())
        return hashlib.sha256(buf.getvalue()).hexdigest()

    crops = []
    for k, u in enumerate(win):
        box = _scale_box(u.box, s, pad, im.width, im.height)
        name = (f"target-{u.a.replace(':', '_')}.png" if u.a in tgt
                else f"unit-{k:02d}-{(u.a or u.label).replace(':', '_').replace('@', '_')}.png")
        sha = save(im.crop(box), name)
        crops.append({**u.to_dict(), "file": name, "crop": list(box), "sha256": sha, "target": u.a in tgt})

    xs = [b for u in win for b in (u.box[0], u.box[0] + u.box[2])]
    ys = [b for u in win for b in (u.box[1], u.box[1] + u.box[3])]
    sbox = _scale_box([min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)], s, pad * 3, im.width, im.height)
    strip = im.crop(sbox)
    strip_sha = save(strip, "strip.png")
    marked = strip.copy()
    dr = ImageDraw.Draw(marked)
    for u in win:
        x0, y0, x1, y1 = _scale_box(u.box, s, 0, im.width, im.height)
        rect = (x0 - sbox[0], y0 - sbox[1], x1 - sbox[0], y1 - sbox[1])
        color = (220, 0, 0) if u.a in tgt else (0, 90, 220) if u.kind != "cell" else (150, 150, 150)
        dr.rectangle(rect, outline=color, width=3 if u.a in tgt else 2)
    save(marked, "strip_marked.png")

    ev = {
        "opinion": op.id, "vol": op.vol, "page": page, "col": col, "target": tgt,
        "check": t.get("check"), "proposal": op.proposal, "category": op.category, "note": op.note,
        "context": context(cells, tgt[0], tgt[-1]) if tgt[0] in by_a else "",
        "image": {"url": url, "sha256": img_sha, "size": [im.width, im.height], "canvas": pg["canvas"].get("id"),
                  "scale": s},
        "strip": {"crop": list(sbox), "sha256": strip_sha},
        "units": crops,
        "marks_near": [c for c in crops if c["kind"] != "cell"],
        "next_after_target": _next_after(crops),
        "others": [{"id": o.id, "status": st, "category": o.category, "proposal": o.proposal}
                   for o, st in (others or [])],
        "located": located,
    }
    (d / "evidence.json").write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")
    return ev


def sheet(evs: list[dict], out: Path, row_h: int = 560) -> tuple[Path, Path]:
    """拼图：每条意见一行（标了框的条带缩到 row_h 高＋意见格裁图）；图上只写 ASCII 编号，中文详情在 sheet.md。"""
    from PIL import Image, ImageDraw
    out = Path(out)
    rows = []
    for i, ev in enumerate(evs, 1):
        d = out / ev["opinion"]
        strip = Image.open(d / "strip_marked.png").convert("RGB")
        k = row_h / strip.height
        strip = strip.resize((max(1, int(strip.width * k)), row_h))
        tiles = [strip]
        for c in ev["units"]:
            if c["target"] or c["kind"] != "cell":
                t = Image.open(d / c["file"]).convert("RGB")
                kk = min(1.0, (row_h // 2) / max(1, t.height))
                tiles.append(t.resize((max(1, int(t.width * kk)), max(1, int(t.height * kk)))))
        w = sum(t.width for t in tiles) + 12 * (len(tiles) + 1)
        row = Image.new("RGB", (max(w, 480), row_h + 34), "white")
        ImageDraw.Draw(row).text((8, 6), f"#{i} {ev['opinion']}  p{ev['page']} c{ev['col']}  "
                                 + " ".join(ev["target"]), fill=(0, 0, 0))
        x = 12
        for t in tiles:
            row.paste(t, (x, 28))
            x += t.width + 12
        rows.append(row)
    W = max(r.width for r in rows) if rows else 480
    H = sum(r.height for r in rows) if rows else 40
    sh = Image.new("RGB", (W, H), "white")
    y = 0
    for r in rows:
        sh.paste(r, (0, y))
        y += r.height
    png = out / "sheet.png"
    sh.save(png)
    md = ["# 证据包", "", "| # | 意见 | 位置 | 原文→建议 | 上下文 | 旁边的 marks | 同格其他意见 |", "|---|---|---|---|---|---|---|"]
    for i, ev in enumerate(evs, 1):
        prop = ev.get("proposal") or {}
        p = (prop.get("choice", "") + ("=" if prop.get("choice") and prop.get("text") else "") + prop.get("text", "")) or "—"
        marks = "；".join(f"{m['label']}{('（' + m['note'] + '）') if m.get('note') else ''} 框{m['box']}"
                         for m in ev["marks_near"]) or "—"
        oth = "；".join(f"{o['id']}（{o['status']}）" for o in ev["others"]) or "—"
        md.append(f"| {i} | `{ev['opinion']}` | {ev['vol']} {'、'.join(ev['target'])} | {ev.get('check') or '—'}→{p} | "
                  f"{ev['context']} | {marks} | {oth} |")
    md += ["", "图例：红框＝意见指的格；蓝框＝marks（排除名单、留白、印章）；灰框＝其他字格。每条的裁图与 evidence.json 在同名子目录。"]
    for i, ev in enumerate(evs, 1):
        nx = ev.get("next_after_target")
        md += ["", f"## #{i} {ev['opinion']}", "",
               f"- 类别 {ev['category']}；读者原话：{ev.get('note') or '—'}",
               f"- 原图 {ev['image']['url']}（{ev['image']['size'][0]}×{ev['image']['size'][1]}，sha256 {ev['image']['sha256'][:12]}…）",
               f"- 意见格之后紧挨的单元：{(nx['label'] + ('（' + nx['note'] + '）' if nx.get('note') else '') + ' 框' + str(nx['box'])) if nx else '—'}"]
        if ev.get("located"):
            lo = ev["located"]
            md.append(f"- 定位：当前 {lo.get('text_version')}，提时 {lo.get('asked_at')}，现文 {lo.get('current_text')}"
                      + (f"；⚠ {lo['drift']}" if lo.get("drift") else ""))
    mdp = out / "sheet.md"
    mdp.write_text("\n".join(md) + "\n", encoding="utf-8")
    return png, mdp


def same_cell_others(store, op) -> list:
    """同章、格位有重叠的其他意见（带状态）。"""
    t = op.target or {}
    if not t.get("start"):
        return []
    lo, hi = cell_key(t["start"]), cell_key(t["end"])
    st = store.statuses()
    out = []
    for o in store.opinions.values():
        tt = o.target or {}
        if o.id == op.id or o.vol != op.vol or not tt.get("start"):
            continue
        if cell_key(tt["start"]) <= hi and cell_key(tt["end"]) >= lo:
            out.append((o, st[o.id]))
    return out
