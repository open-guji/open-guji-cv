-- 中心库表结构 v1（GUJI-603，设计见 ai-team `通用/中心库设计.md` 第三节）。
--
-- 约定
-- * 可重复执行：全部 IF NOT EXISTS。改表结构就加新的 schema_version 并写迁移，不改旧语句的含义。
-- * 每张从 guji-workspace 镜像来的表都带「来源列」：
--     ws        工作区 id（workspace.yaml 的 id，如 siku-zongmu）
--     src_path  文件在工作区里的相对路径
--     src_line  在该文件中的行号（从 0 起；整文件表为 0）
--     raw       该行原文（不含行尾换行），用来逐行核对哈希、原样导出
--     doc       同一行解析后的 jsonb：只在 workspaces、books、files、anchors、verdicts 上有；
--               events、consumed、字形库各表的字段都已拆成列，要整条记录就 raw::jsonb
--               （首次导入实测：去掉这些表的 doc 省约 55 MB，库从约 260 MB 降到约 200 MB）
--     rev       最后一次写这一行的 changes.rev
-- * changes 每写一行记一条，rev 全局递增；「库版本」= max(changes.rev)。
-- * 图不进库：只存 sha256（内容寻址，图在 R2 `sha256/<前两位>/<sha>.png`）。
-- * 只用 Postgres 14+ 的特性（Neon 默认 16/17，本地验证用 16）。

CREATE TABLE IF NOT EXISTS db_meta (
    key   text PRIMARY KEY,
    value text NOT NULL
);

-- ─── 版本与导入 ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS imports (
    import_id    bigserial PRIMARY KEY,
    source       text NOT NULL,              -- 如 git:open-guji/guji-workspace
    git_commit   text,
    actor        text,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    rev_from     bigint,                     -- 导入前的库版本
    rev_to       bigint,                     -- 导入后的库版本（无变化则等于 rev_from）
    stats        jsonb
);

CREATE TABLE IF NOT EXISTS changes (
    rev        bigserial PRIMARY KEY,
    import_id  bigint REFERENCES imports(import_id),
    at         timestamptz NOT NULL DEFAULT now(),
    tbl        text NOT NULL,
    op         text NOT NULL CHECK (op IN ('insert', 'update', 'delete')),
    ws         text,
    pk         jsonb NOT NULL,                -- 主键数组；整批首导为 {"bulk_rows": n}
    old_sha    text,                         -- 旧内容的 sha256（insert 为空）
    new_sha    text                          -- 新内容的 sha256（delete 为空）
    -- 「内容」= raw；glyph_instances 是 raw || '\n' || patch_sha（只换图也算变更）
);
CREATE INDEX IF NOT EXISTS changes_tbl_ws ON changes (tbl, ws, rev);

-- 镜像过来的每个文件一行：整文件 sha256、行数、末尾有没有换行。
-- 逐行表靠它还原空文件与文件末尾，核对时先比这张表。
CREATE TABLE IF NOT EXISTS source_files (
    ws          text NOT NULL,
    src_path    text NOT NULL,
    tbl         text NOT NULL,                -- 内容落在哪张表
    sha256      text NOT NULL,
    bytes       bigint NOT NULL,
    n_lines     int NOT NULL,                 -- 按 \n 切出的行数（不含末尾换行后的空串）
    final_newline boolean NOT NULL,
    src_line    int NOT NULL DEFAULT 0,
    raw         text NOT NULL,                -- = sha256（变更判断用）
    rev         bigint NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, src_path)
);

-- ─── 登记表 ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workspaces (
    ws          text PRIMARY KEY,
    dir         text NOT NULL,               -- 仓里的目录名（<book-index id>-<书名>）
    src_path    text NOT NULL, src_line int NOT NULL DEFAULT 0,
    raw         text NOT NULL,               -- workspace.yaml 全文
    doc         jsonb,
    rev         bigint NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS books (
    ws          text NOT NULL REFERENCES workspaces(ws),
    book        text NOT NULL,               -- 册 id（books/<book>.yaml）
    title       text,
    edition     text,
    src_path    text NOT NULL, src_line int NOT NULL DEFAULT 0,
    raw         text NOT NULL,               -- 册 yaml 全文
    doc         jsonb,
    rev         bigint NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, book)
);

