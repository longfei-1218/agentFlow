-- AgentFlow Studio 表结构（10 张表，按可迁移设计，不用 SQLite 专有语法）
-- 已启用：flows / runs / run_events / settings / tools / tool_invocations；其余表先建好，避免后续迁移。

CREATE TABLE IF NOT EXISTS flows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    dsl_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    flow_id TEXT NOT NULL,
    flow_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    outputs_json TEXT,
    state_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    token_usage INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0.0,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY (flow_id) REFERENCES flows(id)
);

CREATE INDEX IF NOT EXISTS idx_runs_flow ON runs(flow_id, started_at);

CREATE TABLE IF NOT EXISTS run_events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    node_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq),
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tools (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    schema_json TEXT NOT NULL,
    endpoint TEXT,
    risk TEXT NOT NULL DEFAULT 'low',
    enabled INTEGER NOT NULL DEFAULT 1,
    -- 整份 ToolDef（含 method/headers/body/超时/重试/幂等）都在这里，上面几列只是便于筛选的冗余
    definition_json TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS tool_invocations (
    id TEXT PRIMARY KEY,
    tool_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    run_id TEXT,
    node_id TEXT,
    args_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    http_status INTEGER,
    result_json TEXT,
    error TEXT,
    idem_key TEXT,
    idem_hit INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inv_tool ON tool_invocations(tool_id, created_at);
CREATE INDEX IF NOT EXISTS idx_inv_idem ON tool_invocations(idem_key, created_at);

CREATE TABLE IF NOT EXISTS mcp_servers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    transport TEXT NOT NULL,
    command_or_url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    -- 整份 MCPServerDef（含 args/env/cwd/timeout）在这里，上面几列只是列表页冗余
    definition_json TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    collection TEXT NOT NULL UNIQUE,
    chunk_size INTEGER NOT NULL DEFAULT 400,
    overlap INTEGER NOT NULL DEFAULT 50,
    embedding_model TEXT NOT NULL DEFAULT 'bm25-local',
    doc_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS kb_documents (
    id TEXT PRIMARY KEY,
    kb_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id)
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id TEXT PRIMARY KEY,
    kb_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (doc_id) REFERENCES kb_documents(id)
);

CREATE INDEX IF NOT EXISTS idx_chunks_kb ON kb_chunks(kb_id);

CREATE TABLE IF NOT EXISTS eval_sets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cases_json TEXT NOT NULL,
    rubric_version TEXT NOT NULL DEFAULT 'v1',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_results (
    id TEXT PRIMARY KEY,
    set_id TEXT NOT NULL,
    flow_version INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (set_id) REFERENCES eval_sets(id)
);

CREATE TABLE IF NOT EXISTS eval_trials (
    result_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    trial INTEGER NOT NULL,
    outcome_ok INTEGER NOT NULL,
    tool_ok INTEGER NOT NULL,
    judge_score REAL,
    steps INTEGER NOT NULL,
    tokens INTEGER NOT NULL,
    cost REAL NOT NULL,
    trace_ref TEXT,
    PRIMARY KEY (result_id, case_id, trial),
    FOREIGN KEY (result_id) REFERENCES eval_results(id)
);
