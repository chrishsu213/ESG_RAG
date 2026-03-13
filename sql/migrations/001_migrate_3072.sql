-- ==========================================
-- 修正遷移：將 embedding 欄位設為 vector(768)
-- gemini-embedding-001 透過 output_dimensionality 參數降維至 768
-- 以符合 Supabase HNSW 索引 2000 維度上限
-- ==========================================

-- 1) 刪除舊的 HNSW 索引（如果存在）
DROP INDEX IF EXISTS idx_chunks_embedding;

-- 2) 確保 embedding 欄位為 vector(768)
ALTER TABLE document_chunks
    ALTER COLUMN embedding TYPE vector(768);

-- 3) 重新建立 HNSW 索引 (cosine distance)
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON document_chunks
    USING hnsw (embedding vector_cosine_ops);

-- 4) 更新 match_chunks 函式以接收 768 維查詢向量
CREATE OR REPLACE FUNCTION match_chunks(
    query_embedding vector(768),
    match_count     INT DEFAULT 5,
    match_threshold FLOAT DEFAULT 0.5
)
RETURNS TABLE (
    id            BIGINT,
    document_id   BIGINT,
    chunk_index   INT,
    text_content  TEXT,
    metadata      JSONB,
    file_name     TEXT,
    source_type   TEXT,
    similarity    FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        dc.id,
        dc.document_id,
        dc.chunk_index,
        dc.text_content,
        dc.metadata,
        d.file_name,
        d.source_type,
        1 - (dc.embedding <=> query_embedding) AS similarity
    FROM document_chunks dc
    JOIN documents d ON d.id = dc.document_id
    WHERE dc.embedding IS NOT NULL
      AND 1 - (dc.embedding <=> query_embedding) >= match_threshold
    ORDER BY dc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
