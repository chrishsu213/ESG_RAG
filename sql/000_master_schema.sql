-- ==========================================
-- TCC RAG 知識庫 — 整合 Master Schema
-- 版本：v4.0（最終版 — 含陣列過濾 + HNSW 修復 + qa_feedback 欄位修正）
-- 最後更新：2026-03-24 16:10
--
-- ==========================================
-- 📌 使用說明
-- ==========================================
-- 【方案 A】全新環境：
--   1. 在 Supabase SQL Editor 直接執行此整份檔案
--   2. 所有表格、索引、RPC 函數會一次建立完成
--
-- 【方案 B】現有環境（修復 RPC 衝突）：
--   1. 直接執行此整份檔案也安全（CREATE TABLE IF NOT EXISTS 不會覆蓋已有資料）
--   2. RPC 函數用 CREATE OR REPLACE，會覆蓋舊版本（這正是修復目的）
--   3. 資料不會被刪除
--
-- ⚠️ 注意：若要從零開始（清空所有資料重建），請先執行：
--   DROP TABLE IF EXISTS document_chunks CASCADE;
--   DROP TABLE IF EXISTS documents CASCADE;
--   DROP TABLE IF EXISTS terms_dictionary CASCADE;
--   DROP TABLE IF EXISTS rag_config CASCADE;
--   DROP TABLE IF EXISTS qa_feedback CASCADE;
--   DROP TABLE IF EXISTS usage_log CASCADE;
--   然後再執行此檔案。
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
    fiscal_period   TEXT        DEFAULT 'Annual',        -- Q1 | Q2 | Q3 | Q4 | Annual
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
CREATE INDEX IF NOT EXISTS idx_documents_fiscal_period   ON documents (fiscal_period);
CREATE INDEX IF NOT EXISTS idx_documents_status          ON documents (status);
CREATE INDEX IF NOT EXISTS idx_documents_confidentiality ON documents (confidentiality);
CREATE INDEX IF NOT EXISTS idx_documents_category        ON documents (category);
CREATE INDEX IF NOT EXISTS idx_documents_tags            ON documents USING gin(tags);

-- ==========================================
-- 2) 子表：document_chunks（含 embedding + FTS + Parent-Child）
-- ==========================================
CREATE TABLE IF NOT EXISTS document_chunks (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id     BIGINT  NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INT     NOT NULL,
    text_content    TEXT    NOT NULL,
    embedding       vector(768),                            -- Gemini embedding (768d)
    metadata        JSONB   DEFAULT '{}'::JSONB,
    chunk_type      TEXT    NOT NULL DEFAULT 'standalone',  -- 'standalone' | 'parent' | 'child'
    parent_chunk_id BIGINT  REFERENCES document_chunks(id) ON DELETE CASCADE,
    fts             tsvector GENERATED ALWAYS AS (
                        to_tsvector('simple', coalesce(text_content, ''))
                    ) STORED,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding   ON document_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_fts         ON document_chunks USING gin(fts);
CREATE INDEX IF NOT EXISTS idx_chunks_parent_id   ON document_chunks(parent_chunk_id);
CREATE INDEX IF NOT EXISTS idx_chunks_chunk_type  ON document_chunks(chunk_type);

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
-- 4) RAG 動態設定表
-- ==========================================
CREATE TABLE IF NOT EXISTS rag_config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    note       TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE rag_config ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow authenticated read rag_config" ON rag_config;
CREATE POLICY "Allow authenticated read rag_config"
    ON rag_config FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Allow service_role full access rag_config" ON rag_config;
CREATE POLICY "Allow service_role full access rag_config"
    ON rag_config FOR ALL TO service_role USING (true);

