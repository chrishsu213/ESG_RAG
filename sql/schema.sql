-- ==========================================
-- TCC RAG 知識庫 — 完整資料庫 Schema
-- 最後更新：2026-03-13
--
-- 新環境部署：在 Supabase SQL Editor 執行此檔即可
-- ==========================================

-- 0) 啟用 pgvector 擴充
CREATE EXTENSION IF NOT EXISTS vector;

-- ==========================================
-- 1) 主表：documents
-- ==========================================
CREATE TABLE IF NOT EXISTS documents (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_name       TEXT        NOT NULL,
    file_hash       TEXT        NOT NULL UNIQUE,       -- SHA-256 (檔案) 或 URL (網頁)
    source_type     TEXT        NOT NULL,               -- 'pdf' | 'docx' | 'url' | 'audio'
    -- 分類與命名
    category        TEXT        DEFAULT '其他',          -- 網站 | 永續報告書 | 年度報告 | 財務報告 | 公司政策 | 會議紀錄 | 法說會 | 其他
    display_name    TEXT,                                -- 使用者自訂顯示名稱
    report_group    TEXT,                                -- 歸屬報告群組
    -- 集團 / 子公司
    "group"         TEXT,                                -- 集團（台泥企業團 | 亞泥 | 中鋼）
    company         TEXT,                                -- 子公司（台泥 | 台泥儲能 | NHOA）
    -- Metadata
    language        TEXT        DEFAULT 'zh-TW',         -- zh-TW | en | ja | zh-CN
    publish_date    DATE,                                -- 文件發布日期
    fiscal_year     TEXT,                                -- 會計年度（如 2024, 113）
    status          TEXT        DEFAULT '已發布',         -- 草稿 | 已審校 | 已發布
    tags            JSONB       DEFAULT '[]'::jsonb,     -- 標籤 ["碳排", "水泥"]
    confidentiality TEXT        DEFAULT '公開',           -- 公開 | 內部 | 機密
    -- 時間戳
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_report_group    ON documents (report_group);
CREATE INDEX IF NOT EXISTS idx_documents_group           ON documents ("group");
CREATE INDEX IF NOT EXISTS idx_documents_company         ON documents (company);
CREATE INDEX IF NOT EXISTS idx_documents_language        ON documents (language);
CREATE INDEX IF NOT EXISTS idx_documents_fiscal_year     ON documents (fiscal_year);
CREATE INDEX IF NOT EXISTS idx_documents_status          ON documents (status);
CREATE INDEX IF NOT EXISTS idx_documents_confidentiality ON documents (confidentiality);
CREATE INDEX IF NOT EXISTS idx_documents_tags            ON documents USING gin(tags);

-- ==========================================
-- 2) 子表：document_chunks（含 embedding + FTS）
-- ==========================================
CREATE TABLE IF NOT EXISTS document_chunks (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id   BIGINT  NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index   INT     NOT NULL,
    text_content  TEXT    NOT NULL,
    embedding     vector(768),                            -- Gemini embedding (768d)
    metadata      JSONB   DEFAULT '{}'::JSONB,
    fts           tsvector GENERATED ALWAYS AS (
                      to_tsvector('simple', coalesce(text_content, ''))
                  ) STORED,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding   ON document_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_fts         ON document_chunks USING gin(fts);

-- ==========================================
-- 3) 專有名詞字典表
-- ==========================================
CREATE TABLE IF NOT EXISTS terms_dictionary (
    id          BIGSERIAL PRIMARY KEY,
    term        TEXT NOT NULL UNIQUE,
    full_name   TEXT NOT NULL,
    category    TEXT DEFAULT '一般',       -- 一般 | 人名 | 組織 | 技術
    language    TEXT DEFAULT 'zh-TW',
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_terms_term     ON terms_dictionary (term);
CREATE INDEX IF NOT EXISTS idx_terms_category ON terms_dictionary (category);

-- 預設 ESG 常用詞彙
INSERT INTO terms_dictionary (term, full_name, category) VALUES
    ('TCC',     '台泥集團 (TCC Group)',                        '組織'),
    ('DAKA',    '台泥DAKA再生資源處理中心',                      '組織'),
    ('SBT',     '科學基礎減碳目標 (Science Based Targets)',      '技術'),
    ('SBTi',    '科學基礎減碳目標倡議組織 (SBTi)',                '組織'),
    ('TCFD',    '氣候相關財務揭露 (TCFD)',                        '技術'),
    ('ISSB',    '國際永續準則理事會 (ISSB)',                      '組織'),
    ('ESG',     '環境、社會與治理 (ESG)',                         '技術'),
    ('CSRD',    '企業永續報告指令 (CSRD)',                        '技術'),
    ('RE100',   '再生能源100% (RE100)',                          '技術'),
    ('CBAM',    '碳邊境調整機制 (CBAM)',                          '技術'),
    ('GRI',     '全球報告倡議組織 (GRI)',                         '組織'),
    ('CDP',     '碳揭露計畫 (CDP)',                              '組織'),
    ('EBITDA',  '稅息折舊及攤銷前利潤 (EBITDA)',                  '技術')
ON CONFLICT (term) DO NOTHING;

-- ==========================================
-- 4) RPC：純向量搜尋（支援語言篩選）
-- ==========================================
CREATE OR REPLACE FUNCTION match_chunks(
    query_embedding     vector(768),
    match_count         INT   DEFAULT 5,
    match_threshold     FLOAT DEFAULT 0.5,
    filter_language     TEXT  DEFAULT NULL,
    filter_fiscal_year  TEXT  DEFAULT NULL,
    filter_group        TEXT  DEFAULT NULL,
    filter_company      TEXT  DEFAULT NULL
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
    "group"         TEXT,
    company         TEXT,
    category        TEXT,
    language        TEXT,
    fiscal_year     TEXT,
    status          TEXT,
    confidentiality TEXT,
    tags            JSONB,
    publish_date    DATE,
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
        d."group", d.company,
        d.category, d.language, d.fiscal_year,
        d.status, d.confidentiality, d.tags, d.publish_date,
        1 - (dc.embedding <=> query_embedding) AS similarity
    FROM document_chunks dc
    JOIN documents d ON d.id = dc.document_id
    WHERE dc.embedding IS NOT NULL
      AND 1 - (dc.embedding <=> query_embedding) >= match_threshold
      AND (filter_language IS NULL OR d.language = filter_language)
      AND (filter_fiscal_year IS NULL OR d.fiscal_year = filter_fiscal_year)
      AND (filter_group IS NULL OR d."group" = filter_group)
      AND (filter_company IS NULL OR d.company = filter_company)
    ORDER BY dc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ==========================================
-- 5) RPC：混合搜尋 (Vector + FTS + RRF)（支援語言篩選）
-- ==========================================
CREATE OR REPLACE FUNCTION match_chunks_hybrid(
    query_embedding     vector(768),
    query_text          TEXT,
    match_count         INT   DEFAULT 5,
    match_threshold     FLOAT DEFAULT 0.3,
    rrf_k               INT   DEFAULT 60,
    filter_language     TEXT  DEFAULT NULL,
    filter_fiscal_year  TEXT  DEFAULT NULL,
    filter_group        TEXT  DEFAULT NULL,
    filter_company      TEXT  DEFAULT NULL
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
    "group"         TEXT,
    company         TEXT,
    category        TEXT,
    language        TEXT,
    fiscal_year     TEXT,
    status          TEXT,
    confidentiality TEXT,
    tags            JSONB,
    publish_date    DATE,
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
            d."group", d.company,
            d.category, d.language, d.fiscal_year,
            d.status, d.confidentiality, d.tags, d.publish_date,
            1 - (dc.embedding <=> query_embedding) AS sim,
            ROW_NUMBER() OVER (ORDER BY dc.embedding <=> query_embedding) AS rank_ix
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE dc.embedding IS NOT NULL
          AND 1 - (dc.embedding <=> query_embedding) >= match_threshold
          AND (filter_language IS NULL OR d.language = filter_language)
          AND (filter_fiscal_year IS NULL OR d.fiscal_year = filter_fiscal_year)
          AND (filter_group IS NULL OR d."group" = filter_group)
          AND (filter_company IS NULL OR d.company = filter_company)
        ORDER BY dc.embedding <=> query_embedding
        LIMIT match_count * 2
    ),
    fts_results AS (
        SELECT
            dc.id, dc.document_id, dc.chunk_index,
            dc.text_content, dc.metadata,
            d.file_name, d.source_type, d.display_name, d.report_group,
            d."group", d.company,
            d.category, d.language, d.fiscal_year,
            d.status, d.confidentiality, d.tags, d.publish_date,
            ts_rank(dc.fts, websearch_to_tsquery('simple', query_text)) AS sim,
            ROW_NUMBER() OVER (ORDER BY ts_rank(dc.fts, websearch_to_tsquery('simple', query_text)) DESC) AS rank_ix
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE dc.fts @@ websearch_to_tsquery('simple', query_text)
          AND (filter_language IS NULL OR d.language = filter_language)
          AND (filter_fiscal_year IS NULL OR d.fiscal_year = filter_fiscal_year)
          AND (filter_group IS NULL OR d."group" = filter_group)
          AND (filter_company IS NULL OR d.company = filter_company)
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
            COALESCE(v."group", f."group") AS "group",
            COALESCE(v.company, f.company) AS company,
            COALESCE(v.category, f.category) AS category,
            COALESCE(v.language, f.language) AS language,
            COALESCE(v.fiscal_year, f.fiscal_year) AS fiscal_year,
            COALESCE(v.status, f.status) AS status,
            COALESCE(v.confidentiality, f.confidentiality) AS confidentiality,
            COALESCE(v.tags, f.tags) AS tags,
            COALESCE(v.publish_date, f.publish_date) AS publish_date,
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
        c."group", c.company,
        c.category, c.language, c.fiscal_year,
        c.status, c.confidentiality, c.tags, c.publish_date,
        c.vector_sim AS similarity,
        c.search_type
    FROM combined c
    ORDER BY c.rrf_score DESC
    LIMIT match_count;
END;
$$;
