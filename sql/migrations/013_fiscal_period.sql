-- ============================================================
-- Migration 013: 加入 fiscal_period 欄位
-- 用於區分同一年份的不同季度財報
-- 值：Q1 | Q2 | Q3 | Q4 | Annual（預設 Annual）
-- ============================================================

ALTER TABLE document_chunks
  ADD COLUMN IF NOT EXISTS parent_chunk_id BIGINT REFERENCES document_chunks(id) ON DELETE CASCADE;

ALTER TABLE documents
  ADD COLUMN IF NOT EXISTS fiscal_period TEXT DEFAULT 'Annual';

CREATE INDEX IF NOT EXISTS idx_documents_fiscal_period ON documents(fiscal_period);

COMMENT ON COLUMN documents.fiscal_period IS '季度：Q1 | Q2 | Q3 | Q4 | Annual';
