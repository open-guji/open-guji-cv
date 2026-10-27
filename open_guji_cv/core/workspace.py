"""工作区路径解析：把「引擎」与「某本书的数据」分开。

## 为什么有这个模块

`open-guji-cv` 是识别引擎，不该自带某一本书的原图与字形库。
《四庫全書總目》那套数据（原图 134 MB、字形库 88 MB、产物 86 MB）已迁到
`guji-workspace` 私有仓（一部书一个目录，`<book-index id>-<书名>`）；引擎这边只留一个小样本库供测试。

于是路径要能指向别处。解析顺序（先到先得）：

1. 环境变量 —— `GUJI_GLYPH_DB` / `GUJI_GLYPH_STORE` / `GUJI_WORKSPACE`
2. 册配置 —— `books/<book>.yaml` 里的 `glyph_db` / `glyph_store`（可相对 workspace）
3. 仓内默认 —— `output/glyph.db`、`output/glyph_store/`（样本库，够跑测试）

`GUJI_WORKSPACE` 是最省事的一个：指到工作区仓根，库与产物都按约定布局往下找。

## 工作区布局（2026-09-13 起运行时数据**全部**在这里，引擎仓不落任何一本书的数据）

```
<workspace>/
  books/<book>.yaml            册配置
  data_full/…                  原图（raw_root）
  corpus/<name>.txt            整理本语料（迁到中心库后在数据目录，见 corpus_dir）
  output/glyph.db, glyph_store/  字形库索引 + 真源
  products/<book>/<step>/      数值产物（可重算，不进 git）
  cache/<book>/<kind>/         派生图像 LRU 缓存（不进 git）
  review/batches/              人裁批次登记
  feedback/{events,consumed}/  人裁事件日志与消费记账
  feedback/verdicts/<shard>/   裁决表（事件消费后的落点；金标同格式，导入测试集从这里挑）
  config/crop_exclusions.jsonl 图块排除名单
```

`open-guji-dataset`（测试集仓）**不在这张图里**：运行时不读不写，只放显式导入的标注。

## 用法

```bash
# 跑真书：指向工作区仓
export GUJI_WORKSPACE=/d/workspace/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本
guji pipeline keben_body_v2 vol01 --pages dev_set

# 跑测试：什么都不设，用仓内样本库
pytest tests/ -s -p no:cacheprovider
```

⚠️ **库路径变了，产物就该过期**——`glyph_match` / `seed_admit` 的指纹带库指纹，
换库等于换了上游。这是对的，不是 bug。
"""
from __future__ import annotations

import os
import re
from contextvars import ContextVar
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# 工作区内的约定布局（与仓内 output/ 保持一致，迁移时不必改结构）
GLYPH_DB_REL = "output/glyph.db"
GLYPH_STORE_REL = "output/glyph_store"
# 2026-09-13 起运行时数据全部归 workspace（用户裁定：引擎仓不落任何一本书的运行数据；
# 测试集仓 open-guji-dataset 只放显式导入的标注，运行时不读不写）。相对路径与引擎仓内
# 旧默认一致，`git mv` 过去即可。
PRODUCTS_REL = "products"
CACHE_REL = "cache"
BATCHES_REL = "review/batches"
EXCLUSIONS_REL = "config/crop_exclusions.jsonl"
FEEDBACK_REL = "feedback"
VERDICTS_REL = "feedback/verdicts"
REPORTS_REL = "reports"

#: 写入切换后（GUJI-608）中心库管的数据不放在工作区里，放「数据目录」：
#: ``GUJI_DATA_HOME``（缺省 ``~/.guji-data``）/<分支>/<工作区 id>/，布局同工作区
#: （books/ feedback/ review/ config/ output/glyph_store/）。工作区根有这个标记文件
#: 才这样解析；没有就是旧布局（数据在工作区里），测试与没迁的工作区照旧。
CENTRAL_MARKER = ".central.json"


