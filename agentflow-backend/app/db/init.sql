-- AgentFlow Studio 表结构（按可迁移设计，不用 SQLite 专有语法）
-- 已启用：flows / runs / run_events / settings / tools / tool_invocations / mcp_servers / 知识库 / conversations / chat_turns / agents / 版本表

CREATE TABLE IF NOT EXISTS flows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    -- version = 发布指针：回滚会把它指回历史版本，发布永远按 MAX(version)+1 追加
    version INTEGER NOT NULL DEFAULT 1,
    -- 冗余缓存：草稿指纹 / 发布指纹，列表页判断「是否有未发布改动」
    draft_hash TEXT,
    published_hash TEXT,
    dsl_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    -- v2：flow | agent；target_id 分别对应 flows.id / agents.id
    target_type TEXT NOT NULL DEFAULT 'flow',
    target_id TEXT NOT NULL,
    -- 运行实际对应的发布版本（agent 运行也填），0 表示从未发布
    target_version INTEGER NOT NULL DEFAULT 0,
    -- published = 当前保存内容与发布指针一致；draft = 跑的是未发布改动
    version_mode TEXT NOT NULL DEFAULT 'published',
    -- 运行期版本清单：配置指纹 / Agent 版本 / 工具指纹 / 代码 commit
    manifest_json TEXT,
    status TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    outputs_json TEXT,
    state_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    token_usage INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0.0,
    started_at TEXT,
    finished_at TEXT,
    conversation_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_target ON runs(target_type, target_id, started_at);
CREATE INDEX IF NOT EXISTS idx_runs_conv ON runs(conversation_id);

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
    enabled INTEGER NOT NULL DEFAULT 1,
    -- 整份 ToolDef（含 kind/schema/endpoint/risk/method/headers/body/超时/重试/幂等）都在这里
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
    enabled INTEGER NOT NULL DEFAULT 1,
    -- 整份 MCPServerDef（含 transport/args/env/cwd/timeout）都在这里
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

-- R6 质量体系落地时再按实际指标重建 eval_results / eval_trials

-- R5.1 对话模式：一个会话绑定一个流程；助手回复不单独落表，按 run_id 从 runs 还原
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    flow_id TEXT,
    node_id TEXT,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_scope
    ON conversations(agent_id, flow_id, node_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_turns (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_content TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_turns_conv ON chat_turns(conversation_id, created_at);

-- v2：Agent 是全局资源，整份定义（变量/提示词/资源/模型/输出）存 JSON
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    definition_json TEXT NOT NULL,
    -- published_version 是发布指针；0 表示还没发布过
    published_version INTEGER NOT NULL DEFAULT 0,
    draft_hash TEXT,
    published_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agents_updated ON agents(updated_at DESC);

-- R6.0 版本层：只追加、不可变；草稿层被覆盖不影响这里的快照
CREATE TABLE IF NOT EXISTS agent_versions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    bundle_hash TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    code_commit TEXT,
    code_dirty INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    restored_from INTEGER,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_versions ON agent_versions(agent_id, version);

CREATE TABLE IF NOT EXISTS flow_versions (
    id TEXT PRIMARY KEY,
    flow_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    bundle_hash TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    code_commit TEXT,
    code_dirty INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    restored_from INTEGER,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_versions ON flow_versions(flow_id, version);


