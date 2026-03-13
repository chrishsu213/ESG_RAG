-- ==========================================
-- 文件 Metadata 擴展
-- 為 documents 表新增完整管理欄位
-- ==========================================

-- 語言欄位
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'zh-TW';

-- 文件發布日期（非入庫日期）
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS publish_date DATE;

-- 會計年度
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS fiscal_year TEXT;

-- 文件狀態：草稿 / 已審校 / 已發布
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT '已發布';

-- 標籤（JSON Array，例如 ["碳排", "水泥", "ESG"]）
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]'::jsonb;

-- 機密等級：公開 / 內部 / 機密
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS confidentiality TEXT DEFAULT '公開';

-- 最後更新時間
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- 建立索引
CREATE INDEX IF NOT EXISTS idx_documents_language ON documents (language);
CREATE INDEX IF NOT EXISTS idx_documents_fiscal_year ON documents (fiscal_year);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents (status);
CREATE INDEX IF NOT EXISTS idx_documents_confidentiality ON documents (confidentiality);
CREATE INDEX IF NOT EXISTS idx_documents_tags ON documents USING gin(tags);