#: 每请求（或每任务）的工作区覆盖。**优先于环境变量**。
#:
#: 2026-09-15：控制台要支持「开两个标签页，各自在不同工作区上干活」，
#: 于是工作区不能是进程级的全局状态——它只存在于浏览器，每个请求用
#: `X-Guji-Workspace` 头带过来，中间件塞进这个 contextvar（见
#: `console/middleware.py`）。`contextvars` 天然按请求/任务隔离，
#: 并发请求之间不会串。
#:
#: CLI 与跑批子进程不设这个，仍然走 `GUJI_WORKSPACE` 环境变量——
#: 那边一个进程就是一个工作区，本来就不需要隔离。
_WORKSPACE_OVERRIDE: ContextVar[str | None] = ContextVar("guji_workspace", default=None)


def set_workspace_override(path: str | None):
    """设本上下文的工作区，返回 token（用 `reset_workspace_override` 还原）。"""
    return _WORKSPACE_OVERRIDE.set(path)


def reset_workspace_override(token) -> None:
    _WORKSPACE_OVERRIDE.reset(token)


def workspace_root() -> Path | None:
    """当前工作区仓根；没有返回 None（用仓内默认）。

    解析顺序：**本请求的覆盖**（contextvar）> `GUJI_WORKSPACE` 环境变量 > 无。
    覆盖排在最前，是为了让控制台做到「每个标签页各自一个工作区」而进程本身
    不持有状态。"""
    over = _WORKSPACE_OVERRIDE.get()
    if over is not None:
        return Path(over).expanduser().resolve() if over else None
    env = os.environ.get("GUJI_WORKSPACE")
    return Path(env).expanduser().resolve() if env else None


def data_home() -> Path:
    """各工作区数据目录的总根：``GUJI_DATA_HOME``，缺省 ``~/.guji-data``。"""
    return Path(os.environ.get("GUJI_DATA_HOME") or Path.home() / ".guji-data").expanduser()


def central_marker(ws: Path | None = None) -> dict | None:
    """工作区根的 ``.central.json``（{ws, branch}）；没有返回 None（旧布局）。

    设了 ``GUJI_DATA_BRANCH`` 就以它为准（如 ``exp/GUJI-612-try``）：同一个工作区换到实验分支的数据目录，
    下面所有路径函数、pull／push／sync 都跟着走，不改标记文件。"""
    import json
    ws = ws if ws is not None else workspace_root()
    if ws is None:
        return None
    f = Path(ws) / CENTRAL_MARKER
    if not f.is_file():
        return None
    m = json.loads(f.read_text(encoding="utf-8"))
    over = os.environ.get("GUJI_DATA_BRANCH")
    if over:
        m = {**m, "branch": over}
    return m


def active_branch(ws: Path | None = None) -> str:
    """当前工作区读写的中心库分支：``GUJI_DATA_BRANCH`` > 标记里的 > main。"""
    m = central_marker(ws)
    return str((m or {}).get("branch") or os.environ.get("GUJI_DATA_BRANCH") or "main")


def _branch_local(rel: str) -> Path | None:
    """实验分支上，可重建的本地文件（glyph.db、products）放进该分支的数据目录，免得与正式库的那份互相覆盖。"""
    ws = workspace_root()
    m = central_marker(ws) if ws is not None else None
    if not m or str(m.get("branch") or "main") == "main":
        return None
    return central_data_dir(str(m["ws"]), str(m["branch"])) / rel


def central_data_dir(ws_id: str, branch: str = "main") -> Path:
    return data_home() / branch.replace("/", "__") / ws_id


#: 借库条目是中心库工作区名的样子（不含 /）；否则当路径（旧布局，相对工作区根）
_CENTRAL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def borrowed_root(ws_id: str, branch: str = "main") -> Path:
    """借来的中心库工作区的只读副本（``db pull`` 拉，共享方案 S4）：``$GUJI_DATA_HOME/<分支>/.borrowed/<工作区>/``。

    与那个工作区自己的数据目录分开：本机也在整理它时，拉借库不会盖掉那边没推的改动。"""
    return data_home() / branch.replace("/", "__") / ".borrowed" / ws_id


