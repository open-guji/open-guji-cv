-- 重跑任务库（2026-10-25）：Neon 中心库的 jobs schema。幂等，可反复执行（guji job init）。
-- 设计见 doc/design/重跑任务库.md。领单用 FOR UPDATE SKIP LOCKED + 租约心跳（PgQueuer、Oban 同法）。
CREATE SCHEMA IF NOT EXISTS jobs;

CREATE TABLE IF NOT EXISTS jobs.meta (
  key   text PRIMARY KEY,
  value text NOT NULL
);

-- 一条任务：定义（spec）、状态、当前进展。spec 一经提交不改。
CREATE TABLE IF NOT EXISTS jobs.job (
  id               bigserial PRIMARY KEY,
  kind             text NOT NULL,
  book             text,
  spec             jsonb NOT NULL,
  spec_hash        text NOT NULL,
  status           text NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'blocked', 'cancelled', 'duplicate')),
  priority         integer NOT NULL DEFAULT 100,
  depends_on       bigint[] NOT NULL DEFAULT '{}',
  duplicate_of     bigint REFERENCES jobs.job (id),
  submitted_by     text NOT NULL,
  why              text,
  stage            text,
  progress         text,
  attempts         integer NOT NULL DEFAULT 0,
  max_attempts     integer NOT NULL DEFAULT 3,
  cancel_requested boolean NOT NULL DEFAULT false,
  error            text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  started_at       timestamptz,
  finished_at      timestamptz,
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS job_queued ON jobs.job (priority, created_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS job_hash ON jobs.job (spec_hash);
CREATE INDEX IF NOT EXISTS job_book ON jobs.job (book, created_at DESC);
-- 同一册同时只跑一条（各会话的产物根、字形库是按册备的，并跑互相踩）。
-- 册号（vol01）每部书都有，所以锁的是（书 ID，册号）；book_id 是 book-index 的 10 位 Book ID（2026-10-30 加，旧行按 ws_glob 补）。
ALTER TABLE jobs.job ADD COLUMN IF NOT EXISTS book_id text;
UPDATE jobs.job SET book_id = split_part(coalesce(spec->>'ws_glob', '96mid1ogzk-*'), '-', 1)
  WHERE book_id IS NULL AND book IS NOT NULL;
CREATE INDEX IF NOT EXISTS job_book_id ON jobs.job (book_id, book, created_at DESC);
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'jobs' AND indexname = 'job_one_running_per_book'
                 AND indexdef LIKE '%book_id%') THEN
    DROP INDEX IF EXISTS jobs.job_one_running_per_book;
    -- coalesce：旧版代码提交的行没有 book_id，仍按册号互斥（保守）
    CREATE UNIQUE INDEX job_one_running_per_book ON jobs.job ((coalesce(book_id, '')), book)
      WHERE status = 'running' AND book IS NOT NULL;
  END IF;
END $$;

-- 每领一次单一条：哪个会话、哪台机、租约到几时。会话死了租约过期，别的执行会话把单收回重排。
CREATE TABLE IF NOT EXISTS jobs.attempt (
  id           bigserial PRIMARY KEY,
  job_id       bigint NOT NULL REFERENCES jobs.job (id) ON DELETE CASCADE,
  n            integer NOT NULL,
  worker       text NOT NULL,
  session      text,
  host         text,
  cv_commit    text,
  started_at   timestamptz NOT NULL DEFAULT now(),
  heartbeat_at timestamptz NOT NULL DEFAULT now(),
  lease_until  timestamptz NOT NULL,
  finished_at  timestamptz,
  outcome      text CHECK (outcome IN ('succeeded', 'failed', 'blocked', 'cancelled', 'lost')),
  exit_code    integer,
  log_tail     text,
  UNIQUE (job_id, n)
);
CREATE INDEX IF NOT EXISTS attempt_live ON jobs.attempt (lease_until) WHERE finished_at IS NULL;

-- 进展流水：每个阶段开始、结束、警告、出错各一行。只追加。
CREATE TABLE IF NOT EXISTS jobs.event (
  id         bigserial PRIMARY KEY,
  job_id     bigint NOT NULL REFERENCES jobs.job (id) ON DELETE CASCADE,
  attempt_id bigint REFERENCES jobs.attempt (id) ON DELETE CASCADE,
  at         timestamptz NOT NULL DEFAULT now(),
  stage      text,
  level      text NOT NULL DEFAULT 'info' CHECK (level IN ('info', 'warn', 'error')),
  msg        text NOT NULL,
  secs       real,
  data       jsonb
);
CREATE INDEX IF NOT EXISTS event_job ON jobs.event (job_id, id);

-- 结果：存了哪个包（R2 前缀）、对比报告、检查数、评测输出。
CREATE TABLE IF NOT EXISTS jobs.result (
  id         bigserial PRIMARY KEY,
  job_id     bigint NOT NULL REFERENCES jobs.job (id) ON DELETE CASCADE,
  attempt_id bigint REFERENCES jobs.attempt (id) ON DELETE SET NULL,
  kind       text NOT NULL CHECK (kind IN ('pack', 'diff', 'check', 'output', 'file')),
  name       text NOT NULL,
  location   text,
  data       jsonb,
  at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS result_job ON jobs.result (job_id);

-- 执行方登记：每个常驻执行方一个名字（GUJI_JOBS_WHO），空闲时也按轮询心跳，谁在线、在跑哪条一眼可见。
CREATE TABLE IF NOT EXISTS jobs.worker (
  name       text PRIMARY KEY,
  session    text,
  host       text,
  runner     text,
  state      text NOT NULL DEFAULT 'idle' CHECK (state IN ('idle', 'busy', 'stopped')),
  job_id     bigint REFERENCES jobs.job (id) ON DELETE SET NULL,
  done       integer NOT NULL DEFAULT 0,
  started_at timestamptz NOT NULL DEFAULT now(),
  seen_at    timestamptz NOT NULL DEFAULT now(),
  note       text
);

-- v3（10-25）：环境类失败退回排队时隔几分钟再领（run_after），免得同一个坏会话几秒内把次数用完
ALTER TABLE jobs.job ADD COLUMN IF NOT EXISTS run_after timestamptz;

INSERT INTO jobs.meta (key, value) VALUES ('schema_version', '3')
  ON CONFLICT (key) DO UPDATE SET value = GREATEST(jobs.meta.value::int, 3)::text;