INSERT INTO rag_config (key, value, note) VALUES
    ('hybrid_threshold',  '0.2',        '混合搜尋相似度門檻（0.1~0.6）'),
    ('top_k_multiplier',  '2',          'hybrid_search 取 top_k × N 倍作為候選池（1~5）'),
    ('sim_weight',        '0.60',       '語義相似度權重（0~1，三個加總需 = 1）'),
    ('year_weight',       '0.25',       '年份新舊權重（0~1）'),
    ('source_weight',     '0.15',       '來源類型權重（0~1）'),
    ('system_prompt',     '{{DEFAULT}}','RAG System Prompt，{{DEFAULT}} 表示使用程式碼預設值')
ON CONFLICT (key) DO NOTHING;

CREATE OR REPLACE FUNCTION update_rag_config_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS rag_config_updated_at ON rag_config;
CREATE TRIGGER rag_config_updated_at
    BEFORE UPDATE ON rag_config
    FOR EACH ROW EXECUTE FUNCTION update_rag_config_timestamp();

-- ==========================================
-- 5) 使用者回饋表
-- ==========================================
CREATE TABLE IF NOT EXISTS qa_feedback (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    question        TEXT    NOT NULL,
    answer          TEXT    NOT NULL,
    rating          TEXT    NOT NULL CHECK (rating IN ('up', 'down')),
    reason          TEXT,                          -- 原始欄位：答非所問 / 資料過時 / 數據錯誤 / 其他
    comment         TEXT,                          -- API 端使用的文字回饋欄位
    session_id      TEXT,                          -- 外部 App 的 Session ID
    source          TEXT    DEFAULT 'api',         -- 來源：admin_ui / api / line_bot / web
    chunk_ids       JSONB   DEFAULT '[]'::jsonb,   -- 搜尋到的 chunk IDs
    search_mode     TEXT,
    fiscal_year     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_qa_feedback_rating  ON qa_feedback (rating);
CREATE INDEX IF NOT EXISTS idx_qa_feedback_created ON qa_feedback (created_at DESC);

-- ℹ️ 既有環境補丁：CREATE TABLE IF NOT EXISTS 不會新增欄位，需用 ALTER
ALTER TABLE qa_feedback ADD COLUMN IF NOT EXISTS comment    TEXT;
ALTER TABLE qa_feedback ADD COLUMN IF NOT EXISTS session_id TEXT;
ALTER TABLE qa_feedback ADD COLUMN IF NOT EXISTS source     TEXT DEFAULT 'api';

-- ==========================================
-- 6) 使用量記錄表
-- ==========================================
CREATE TABLE IF NOT EXISTS usage_log (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL DEFAULT 'unknown',
    question        TEXT,
    model           TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    search_mode     TEXT,
    fiscal_year     TEXT,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_usage_log_created ON usage_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_log_source  ON usage_log (source);

-- ==========================================
-- 7) RPC：純向量搜尋 match_chunks
--    ✅ 雙層 CTE HNSW 修復
--    ✅ Parent-Child 自動替換（child 命中 → 回傳 parent 內容）
--    ✅ 支援 category / group / company / fiscal_year / language 過濾
-- ==========================================
DROP FUNCTION IF EXISTS match_chunks(vector,integer,double precision,text,text,text,text);
DROP FUNCTION IF EXISTS match_chunks(vector,integer,double precision,text,text,text,text,text);