def resolve_borrow(entry: str, ws: Path) -> Path:
    """``workspace.yaml`` 的 ``glyph_lib.borrow`` 一条 → 被借字形库目录。

    迁过的工作区写中心库工作区名（``siku-zongmu``、``glyphlib-qkp-v1``）→ 借库只读副本；
    写路径的（旧布局，绝对或相对工作区根）照旧当路径。"""
    ws = Path(ws)
    m = central_marker(ws)
    if m and _CENTRAL_NAME.match(entry) and not (ws / entry).exists():
        return borrowed_root(entry, str(m.get("branch") or "main")) / "output" / "glyph_store"
    p = Path(entry).expanduser()
    return p if p.is_absolute() else ws / p


def data_root(ws: Path | None = None) -> Path | None:
    """中心库管的数据（册 yaml、人裁、台账、配置、字形库）所在的根。

    工作区迁到中心库后（有 ``.central.json``）是数据目录，否则就是工作区自己；
    没有工作区返回 None。"""
    ws = ws if ws is not None else workspace_root()
    if ws is None:
        return None
    m = central_marker(ws)
    if m:
        return central_data_dir(str(m["ws"]), str(m.get("branch") or "main"))
    return Path(ws)


def central_rev(ws: Path | None = None) -> str | None:
    """本机数据目录对应中心库的哪一版：``<工作区>@<分支>:<rev>``（读 ``.central-state.json``，
    ``db pull``／``push`` 时写）。没迁、没拉过返回 None。

    记进每条产物 manifest（``ManifestEntry.db_rev``）和产物包的 ``versions``：``glyph_pin`` 只钉指纹、
    不钉字形库内容，要知道一页当时读的是哪版库、要从那版开 Neon 分支复现，就看这个。
    拉过之后本机又裁了、还没推的改动不在这个 rev 里。"""
    import json
    d = data_root(ws)
    if d is None:
        return None
    try:
        st = json.loads((d / ".central-state.json").read_text(encoding="utf-8"))
        return f"{st['ws']}@{st.get('branch') or 'main'}:{int(st['rev'])}"
    except (OSError, ValueError, KeyError, TypeError):
        return None


def books_dir(ws: Path | None = None) -> Path | None:
    """册配置 ``books/``（见 ``data_root``）。"""
    d = data_root(ws)
    return d / "books" if d is not None else None


def ws_config_dir(ws: Path | None = None) -> Path | None:
    """工作区的人工配置 ``config/``（排除名单、字组字频与答案表等；见 ``data_root``）。"""
    d = data_root(ws)
    return d / "config" if d is not None else None


def _resolve(env_key: str, rel: str, override: str | Path | None = None, data: bool = False) -> Path:
    """环境变量 > 显式覆盖 > 工作区（``data`` 时是数据根）> 仓内默认。"""
    env = os.environ.get(env_key)
    if env:
        return Path(env).expanduser()
    base = data_root() if data else workspace_root()
    if override:
        p = Path(override).expanduser()
        # 相对路径按工作区（数据根）解释，没有工作区就按仓根
        return p if p.is_absolute() else (base or REPO_ROOT) / p
    if base:
        return base / rel
    return REPO_ROOT / rel


def glyph_db_path(override: str | Path | None = None) -> Path:
    """字形库 SQLite 索引。可重建，不进 git。实验分支上缺省在该分支的数据目录里（见 ``_branch_local``）。"""
    if not os.environ.get("GUJI_GLYPH_DB") and not override:
        p = _branch_local(GLYPH_DB_REL)
        if p is not None:
            return p
    return _resolve("GUJI_GLYPH_DB", GLYPH_DB_REL, override)


def glyph_store_path(override: str | Path | None = None) -> Path:
    """字形库真源（PNG + JSONL），进 git。"""
    return _resolve("GUJI_GLYPH_STORE", GLYPH_STORE_REL, override, data=True)


