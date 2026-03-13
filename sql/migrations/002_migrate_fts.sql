-- ==========================================
-- 全文搜尋 (FTS) 支援 + 混合搜尋 RPC
-- ==========================================

-- 1) 新增 tsvector 欄位，支援中英文全文搜尋
ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS fts tsvector
    GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(text_content, ''))
    ) STORED;

-- 2) 建立 GIN 索引加速全文搜尋
CREATE INDEX IF NOT EXISTS idx_chunks_fts ON document_chunks USING gin(fts);

-- 3) 混合搜尋 function：向量 + 全文，使用 RRF (Reciprocal Rank Fusion) 合併
CREATE OR REPLACE FUNCTION match_chunks_hybrid(
    query_embedding vector(768),
    query_text      TEXT,
    match_count     INT DEFAULT 5,
    match_threshold FLOAT DEFAULT 0.3,
    rrf_k           INT DEFAULT 60
)
RETURNS TABLE (
    id            BIGINT,
    document_id   BIGINT,
    chunk_index   INT,
    text_content  TEXT,
    metadata      JSONB,
    file_name     TEXT,
    source_type   TEXT,
    display_name  TEXT,
    report_group  TEXT,
    similarity    FLOAT,
    search_type   TEXT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY

    WITH
    -- 向量搜尋 Top N
    vector_results AS (
        SELECT
            dc.id,
            dc.document_id,
            dc.chunk_index,
            dc.text_content,
            dc.metadata,
            d.file_name,
            d.source_type,
            d.display_name,
            d.report_group,
            1 - (dc.embedding <=> query_embedding) AS sim,
            ROW_NUMBER() OVER (ORDER BY dc.embedding <=> query_embedding) AS rank_ix
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE dc.embedding IS NOT NULL
          AND 1 - (dc.embedding <=> query_embedding) >= match_threshold
        ORDER BY dc.embedding <=> query_embedding
        LIMIT match_count * 2
    ),
    -- 全文搜尋 Top N
    fts_results AS (
        SELECT
            dc.id,
            dc.document_id,
            dc.chunk_index,
            dc.text_content,
            dc.metadata,
            d.file_name,
            d.source_type,
            d.display_name,
            d.report_group,
            ts_rank(dc.fts, websearch_to_tsquery('simple', query_text)) AS sim,
            ROW_NUMBER() OVER (ORDER BY ts_rank(dc.fts, websearch_to_tsquery('simple', query_text)) DESC) AS rank_ix
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE dc.fts @@ websearch_to_tsquery('simple', query_text)
        ORDER BY ts_rank(dc.fts, websearch_to_tsquery('simple', query_text)) DESC
        LIMIT match_count * 2
    ),
    -- RRF 合併排序
    combined AS (
        SELECT
            COALESCE(v.id, f.id) AS id,
            COALESCE(v.document_id, f.document_id) AS document_id,
            COALESCE(v.chunk_index, f.chunk_index) AS chunk_index,
            COALESCE(v.text_content, f.text_content) AS text_content,
            COALESCE(v.metadata, f.metadata) AS metadata,
            COALESCE(v.file_name, f.file_name) AS file_name,
            COALESCE(v.source_type, f.source_type) AS source_type,
            COALESCE(v.display_name, f.display_name) AS display_name,
            COALESCE(v.report_group, f.report_group) AS report_group,
            COALESCE(v.sim, 0) AS vector_sim,
            -- RRF score
            COALESCE(1.0 / (rrf_k + v.rank_ix), 0) +
            COALESCE(1.0 / (rrf_k + f.rank_ix), 0) AS rrf_score,
            CASE
                WHEN v.id IS NOT NULL AND f.id IS NOT NULL THEN 'hybrid'
                WHEN v.id IS NOT NULL THEN 'vector'
                ELSE 'fulltext'
            END AS search_type
        FROM vector_results v
        FULL OUTER JOIN fts_results f ON v.id = f.id
    )
    SELECT
        c.id,
        c.document_id,
        c.chunk_index,
        c.text_content,
        c.metadata,
        c.file_name,
        c.source_type,
        c.display_name,
        c.report_group,
        c.vector_sim AS similarity,
        c.search_type
    FROM combined c
    ORDER BY c.rrf_score DESC
    LIMIT match_count;

END;
$$;
