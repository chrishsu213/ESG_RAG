-- ============================================================
-- Migration 012: Parent-Child Chunking 支援
-- 為 document_chunks 加入 parent_chunk_id 與 chunk_type 欄位
--
-- chunk_type 值：
--   'standalone' (預設) — 舊有 chunks，向下相容
--   'parent'            — 大 chunk，保留完整上下文，供 AI 閱讀
--   'child'             — 小 chunk，做 embedding，用於搜尋
-- ============================================================

-- 1. 加入 chunk_type 欄位（舊資料預設 standalone）
ALTER TABLE document_chunks
  ADD COLUMN IF NOT EXISTS chunk_type TEXT NOT NULL DEFAULT 'standalone';

-- 2. 加入 parent_chunk_id 外鍵（child → parent）
ALTER TABLE document_chunks
  ADD COLUMN IF NOT EXISTS parent_chunk_id BIGINT REFERENCES document_chunks(id) ON DELETE CASCADE;

-- 3. 索引
CREATE INDEX IF NOT EXISTS idx_chunks_parent_id  ON document_chunks(parent_chunk_id);
CREATE INDEX IF NOT EXISTS idx_chunks_chunk_type ON document_chunks(chunk_type);

-- 4. 更新 match_chunks RPC：命中 child → 回傳 parent 的 text_content
CREATE OR REPLACE FUNCTION match_chunks(
  query_embedding     vector(768),
  match_count         INT            DEFAULT 5,
  match_threshold     FLOAT          DEFAULT 0.3,
  filter_language     TEXT           DEFAULT NULL,
  filter_fiscal_year  TEXT           DEFAULT NULL,
  filter_group        TEXT           DEFAULT NULL,
  filter_company      TEXT           DEFAULT NULL
)
RETURNS TABLE (
  id              BIGINT,
  document_id     BIGINT,
  chunk_index     INT,
  text_content    TEXT,    -- parent 的 text（若為 child），否則自己的
  similarity      FLOAT,
  metadata        JSONB,
  file_name       TEXT,
  display_name    TEXT,
  category        TEXT,
  report_group    TEXT,
  "group"         TEXT,
  company         TEXT,
  fiscal_year     TEXT,
  language        TEXT,
  source_type     TEXT,
  search_type     TEXT,
  chunk_type      TEXT,
  parent_chunk_id BIGINT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  WITH ranked AS (
    SELECT
      c.id,
      c.document_id,
      c.chunk_index,
      -- 若為 child，取 parent 的 text_content；否則用自己的
      COALESCE(p.text_content, c.text_content)          AS text_content,
      1 - (c.embedding <=> query_embedding)              AS similarity,
      COALESCE(p.metadata, c.metadata)                   AS metadata,
      d.file_name,
      d.display_name,
      d.category,
      d.report_group,
      d."group",
      d.company,
      d.fiscal_year,
      d.language,
      d.source_type,
      'vector'::TEXT                                     AS search_type,
      c.chunk_type,
      c.parent_chunk_id
    FROM document_chunks c
    JOIN documents d ON c.document_id = d.id
    -- LEFT JOIN parent chunk（只有 child 才有 parent_chunk_id）
    LEFT JOIN document_chunks p ON c.parent_chunk_id = p.id
    WHERE
      -- 只搜尋有 embedding 的 chunks（child 或 standalone）
      c.chunk_type IN ('child', 'standalone')
      AND (1 - (c.embedding <=> query_embedding)) >= match_threshold
      AND (filter_language   IS NULL OR d.language    = filter_language)
      AND (filter_fiscal_year IS NULL OR d.fiscal_year = filter_fiscal_year)
      AND (filter_group      IS NULL OR d."group"     = filter_group)
      AND (filter_company    IS NULL OR d.company     = filter_company)
  )
  SELECT *
  FROM ranked
  ORDER BY similarity DESC
  LIMIT match_count;
END;
$$;

-- 5. 更新 match_chunks_hybrid RPC（同樣邏輯）
CREATE OR REPLACE FUNCTION match_chunks_hybrid(
  query_embedding     vector(768),
  query_text          TEXT,
  match_count         INT            DEFAULT 5,
  match_threshold     FLOAT          DEFAULT 0.2,
  filter_language     TEXT           DEFAULT NULL,
  filter_fiscal_year  TEXT           DEFAULT NULL,
  filter_group        TEXT           DEFAULT NULL,
  filter_company      TEXT           DEFAULT NULL
)
RETURNS TABLE (
  id              BIGINT,
  document_id     BIGINT,
  chunk_index     INT,
  text_content    TEXT,
  similarity      FLOAT,
  metadata        JSONB,
  file_name       TEXT,
  display_name    TEXT,
  category        TEXT,
  report_group    TEXT,
  "group"         TEXT,
  company         TEXT,
  fiscal_year     TEXT,
  language        TEXT,
  source_type     TEXT,
  search_type     TEXT,
  chunk_type      TEXT,
  parent_chunk_id BIGINT
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_rrf_k INT := 60;
BEGIN
  RETURN QUERY
  WITH
  -- 向量搜尋（RRF 排名）
  vector_search AS (
    SELECT
      c.id,
      ROW_NUMBER() OVER (ORDER BY c.embedding <=> query_embedding) AS vec_rank
    FROM document_chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE
      c.chunk_type IN ('child', 'standalone')
      AND (1 - (c.embedding <=> query_embedding)) >= match_threshold
      AND (filter_language    IS NULL OR d.language    = filter_language)
      AND (filter_fiscal_year IS NULL OR d.fiscal_year = filter_fiscal_year)
      AND (filter_group       IS NULL OR d."group"     = filter_group)
      AND (filter_company     IS NULL OR d.company     = filter_company)
    LIMIT match_count * 4
  ),
  -- 全文搜尋（RRF 排名）
  fts_search AS (
    SELECT
      c.id,
      ROW_NUMBER() OVER (ORDER BY ts_rank_cd(c.fts, websearch_to_tsquery('simple', query_text)) DESC) AS fts_rank
    FROM document_chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE
      c.chunk_type IN ('child', 'standalone')
      AND c.fts @@ websearch_to_tsquery('simple', query_text)
      AND (filter_language    IS NULL OR d.language    = filter_language)
      AND (filter_fiscal_year IS NULL OR d.fiscal_year = filter_fiscal_year)
      AND (filter_group       IS NULL OR d."group"     = filter_group)
      AND (filter_company     IS NULL OR d.company     = filter_company)
    LIMIT match_count * 4
  ),
  -- RRF 融合分數
  rrf_scores AS (
    SELECT
      COALESCE(v.id, f.id) AS id,
      COALESCE(1.0 / (v_rrf_k + v.vec_rank), 0.0) +
      COALESCE(1.0 / (v_rrf_k + f.fts_rank), 0.0) AS rrf_score
    FROM vector_search v
    FULL OUTER JOIN fts_search f ON v.id = f.id
  )
  SELECT
    c.id,
    c.document_id,
    c.chunk_index,
    COALESCE(p.text_content, c.text_content)          AS text_content,
    r.rrf_score                                        AS similarity,
    COALESCE(p.metadata, c.metadata)                   AS metadata,
    d.file_name,
    d.display_name,
    d.category,
    d.report_group,
    d."group",
    d.company,
    d.fiscal_year,
    d.language,
    d.source_type,
    'hybrid'::TEXT                                     AS search_type,
    c.chunk_type,
    c.parent_chunk_id
  FROM rrf_scores r
  JOIN document_chunks c ON r.id = c.id
  JOIN documents d ON c.document_id = d.id
  LEFT JOIN document_chunks p ON c.parent_chunk_id = p.id
  ORDER BY r.rrf_score DESC
  LIMIT match_count;
END;
$$;