def products_root() -> Path:
    """数值产物 `products/<book>/<step>/`。`GUJI_PRODUCTS_DIR` > 工作区 > 仓内默认。
    实验分支上缺省在该分支的数据目录里（见 ``_branch_local``）。"""
    if not os.environ.get("GUJI_PRODUCTS_DIR"):
        p = _branch_local(PRODUCTS_REL)
        if p is not None:
            return p
    return _resolve("GUJI_PRODUCTS_DIR", PRODUCTS_REL)


def cache_root() -> Path:
    """派生图像缓存（列图 / 字块 / 归一图块，LRU）。`GUJI_CACHE_DIR` > 工作区 > 仓内。"""
    return _resolve("GUJI_CACHE_DIR", CACHE_REL)


def batches_root() -> Path:
    """人裁批次登记。`GUJI_BATCHES_DIR` > 工作区 > 仓内。"""
    return _resolve("GUJI_BATCHES_DIR", BATCHES_REL, data=True)


def exclusions_path() -> Path:
    """图块排除名单（人裁 / 闸判定的坏图块）。`GUJI_EXCLUSIONS` > 工作区 > 仓内。"""
    return _resolve("GUJI_EXCLUSIONS", EXCLUSIONS_REL, data=True)


def feedback_root() -> Path:
    """人裁事件日志与消费记账 `feedback/{events,consumed}/`、路由表 `routes.yaml`。
    `GUJI_FEEDBACK_DIR` > 工作区 > 仓内。

    09-03 设计把它放在 open-guji-dataset/feedback/，09-13 改归 workspace：事件是
    「这本书」审查过程的账，不是测试集；进测试集要走显式导入。"""
    return _resolve("GUJI_FEEDBACK_DIR", FEEDBACK_REL, data=True)


def verdicts_root() -> Path:
    """人裁**裁决表** `feedback/verdicts/<shard>/items.jsonl`——事件经路由消费后的落点，
    管线回流、面板去重都读这里。`GUJI_VERDICTS_DIR` > 工作区 > 仓内。

    载体与 open-guji-dataset 的金标分片**同一格式**（`gold.store.GoldStore` 直接指过来），
    所以「导入测试集」只是从这里挑一批复制到 dataset 同名分片（`guji gold import`），
    不用转格式。它是事件日志的派生物，丢了可从事件重放（`guji gold rebuild`）。"""
    return _resolve("GUJI_VERDICTS_DIR", VERDICTS_REL, data=True)


def raw_root(override: str | Path | None = None) -> Path:
    """原图根目录。册配置里的 `raw_dir` 相对它解释。"""
    env = os.environ.get("GUJI_RAW_ROOT")
    if env:
        return Path(env).expanduser()
    if override:
        p = Path(override).expanduser()
        return p if p.is_absolute() else (workspace_root() or REPO_ROOT) / p
    return workspace_root() or REPO_ROOT


def corpus_path(name: str) -> Path:
    """整理本语料（`corpus/<name>`）。只有文件名，没有整库那种专属环境变量——
    跟库/图一样走 `workspace_root()`，没设 `GUJI_WORKSPACE` 就退回仓内样本。

    2026-09-11 实锤：`DEFAULT_CORPUS = "corpus/xxx.txt"` 这种硬编码相对路径
    绕过了这整套机制，靠进程 cwd 解析——在 cv 仓根下跑会读到仓内那份过期
    小样本，在 `GUJI_WORKSPACE` 下跑才读到工作区真语料，两边一度分叉 4680 行
    却完全无感知（`align_ref` 锚定失败诊断明明很详细，但没人想到是读错了文件）。
    """
    d = corpus_dir()
    return (d if d is not None else REPO_ROOT / "corpus") / name


def corpus_dir(ws: Path | None = None) -> Path | None:
    """整理本目录 ``corpus/``（见 ``data_root``；2026-10-19 起进中心库，共享方案 2.2 节）。

    迁过的工作区在数据目录；数据目录里还没有、工作区根还留着旧的 ``corpus/``（新版收录范围之前迁的，
    还没 ``guji db migrate`` 补迁）时退回工作区根，免得静默读到仓内小样本。没有工作区返回 None。"""
    ws = ws if ws is not None else workspace_root()
    if ws is None:
        return None
    d = data_root(ws)
    old = Path(ws) / "corpus"
    if d != Path(ws) and not (d / "corpus").is_dir() and old.is_dir():
        return old
    return d / "corpus"


