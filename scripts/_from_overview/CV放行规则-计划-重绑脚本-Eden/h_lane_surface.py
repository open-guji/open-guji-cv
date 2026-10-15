#!/usr/bin/env python3
"""H 道写入面快照与比对（GUJI-208ks）。只读：只 stat/读文件，不写 $WS，不起引擎。

  python3 -I h_lane_surface.py snap  <WS> --out snap.json [--extra 标签=路径 …]
  python3 -I h_lane_surface.py check <WS> --base snap.json [--extra 标签=路径 …]

五类 H 道写入物（路径模板取自终头 1deec56 的 core/workspace.py，见《S27自检路径-Eden.md》）。
内容比对用 sha256，不用 mtime（`GlyphDB(db_path)` 以读写打开会碰文件，但内容不变不算改）。
--extra 的根只比 (大小, mtime_ns)，给 $GUJI_PRODUCTS_DIR／$SNAP 这类大目录用。

退出码：0 一致；（208kv）--extra 根不存在／不是目录／是符号链接／根下 0 个文件→2；1 有 H 道面变动（停线）；3 只有 bindings 派生缓存变（警告，报 Mila）；2 用法／读错误／`GUJI_FEEDBACK_DIR` 等路径环境变量被设（查不准，停）。
"""
import hashlib, json, os, sys
from pathlib import Path

# (类, 标签, 相对 WS 的路径, 是否目录, 变动算什么)
SURFACES = [
    ("①事件", "feedback/events", "feedback/events", True, "stop"),
    ("①事件", "feedback/consumed", "feedback/consumed", True, "stop"),
    ("①事件", "feedback/routes.yaml", "feedback/routes.yaml", False, "stop"),
    ("①事件", "feedback/.write.lock", "feedback/.write.lock", False, "stop"),
    ("②裁决", "feedback/verdicts", "feedback/verdicts", True, "stop"),
    ("③绑定表", "feedback/bindings", "feedback/bindings", True, "warn"),   # 派生缓存：seed_admit 读路径会重写
    ("③绑定表", "feedback/anchors", "feedback/anchors", True, "stop"),
    ("③绑定表", "feedback/anchor_patches", "feedback/anchor_patches", True, "stop"),
    ("④排除名单", "config/crop_exclusions*.jsonl", "config", True, "stop"),
    ("⑤字形库", "output/glyph_store", "output/glyph_store", True, "stop"),
    ("⑤字形库", "output/glyph.db", "output/glyph.db", False, "stop"),
    ("⑤字形库", "output/glyph_selfcheck", "output/glyph_selfcheck", True, "stop"),
    ("⑥人裁其它", "feedback/lists", "feedback/lists", True, "stop"),
    ("⑥人裁其它", "feedback/candidates", "feedback/candidates", True, "stop"),
    ("⑥人裁其它", "review/batches", "review/batches", True, "stop"),
]
ENV_OVERRIDES = ["GUJI_FEEDBACK_DIR", "GUJI_VERDICTS_DIR", "GUJI_EXCLUSIONS", "GUJI_GLYPH_STORE",
                 "GUJI_GLYPH_DB", "GUJI_BATCHES_DIR"]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def files_of(root, rel, is_dir, label):
    p = Path(root) / rel
    out = []
    if is_dir:
        if p.is_dir():
            for q in sorted(p.rglob("*")):
                if q.is_file() or q.is_symlink():
                    r = str(q.relative_to(root))
                    if label.startswith("config/") and not Path(r).name.startswith("crop_exclusions"):
                        continue          # config/ 只取排除名单三份
                    out.append((r, q))
    elif p.is_file():
        out.append((rel, p))
    # glyph.db 旁的 -wal/-shm/-journal
    if rel == "output/glyph.db":
        for suf in ("-wal", "-shm", "-journal"):
            q = Path(str(p) + suf)
            if q.is_file():
                out.append((rel + suf, q))
    return out


def snap(ws, extras):
    ws = Path(ws).resolve()
    d = {"ws": str(ws), "env_overrides": {k: os.environ[k] for k in ENV_OVERRIDES if os.environ.get(k)},
         "h": {}, "extra": {}}
    for cls, label, rel, is_dir, sev in SURFACES:
        for r, q in files_of(ws, rel, is_dir, label):
            d["h"][r] = {"cls": cls, "sev": sev, "sha": sha(q)}
    for lab, path in extras:
        root = Path(path)
        ent = {}
        if root.is_dir():
            for q in sorted(root.rglob("*")):
                if q.is_file():
                    st = q.stat()
                    ent[str(q.relative_to(root))] = [st.st_size, st.st_mtime_ns]
        d["extra"][lab] = {"root": str(root), "files": ent}
    return d


