-- ==========================================
-- Migration 014: 為 RPC 加入 category 篩選支援
-- 最後更新：2026-03-23
-- ==========================================
-- 說明：在 match_chunks 和 match_chunks_hybrid 兩個 RPC function
--       加入 filter_category 參數，讓 API 的 category 篩選真正生效。
-- 執行方式：貼到 Supabase SQL Editor 執行
-- ==========================================

-- 1) 重建 match_chunks：加入 filter_group / filter_company / filter_category
DROP FUNCTION IF EXISTS match_chunks(vector, int, float, text, text);
DROP FUNCTION IF EXISTS match_chunks(vector, int, float, text, text, text, text);

CREATE OR REPLACE FUNCTION match_chunks(
    query_embedding     vector(768),
    match_count         INT   DEFAULT 5,
    match_threshold     FLOAT DEFAULT 0.5,
    filter_language     TEXT  DEFAULT NULL,
    filter_fiscal_year  TEXT  DEFAULT NULL,
    filter_group        TEXT  DEFAULT NULL,
    filter_company      TEXT  DEFAULT NULL,
    filter_category     TEXT  DEFAULT NULL      -- 🆕 新增
)
RETURNS TABLE (
    id              BIGINT,
    document_id     BIGINT,
    chunk_index     INT,
    text_content    TEXT,
    metadata        JSONB,
    file_name       TEXT,
    source_type     TEXT,
    display_name    TEXT,
    report_group    TEXT,
    category        TEXT,
    language        TEXT,
    fiscal_year     TEXT,
    status          TEXT,
    confidentiality TEXT,
    tags            JSONB,
    publish_date    DATE,
    "group"         TEXT,
    company         TEXT,
    similarity      FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        dc.id, dc.document_id, dc.chunk_index,
        dc.text_content, dc.metadata,
        d.file_name, d.source_type,
        d.display_name, d.report_group,
        d.category, d.language, d.fiscal_year,
        d.status, d.confidentiality, d.tags, d.publish_date,
        d."group", d.company,
        1 - (dc.embedding <=> query_embedding) AS similarity
    FROM document_chunks dc
    JOIN documents d ON d.id = dc.document_id
    WHERE dc.embedding IS NOT NULL
      AND 1 - (dc.embedding <=> query_embedding) >= match_threshold
      AND (filter_language    IS NULL OR d.language    = filter_language)
      AND (filter_fiscal_year IS NULL OR d.fiscal_year = filter_fiscal_year)
      AND (filter_group       IS NULL OR d."group"     = filter_group)
      AND (filter_company     IS NULL OR d.company     = filter_company)
      AND (filter_category    IS NULL OR d.category    = filter_category)  -- 🆕
    ORDER BY dc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;


-- 2) 重建 match_chunks_hybrid：加入 filter_group / filter_company / filter_category
DROP FUNCTION IF EXISTS match_chunks_hybrid(vector, text, int, float, int, text, text);
DROP FUNCTION IF EXISTS match_chunks_hybrid(vector, text, int, float, int, text, text, text, text);

CREATE OR REPLACE FUNCTION match_chunks_hybrid(
    query_embedding     vector(768),
    query_text          TEXT,
    match_count         INT   DEFAULT 5,
    match_threshold     FLOAT DEFAULT 0.3,
    rrf_k               INT   DEFAULT 60,
    filter_language     TEXT  DEFAULT NULL,
    filter_fiscal_year  TEXT  DEFAULT NULL,
    filter_group        TEXT  DEFAULT NULL,
    filter_company      TEXT  DEFAULT NULL,
    filter_category     TEXT  DEFAULT NULL      -- 🆕 新增
)
RETURNS TABLE (
    id              BIGINT,
    document_id     BIGINT,
    chunk_index     INT,
    text_content    TEXT,
    metadata        JSONB,
    file_name       TEXT,
    source_type     TEXT,
    display_name    TEXT,
    report_group    TEXT,
    category        TEXT,
    language        TEXT,
    fiscal_year     TEXT,
    status          TEXT,
    confidentiality TEXT,
    tags            JSONB,
    publish_date    DATE,
    "group"         TEXT,
    company         TEXT,
    similarity      FLOAT,
    search_type     TEXT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    WITH
    vector_results AS (
        SELECT
            dc.id, dc.document_id, dc.chunk_index,
            dc.text_content, dc.metadata,
            d.file_name, d.source_type, d.display_name, d.report_group,
            d.category, d.language, d.fiscal_year,
            d.status, d.confidentiality, d.tags, d.publish_date,
            d."group", d.company,
            1 - (dc.embedding <=> query_embedding) AS sim,
            ROW_NUMBER() OVER (ORDER BY dc.embedding <=> query_embedding) AS rank_ix
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE dc.embedding IS NOT NULL
          AND 1 - (dc.embedding <=> query_embedding) >= match_threshold
          AND (filter_language    IS NULL OR d.language    = filter_language)
          AND (filter_fiscal_year IS NULL OR d.fiscal_year = filter_fiscal_year)
          AND (filter_group       IS NULL OR d."group"     = filter_group)
          AND (filter_company     IS NULL OR d.company     = filter_company)
          AND (filter_category    IS NULL OR d.category    = filter_category)  -- 🆕
        ORDER BY dc.embedding <=> query_embedding
        LIMIT match_count * 2
    ),
    fts_results AS (
        SELECT
            dc.id, dc.document_id, dc.chunk_index,
            dc.text_content, dc.metadata,
            d.file_name, d.source_type, d.display_name, d.report_group,
            d.category, d.language, d.fiscal_year,
            d.status, d.confidentiality, d.tags, d.publish_date,
            d."group", d.company,
            ts_rank(dc.fts, websearch_to_tsquery('simple', query_text)) AS sim,
            ROW_NUMBER() OVER (ORDER BY ts_rank(dc.fts, websearch_to_tsquery('simple', query_text)) DESC) AS rank_ix
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE dc.fts @@ websearch_to_tsquery('simple', query_text)
          AND (filter_language    IS NULL OR d.language    = filter_language)
          AND (filter_fiscal_year IS NULL OR d.fiscal_year = filter_fiscal_year)
          AND (filter_group       IS NULL OR d."group"     = filter_group)
          AND (filter_company     IS NULL OR d.company     = filter_company)
          AND (filter_category    IS NULL OR d.category    = filter_category)  -- 🆕
        ORDER BY ts_rank(dc.fts, websearch_to_tsquery('simple', query_text)) DESC
        LIMIT match_count * 2
    ),
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
            COALESCE(v.category, f.category) AS category,
            COALESCE(v.language, f.language) AS language,
            COALESCE(v.fiscal_year, f.fiscal_year) AS fiscal_year,
            COALESCE(v.status, f.status) AS status,
            COALESCE(v.confidentiality, f.confidentiality) AS confidentiality,
            COALESCE(v.tags, f.tags) AS tags,
            COALESCE(v.publish_date, f.publish_date) AS publish_date,
            COALESCE(v."group", f."group") AS "group",
            COALESCE(v.company, f.company) AS company,
            COALESCE(v.sim, 0) AS vector_sim,
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
        c.id, c.document_id, c.chunk_index,
        c.text_content, c.metadata,
        c.file_name, c.source_type, c.display_name, c.report_group,
        c.category, c.language, c.fiscal_year,
        c.status, c.confidentiality, c.tags, c.publish_date,
        c."group", c.company,
        c.vector_sim AS similarity,
        c.search_type
    FROM combined c
    ORDER BY c.rrf_score DESC
    LIMIT match_count;
END;
$$;