#: 仓内样本语料的量级上限。工作区真语料 275 万字（8.2 MB）、仓内样本各 6000 字
#: （17 KB），中间差两个半数量级，这条线怎么画都不会误判。
SAMPLE_CORPUS_MAX_BYTES = 1_000_000


def using_sample_corpus(name: str = "zongmu_wenyuange_wikisource.txt") -> bool:
    """这次会不会读到「仓内小样本语料」——与 `using_sample_db` 同类的哑失败检测。

    2026-09-12 实锤（Step7 切分裁决那批卡片）：控制台进程没有 `GUJI_WORKSPACE`
    （它只写在 `~/.bashrc` 里，从 PowerShell / VS Code 起就读不到），于是
    `corpus_path()` 静默退回仓内 17 KB 样本，vol02 全书 188 页 8-gram 锚定
    **186 页失败**、`anchored` 页数为 0。面板照常渲染，只是「整理本期望」那两个
    字全是拿样本硬锚出来的噪声——用户看到的现象是「附带信息非常不准确，没法读」，
    过程中没有任何报错。

    `using_sample_db` 只看**路径来源**（环境变量设没设），这里必须看**文件大小**：
    `GUJI_WORKSPACE` 指对了但工作区语料没同步下来、或指到了一个半空的工作区，
    路径来源是"正确"的，读到的仍是小样本。
    """
    p = corpus_path(name)
    try:
        return p.stat().st_size < SAMPLE_CORPUS_MAX_BYTES
    except OSError:
        return True     # 读不到就是不可用，按"不能拿来锚定"处理


def reports_root() -> Path:
    """Step9 汇总产物 `reports/<book>/`——比对报告、体检表。
    `GUJI_REPORTS_DIR` > 工作区 > 仓内。

    **不是页级产物**：它跨页跨册，不属于任何一页，所以不进 `products/`、
    不注册 `ProductKindSpec`（理由同 Step8，见 `feedback/step8.py` 模块头）。
    可再生，不进 git。
    """
    return _resolve("GUJI_REPORTS_DIR", REPORTS_REL)


def describe() -> dict[str, str]:
    """当前解析结果，供控制台与诊断打印——路径错了要看得见。"""
    ws = workspace_root()
    corpus = corpus_path("zongmu_wenyuange_wikisource.txt")
    return {
        "workspace": str(ws) if ws else "(未设 GUJI_WORKSPACE，用仓内默认)",
        "data": str(data_root()) + ("（中心库数据目录）" if central_marker() else "") if ws else "",
        "glyph_db": str(glyph_db_path()),
        "glyph_store": str(glyph_store_path()),
        "raw_root": str(raw_root()),
        "products": str(products_root()),
        "cache": str(cache_root()),
        "batches": str(batches_root()),
        "feedback": str(feedback_root()),
        "verdicts": str(verdicts_root()),
        "reports": str(reports_root()),
        "exclusions": str(exclusions_path()),
        # 语料读错了整理本对齐会静默全空（见 using_sample_corpus），所以摆到台面上
        "corpus": str(corpus) + ("  ⚠️ 仓内小样本，锚不住整理本" if using_sample_corpus() else ""),
    }


def using_sample_db() -> bool:
    """跑批会不会落到「仓内小样本库」这条分支——不看库内容，只看**路径来源**。

    2026-09-09 实锤：`GUJI_WORKSPACE` 没设 → 静默退回 `output/glyph.db`
    （310 条示例记录，不是空库，`assert_db_not_silently_empty` 那道闸认的是
    「空」不认「小」，拦不住）。控制台在本机重启漏带这个变量，vol02 101-150
    页就这样对着示例库跑了一遍，`glyph_match` 全给 `unsure`、`context_decide`
    弃权 80%+、最后连 8-gram 锚定整理本都锚不上——过程里全程 `status: ok`，
    唯一的破绽是产物 `code_rev`/`params_hash` 事后才能翻出来。
    """
    return not (os.environ.get("GUJI_WORKSPACE") or os.environ.get("GUJI_GLYPH_DB"))