def extra_problems(extras, cur=None, old=None):
    """208kv 零文件守卫：--extra 根不存在／不是目录／是符号链接／根下 0 个文件 → 返回说明列表（非空即 rc=2，不得静默当 0 个文件）。"""
    msgs = []
    for lab, path in extras:
        p = Path(path)
        if p.is_symlink():
            msgs.append(f"额外根 {lab}={path}：是符号链接（rglob 不跟随，会得 0 个文件）；请给真目录")
        elif not p.exists():
            msgs.append(f"额外根 {lab}={path}：路径不存在")
        elif not p.is_dir():
            msgs.append(f"额外根 {lab}={path}：不是目录")
        elif cur is not None and len(cur["extra"].get(lab, {}).get("files", {})) == 0:
            was = len(old["extra"].get(lab, {}).get("files", {})) if old else None
            extra = f"（基线记录里该根有 {was} 个文件，现在 0 个）" if was else ""
            msgs.append(f"额外根 {lab}={path}：根下 0 个文件{extra}")
    return msgs


def classes_summary(h):
    s = {}
    for r, v in h.items():
        s[v["cls"]] = s.get(v["cls"], 0) + 1
    return s


def main(argv):
    if len(argv) < 3 or argv[1] not in ("snap", "check"):
        print(__doc__); return 2
    mode, ws = argv[1], argv[2]
    out = base = None
    extras = []
    a = argv[3:]
    i = 0
    while i < len(a):
        if a[i] == "--out": out = a[i + 1]; i += 2
        elif a[i] == "--base": base = a[i + 1]; i += 2
        elif a[i] == "--extra":
            lab, _, path = a[i + 1].partition("="); extras.append((lab, path)); i += 2
        else:
            print("未知参数", a[i]); return 2
    if not Path(ws).is_dir():
        print("WS 不是目录:", ws); return 2
    cur = snap(ws, extras)
    old = None
    if mode == "check" and base and Path(base).is_file():
        try:
            old = json.loads(Path(base).read_text(encoding="utf-8"))
        except Exception:
            old = None
    bad = extra_problems(extras, cur, old)
    if bad:
        for m in bad:
            print("【停】" + m)
        return 2
    if cur["env_overrides"]:
        print("【停】环境变量把某些路径改指到工作区之外，本脚本只看 WS 下的约定路径，查不准；先 unset 或改指后再来：", cur["env_overrides"])
        return 2
    if mode == "snap":
        if not out:
            print("snap 需要 --out"); return 2
        Path(out).write_text(json.dumps(cur, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
        extra_desc = ", ".join("%s:%d" % (k, len(v["files"])) for k, v in cur["extra"].items())
        print(f"snap 已写 {out}：H 道面 {len(cur['h'])} 个文件 {classes_summary(cur['h'])}；额外根 {{{extra_desc}}}")
        return 0
    if not base:
        print("check 需要 --base"); return 2
    old = json.loads(Path(base).read_text(encoding="utf-8"))
    if old["ws"] != cur["ws"]:
        print(f"【停】WS 不是同一个：基线 {old['ws']} ≠ 现在 {cur['ws']}"); return 2
    stop = warn = 0
    for r in sorted(set(old["h"]) | set(cur["h"])):
        o, c = old["h"].get(r), cur["h"].get(r)
        if o and c and o["sha"] == c["sha"]:
            continue
        kind = "新增" if not o else "删除" if not c else "修改"
        v = c or o
        if v["sev"] == "warn":
            warn += 1; tag = "警告(派生缓存)"
        else:
            stop += 1; tag = "停线"
        print(f"[{tag}] {v['cls']} {kind}: {r}")
    for lab, e in cur["extra"].items():
        oe = old["extra"].get(lab, {"files": {}})["files"]
        for r in sorted(set(oe) | set(e["files"])):
            if oe.get(r) == e["files"].get(r):
                continue
            kind = "新增" if r not in oe else "删除" if r not in e["files"] else "修改"
            stop += 1
            print(f"[停线] 额外根 {lab} {kind}: {r}")
    n = len(cur["h"])
    if stop:
        print(f"结论：不一致（停线项 {stop}，派生缓存警告 {warn}）"); return 1
    if warn:
        print(f"结论：H 道面一致，仅 bindings 派生缓存变 {warn} 个（报 Mila，不自行放行）"); return 3
    print(f"结论：一致（H 道面 {n} 个文件，额外根 {len(cur['extra'])} 个）"); return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