CREATE OR REPLACE FUNCTION match_chunks(
    query_embedding     vector(768),
    match_count         INT     DEFAULT 5,
    match_threshold     FLOAT   DEFAULT 0.3,
    filter_language     TEXT    DEFAULT NULL,
    filter_fiscal_years TEXT[]  DEFAULT NULL,   -- ▲ TEXT[] 支援多年度
    filter_group        TEXT    DEFAULT NULL,
    filter_company      TEXT    DEFAULT NULL,
    filter_categories   TEXT[]  DEFAULT NULL    -- ▲ TEXT[] 支援多分類
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
    parent_chunk_id BIGINT,
    status          TEXT,
    confidentiality TEXT,
    tags            JSONB,
    publish_date    DATE
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  -- 🛡️ 雙層 CTE：Layer 1 觸發 HNSW Index，Layer 2 做候選池去重與 Parent-Child 替換
  WITH top_matches AS (
    SELECT
      c.id, c.document_id, c.chunk_index, c.text_content, c.embedding,
      c.metadata, c.chunk_type, c.parent_chunk_id,
      d.file_name, d.display_name, d.category, d.report_group,
      d."group", d.company, d.fiscal_year, d.language, d.source_type,
      d.status, d.confidentiality, d.tags, d.publish_date
    FROM document_chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE
      c.chunk_type IN ('child', 'standalone')
      AND (filter_language     IS NULL OR d.language    = filter_language)
      AND (filter_fiscal_years IS NULL OR d.fiscal_year = ANY(filter_fiscal_years))
      AND (filter_group        IS NULL OR d."group"     = filter_group)
      AND (filter_company      IS NULL OR d.company     = filter_company)
      AND (filter_categories   IS NULL OR d.category    = ANY(filter_categories))
    -- 🛡️ 嚴格遵循 HNSW 觸發語法：ORDER BY <=> LIMIT
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count * 20
  ),
  -- Layer 2：候選池中做 Parent-Child 替換 + 相似度篩選 + DISTINCT ON 去重
  deduped_results AS (
    SELECT DISTINCT ON (COALESCE(t.parent_chunk_id, t.id))
      t.id, t.document_id, t.chunk_index,
      COALESCE(p.text_content, t.text_content)         AS text_content,
      1 - (t.embedding <=> query_embedding)            AS similarity,
      COALESCE(p.metadata, t.metadata)                 AS metadata,
      t.file_name, t.display_name, t.category, t.report_group,
      t."group", t.company, t.fiscal_year, t.language, t.source_type,
      'vector'::TEXT                                   AS search_type,
      t.chunk_type, t.parent_chunk_id,
      t.status, t.confidentiality, t.tags, t.publish_date
    FROM top_matches t
    LEFT JOIN document_chunks p ON t.parent_chunk_id = p.id
    WHERE (1 - (t.embedding <=> query_embedding)) >= match_threshold
    ORDER BY COALESCE(t.parent_chunk_id, t.id), (1 - (t.embedding <=> query_embedding)) DESC
  )
  SELECT * FROM deduped_results
  ORDER BY similarity DESC
  LIMIT match_count;
END;
$$;

-- ==========================================
-- 8) RPC：混合搜尋 match_chunks_hybrid
--    ✅ 向量 + FTS RRF 融合
--    ✅ 雙層 CTE HNSW 修復
--    ✅ Parent-Child 自動替換
--    ✅ 支援所有維度過濾
-- ==========================================
DROP FUNCTION IF EXISTS match_chunks_hybrid(vector,text,integer,double precision,text,text,text,text);
DROP FUNCTION IF EXISTS match_chunks_hybrid(vector,text,integer,double precision,integer,text,text,text,text,text);
DROP FUNCTION IF EXISTS match_chunks_hybrid(vector,text,integer,double precision,text,text[],text,text,text[]);