def assert_workspace_declared() -> None:
    """跑批前必须显式声明库来源——用仓内小样本库也要**声明**，不能是漏设的默认值。

    `GUJI_ALLOW_SAMPLE_DB=1`（CLI 的 `--allow-sample-db`、控制台跑批表单的
    「允许用本地示例库」都落到这个变量）显式放行；`pytest` 走的是
    `conftest.py`/各测试自己传 `db_path=str(DB)`，不经过这个函数，不受影响。
    """
    if not using_sample_db():
        return
    if os.environ.get("GUJI_ALLOW_SAMPLE_DB") == "1":
        return
    raise RuntimeError(
        "没设 GUJI_WORKSPACE（也没设 GUJI_GLYPH_DB）——这一跑会落到仓内那份"
        f"小样本库（{glyph_db_path()}，几百条，不是你在用的工作区库）。\n"
        "真跑书：export GUJI_WORKSPACE=/path/to/guji-workspace/<id>-<书名>\n"
        "确实想用仓内示例库（本地试跑/开发）：加 --allow-sample-db"
        "（或设 GUJI_ALLOW_SAMPLE_DB=1）显式声明。"
    )


# ── 工作区发现（原在 console/routers/workspace.py，2026-10-27 拆分 M3 搬来：pipeline 的字形库自检也要用）──
def _ws_id(d: Path) -> str:
    """工作区的 id——**URL 上露出来的就是这个**（`/<ws>/<book>/step/...`）。

    默认取目录名去掉 `-workspace` 后缀（`xx-workspace` → `xx`）：短、稳定。
    **`guji-workspace` 那套目录名是 `<book-index id>-<书名>`**，不以 `-workspace`
    结尾，退回来就是一整串中文——那种工作区**必须**放 `workspace.yaml` 写
    `id: 自定义` 覆盖（四庫總目写的是 `siku-zongmu`，与旧仓时期的 URL 一致）。
    """
    import yaml
    f = d / "workspace.yaml"
    if f.is_file():
        try:
            got = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("id")
            if got:
                return str(got)
        except Exception:
            pass                        # 写坏了就退回目录名，不让整个列表挂掉
    name = d.name
    return name[: -len("-workspace")] if name.endswith("-workspace") else name


ROOT_ENV = "GUJI_WORKSPACES_ROOT"


def workspaces_root() -> Path | None:
    """工作区总目录；没配返回 None（此时没有任何工作区可选）。"""
    env = os.environ.get(ROOT_ENV)
    return Path(env).expanduser().resolve() if env else None


def discover_workspaces(current: Path | None = None) -> list[dict]:
    """能切到哪些工作区：总目录下有 `books/` 的子目录。`current` 不给就按本请求解析出来的那个，
    只用来标 `current` 字段，不影响列哪些。"""
    if current is None:
        current = workspace_root()
    root = workspaces_root()
    cands: list[Path] = sorted(d for d in root.iterdir() if d.is_dir()) if root and root.is_dir() else []

    cur_res = current.resolve() if current else None
    out: list[dict] = []
    for d in cands:
        books = books_dir(d)
        if not books.is_dir():
            continue
        ids = sorted(y.stem for y in books.glob("*.yaml"))
        if not ids and d.resolve() != cur_res:
            continue                      # 空工作区不列（当前这个除外，免得自己消失）
        out.append({"id": _ws_id(d), "path": str(d.resolve()), "name": d.name,
                    "books": ids, "current": d.resolve() == cur_res})
    return out


#: 实验分支名，与 Worker ``policy.ts`` 的 EXP_BRANCH_RE、MAX_BRANCH_NAME 一致
EXP_BRANCH_RE = re.compile(r"^exp/GUJI-\d+(?:-[a-z0-9]+)*$")


def is_exp_branch(name: str) -> bool:
    return len(name) <= 63 and bool(EXP_BRANCH_RE.match(name))