-- 冻结基线（GUJI-601 的规矩落这里；首次导入不灌，由 close-check / 发布流程写）
CREATE TABLE IF NOT EXISTS freeze_baselines (
    ws          text NOT NULL,
    book        text NOT NULL,
    version     text NOT NULL,               -- 0.1.0 / 1.0.0 …
    cv_version  text,
    cv_commit   text,
    snapshot_id text,
    db_branch   text,
    db_rev      bigint,
    frozen_at   timestamptz NOT NULL DEFAULT now(),
    note        text,
    doc         jsonb,
    PRIMARY KEY (ws, book, version)
);

CREATE TABLE IF NOT EXISTS cv_versions (
    version     text PRIMARY KEY,
    cv_commit   text NOT NULL,
    released_at timestamptz,
    note        text,
    doc         jsonb
);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id text PRIMARY KEY,
    ws          text,
    book        text,
    created_at  timestamptz,
    cv_commit   text,
    db_branch   text,
    db_rev      bigint,
    doc         jsonb
);

-- ─── 人裁与台账（feedback/） ────────────────────────────────────────────
-- 事件：feedback/events/*.jsonl（stream=events）与 feedback/vision/*.jsonl（stream=vision）。
-- 主键带 src_path：现有数据里有同一 id 出现在两个文件、内容不同的情况（见导入报告），
-- 不能静默合并。
CREATE TABLE IF NOT EXISTS events (
    ws          text NOT NULL REFERENCES workspaces(ws),
    src_path    text NOT NULL,
    id          text NOT NULL,
    stream      text NOT NULL,
    book        text,                         -- target.book
    batch       text,
    seq         int,
    kind        text,
    actor       text,
    reviewer    text,
    ts          text,                         -- 原样保留（格式不统一）
    payload     jsonb,
    target      jsonb,
    src_line    int NOT NULL,
    raw         text NOT NULL,
    rev         bigint NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, src_path, id)
);
CREATE INDEX IF NOT EXISTS events_ws_id    ON events (ws, id);
CREATE INDEX IF NOT EXISTS events_ws_book  ON events (ws, book);
CREATE INDEX IF NOT EXISTS events_ws_batch ON events (ws, batch);

-- 消费者台账：feedback/consumed/<consumer>.jsonl。同一事件被同一消费者记过两次的行
-- 现有数据里就有（含整行重复），所以主键用行号，不用 (consumer, event)。
CREATE TABLE IF NOT EXISTS consumed (
    ws          text NOT NULL REFERENCES workspaces(ws),
    consumer    text NOT NULL,
    src_line    int NOT NULL,
    event       text,
    ts          text,
    note        text,
    src_path    text NOT NULL,
    raw         text NOT NULL,
    rev         bigint NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, consumer, src_line)
);
CREATE INDEX IF NOT EXISTS consumed_event ON consumed (ws, consumer, event);

CREATE TABLE IF NOT EXISTS anchors (
    ws          text NOT NULL REFERENCES workspaces(ws),
    src_path    text NOT NULL,                -- feedback/anchors/<book>.jsonl
    event       text NOT NULL,
    key         text NOT NULL,                -- 格键 vol03:3:1:1
    book        text,
    src_line    int NOT NULL,
    raw         text NOT NULL,
    doc         jsonb NOT NULL,
    rev         bigint NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, src_path, event, key)
);

-- 锚图本身进 R2，这里只记 sha
CREATE TABLE IF NOT EXISTS anchor_patches_meta (
    ws          text NOT NULL REFERENCES workspaces(ws),
    src_path    text NOT NULL,                -- feedback/anchor_patches/<book>/<name>.png
    sha256      text NOT NULL,
    bytes       int NOT NULL,
    src_line    int NOT NULL DEFAULT 0,
    raw         text NOT NULL,                -- = sha256（核对与变更判断用）
    rev         bigint NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, src_path)
);

-- 整理本（corpus/**，共享方案 2.2 节）：文本进 R2（键后缀 .txt），这里只记 sha，同锚图
CREATE TABLE IF NOT EXISTS corpus_files (
    ws          text NOT NULL REFERENCES workspaces(ws),
    src_path    text NOT NULL,                -- corpus/<name>.txt、corpus/daizhige/…
    sha256      text NOT NULL,
    bytes       int NOT NULL,
    src_line    int NOT NULL DEFAULT 0,
    raw         text NOT NULL,                -- = sha256（核对与变更判断用）
    rev         bigint NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, src_path)
);

-- 金标信封：feedback/verdicts/<task>/<file>.jsonl，原样进 doc
CREATE TABLE IF NOT EXISTS verdicts (
    ws           text NOT NULL REFERENCES workspaces(ws),
    src_path     text NOT NULL,
    id           text NOT NULL,
    task         text NOT NULL,               -- verdicts/ 下的目录，如 border-detection/bottom-offset
    status       text,
    label_origin text,
    src_line     int NOT NULL,
    raw          text NOT NULL,
    doc          jsonb NOT NULL,
    rev          bigint NOT NULL,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, src_path, id)
);

-- 整文件表：待审名单（feedback/lists）、审阅批次（review/batches）、排除名单等配置（config/）、其他小文件。
-- 按文件整存，raw = 文件全文。
CREATE TABLE IF NOT EXISTS files (
    ws          text NOT NULL REFERENCES workspaces(ws),
    src_path    text NOT NULL,
    kind        text NOT NULL,                -- list / batch / config / feedback_misc / glyph_misc
    sha256      text NOT NULL,
    bytes       int NOT NULL,
    src_line    int NOT NULL DEFAULT 0,
    raw         text NOT NULL,
    doc         jsonb,                        -- .json 文件解析后的内容；其他为空
    rev         bigint NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, src_path)
);
CREATE OR REPLACE VIEW lists   AS SELECT * FROM files WHERE kind = 'list';
CREATE OR REPLACE VIEW batches AS SELECT * FROM files WHERE kind = 'batch';

-- ─── 字形库（output/glyph_store/，照搬 clustering/glyph_db.py 的表） ────
-- 区别：按工作区分（ws 进主键）；instances.patch_png 改为 patch_sha；
-- kind='font' 的来源本来就不导出，这里也不进。
CREATE TABLE IF NOT EXISTS glyph_sources (
    ws text NOT NULL REFERENCES workspaces(ws),
    source_id text NOT NULL,
    collection text, title text, volume text,
    edition_tag text NOT NULL,
    script_style text, era text,
    cols_per_page int, chars_per_col int,
    pipeline_version text, notes text,
    kind text NOT NULL DEFAULT 'woodblock',
    created_at text NOT NULL,
    src_path text NOT NULL, src_line int NOT NULL, raw text NOT NULL,
    rev bigint NOT NULL, ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, source_id)
);

CREATE TABLE IF NOT EXISTS glyph_instances (
    ws text NOT NULL REFERENCES workspaces(ws),
    instance_id text NOT NULL,
    source_id text NOT NULL,
    page text NOT NULL, col int NOT NULL, idx int NOT NULL,
    bbox text,
    patch_sha text,                               -- 刻例图 sha256；图在 R2
    patch_bytes int,
    ink_ratio double precision, width double precision, height double precision,
    quality_flags text,
    label text, label_status text, label_confidence double precision,
    semantic text, unicode_cp int, ids text,
    fidelity text, fidelity_by text,
    updated_at text NOT NULL,
    src_path text NOT NULL, src_line int NOT NULL, raw text NOT NULL,
    rev bigint NOT NULL, ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, instance_id)
);
CREATE INDEX IF NOT EXISTS glyph_instances_label ON glyph_instances (ws, label) WHERE label IS NOT NULL;
CREATE INDEX IF NOT EXISTS glyph_instances_sha   ON glyph_instances (patch_sha);

CREATE TABLE IF NOT EXISTS glyphs (
    ws text NOT NULL REFERENCES workspaces(ws),
    edition_tag text NOT NULL,
    char text NOT NULL,
    semantic text, unicode_cp int, ids text,
    status text NOT NULL DEFAULT 'sparse',
    n_confirmed int NOT NULL DEFAULT 0,
    updated_at text NOT NULL,
    src_path text NOT NULL, src_line int NOT NULL, raw text NOT NULL,
    rev bigint NOT NULL, ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, edition_tag, char)
);

CREATE TABLE IF NOT EXISTS glyph_exemplars (
    ws text NOT NULL REFERENCES workspaces(ws),
    edition_tag text NOT NULL,
    char text NOT NULL,
    instance_id text NOT NULL,
    role text NOT NULL,
    added_at text NOT NULL,
    src_path text NOT NULL, src_line int NOT NULL, raw text NOT NULL,
    rev bigint NOT NULL, ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, edition_tag, char, instance_id)
);

CREATE TABLE IF NOT EXISTS glyph_admissions (
    ws text NOT NULL REFERENCES workspaces(ws),
    instance_id text NOT NULL,
    char text NOT NULL,
    provenance text NOT NULL,
    evidence text,
    admitted_at text NOT NULL,
    src_path text NOT NULL, src_line int NOT NULL, raw text NOT NULL,
    rev bigint NOT NULL, ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, instance_id)
);

CREATE TABLE IF NOT EXISTS glyph_evictions (
    ws text NOT NULL REFERENCES workspaces(ws),
    instance_id text NOT NULL,
    char text, reason text,
    at text NOT NULL,
    src_path text NOT NULL, src_line int NOT NULL, raw text NOT NULL,
    rev bigint NOT NULL, ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, instance_id, at)
);

CREATE TABLE IF NOT EXISTS glyph_approx_labels (
    ws text NOT NULL REFERENCES workspaces(ws),
    instance_id text NOT NULL,
    label text NOT NULL,
    ids text, note text, reviewer text,
    created_at text NOT NULL,
    src_path text NOT NULL, src_line int NOT NULL, raw text NOT NULL,
    rev bigint NOT NULL, ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, instance_id)
);

CREATE TABLE IF NOT EXISTS glyph_approx_clears (
    ws text NOT NULL REFERENCES workspaces(ws),
    instance_id text NOT NULL,
    label text,
    at text NOT NULL,
    src_path text NOT NULL, src_line int NOT NULL, raw text NOT NULL,
    rev bigint NOT NULL, ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, instance_id, at)
);

CREATE TABLE IF NOT EXISTS glyph_pairs (
    ws text NOT NULL REFERENCES workspaces(ws),
    inst_a text NOT NULL, inst_b text NOT NULL,
    relation text NOT NULL,
    origin text NOT NULL,
    source_id text,
    created_at text NOT NULL,
    src_path text NOT NULL, src_line int NOT NULL, raw text NOT NULL,
    rev bigint NOT NULL, ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, inst_a, inst_b, relation)
);

CREATE TABLE IF NOT EXISTS glyph_meta (
    ws text NOT NULL REFERENCES workspaces(ws),
    key text NOT NULL,
    value text,
    src_path text NOT NULL, src_line int NOT NULL, raw text NOT NULL,
    rev bigint NOT NULL, ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, key)
);

-- glyph_store/events/<source>.jsonl（生产库里目前全空，表照建）
CREATE TABLE IF NOT EXISTS glyph_events (
    ws text NOT NULL REFERENCES workspaces(ws),
    src_path text NOT NULL,
    src_line int NOT NULL,
    source_id text, batch text, seq int, ts text, op text, payload text,
    raw text NOT NULL,
    rev bigint NOT NULL, ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ws, src_path, src_line)
);

INSERT INTO db_meta (key, value) VALUES ('schema_version', '1')
    ON CONFLICT (key) DO NOTHING;
