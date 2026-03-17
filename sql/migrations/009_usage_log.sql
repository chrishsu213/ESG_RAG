-- 009_usage_log.sql
-- 記錄每次 LLM 呼叫的 token 用量，用於成本追蹤與分析

CREATE TABLE IF NOT EXISTS usage_log (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL DEFAULT 'unknown',  -- 'admin_ui', 'api', 'api_stream'
    question    TEXT,
    model       TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens  INTEGER NOT NULL DEFAULT 0,
    search_mode TEXT,                              -- 'hybrid', 'vector'
    fiscal_year TEXT,
    latency_ms  INTEGER,                          -- 回應耗時（毫秒）
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 按日期查詢的索引
CREATE INDEX IF NOT EXISTS idx_usage_log_created ON usage_log (created_at DESC);
-- 按來源查詢的索引
CREATE INDEX IF NOT EXISTS idx_usage_log_source ON usage_log (source);
