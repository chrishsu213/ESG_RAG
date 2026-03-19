-- Migration 010: RAG 動態設定表
-- 讓管理員可在後台即時調整搜尋參數與系統 Prompt，無需重新部署

CREATE TABLE IF NOT EXISTS rag_config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    note       TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 啟用 Row Level Security（只有 service_role 可寫）
ALTER TABLE rag_config ENABLE ROW LEVEL SECURITY;

-- 允許所有認證用戶讀取（API 需要讀）
CREATE POLICY "Allow authenticated read rag_config"
    ON rag_config FOR SELECT
    TO authenticated
    USING (true);

-- 只有 service_role 可以寫入
CREATE POLICY "Allow service_role full access rag_config"
    ON rag_config FOR ALL
    TO service_role
    USING (true);

-- 插入預設值
INSERT INTO rag_config (key, value, note) VALUES
    ('hybrid_threshold',  '0.2',   '混合搜尋相似度門檻（0.1~0.6）'),
    ('top_k_multiplier',  '2',     'hybrid_search 取 top_k × N 倍作為候選池（1~5）'),
    ('sim_weight',        '0.60',  '語義相似度權重（0~1，三個加總需 = 1）'),
    ('year_weight',       '0.25',  '年份新舊權重（0~1）'),
    ('source_weight',     '0.15',  '來源類型權重（0~1）'),
    ('system_prompt',     '{{DEFAULT}}', 'RAG System Prompt，{{DEFAULT}} 表示使用程式碼預設值')
ON CONFLICT (key) DO NOTHING;

-- 自動更新 updated_at
CREATE OR REPLACE FUNCTION update_rag_config_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER rag_config_updated_at
    BEFORE UPDATE ON rag_config
    FOR EACH ROW
    EXECUTE FUNCTION update_rag_config_timestamp();
