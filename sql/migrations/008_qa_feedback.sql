-- ==========================================
-- Migration 008: 使用者回饋表
-- 最後更新：2026-03-17
-- ==========================================

CREATE TABLE IF NOT EXISTS qa_feedback (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    question        TEXT    NOT NULL,
    answer          TEXT    NOT NULL,
    rating          TEXT    NOT NULL CHECK (rating IN ('up', 'down')),
    reason          TEXT,                          -- 可選：答非所問 / 資料過時 / 數據錯誤 / 其他
    chunk_ids       JSONB   DEFAULT '[]'::jsonb,   -- 搜尋到的 chunk IDs
    search_mode     TEXT,
    fiscal_year     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_qa_feedback_rating ON qa_feedback (rating);
CREATE INDEX IF NOT EXISTS idx_qa_feedback_created ON qa_feedback (created_at DESC);