CREATE OR REPLACE FUNCTION match_chunks_hybrid(
    query_embedding     vector(768),
    query_text          TEXT,
    match_count         INT     DEFAULT 5,
    match_threshold     FLOAT   DEFAULT 0.2,
    filter_language     TEXT    DEFAULT NULL,
    filter_fiscal_years TEXT[]  DEFAULT NULL,   -- ▲ TEXT[] 支援多年度
    filter_group        TEXT    DEFAULT NULL,
    filter_company      TEXT    DEFAULT NULL,
    filter_categories   TEXT[]  DEFAULT NULL    -- ▲ TEXT[] 支援多分類
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
    parent_chunk_id BIGINT,
    status          TEXT,
    confidentiality TEXT,
    tags            JSONB,
    publish_date    DATE
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_rrf_k INT := 60;
BEGIN
  RETURN QUERY
  WITH
  -- 🛡️ 向量搜尋 CTE（嚴格遵守 HNSW 觸發語法）
  vector_search AS (
    SELECT
      c.id,
      ROW_NUMBER() OVER (ORDER BY c.embedding <=> query_embedding) AS vec_rank
    FROM document_chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE
      c.chunk_type IN ('child', 'standalone')
      -- 🛡️ C-2 修復：移除相似度 WHERE，避免破壞 HNSW Index Scan
      -- 閾值過濾改由 deduped_results CTE（Layer 2）處理
      AND (filter_language     IS NULL OR d.language    = filter_language)
      AND (filter_fiscal_years IS NULL OR d.fiscal_year = ANY(filter_fiscal_years))
      AND (filter_group        IS NULL OR d."group"     = filter_group)
      AND (filter_company      IS NULL OR d.company     = filter_company)
      AND (filter_categories   IS NULL OR d.category    = ANY(filter_categories))
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count * 20
  ),
  -- 全文搜尋 CTE
  fts_search AS (
    SELECT
      c.id,
      ROW_NUMBER() OVER (ORDER BY ts_rank_cd(c.fts, websearch_to_tsquery('simple', query_text)) DESC) AS fts_rank
    FROM document_chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE
      c.chunk_type IN ('child', 'standalone')
      AND c.fts @@ websearch_to_tsquery('simple', query_text)
      AND (filter_language     IS NULL OR d.language    = filter_language)
      AND (filter_fiscal_years IS NULL OR d.fiscal_year = ANY(filter_fiscal_years))
      AND (filter_group        IS NULL OR d."group"     = filter_group)
      AND (filter_company      IS NULL OR d.company     = filter_company)
      AND (filter_categories   IS NULL OR d.category    = ANY(filter_categories))
    ORDER BY ts_rank_cd(c.fts, websearch_to_tsquery('simple', query_text)) DESC
    LIMIT match_count * 20
  ),
  -- RRF 融合分數
  rrf_scores AS (
    SELECT
      COALESCE(v.id, f.id) AS id,
      COALESCE(1.0 / (v_rrf_k + v.vec_rank), 0.0) +
      COALESCE(1.0 / (v_rrf_k + f.fts_rank), 0.0) AS rrf_score
    FROM vector_search v
    FULL OUTER JOIN fts_search f ON v.id = f.id
  ),
  -- 🛡️ Parent-Child 替換 + DISTINCT ON 去重
  deduped_results AS (
    SELECT DISTINCT ON (COALESCE(c.parent_chunk_id, c.id))
      c.id,
      c.document_id,
      c.chunk_index,
      COALESCE(p.text_content, c.text_content)          AS text_content,
      r.rrf_score,
      COALESCE(p.metadata, c.metadata)                  AS metadata,
      d.file_name, d.display_name, d.category, d.report_group,
      d."group", d.company, d.fiscal_year, d.language, d.source_type,
      'hybrid'::TEXT                                    AS search_type,
      c.chunk_type, c.parent_chunk_id,
      d.status, d.confidentiality, d.tags, d.publish_date
    FROM rrf_scores r
    JOIN document_chunks c ON r.id = c.id
    JOIN documents d ON c.document_id = d.id
    LEFT JOIN document_chunks p ON c.parent_chunk_id = p.id
    ORDER BY COALESCE(c.parent_chunk_id, c.id), r.rrf_score DESC
  )
  SELECT
    id, document_id, chunk_index, text_content,
    rrf_score AS similarity,
    metadata, file_name, display_name, category, report_group,
    "group", company, fiscal_year, language, source_type,
    search_type, chunk_type, parent_chunk_id,
    status, confidentiality, tags, publish_date
  FROM deduped_results
  ORDER BY rrf_score DESC
  LIMIT match_count;
END;
$$;
