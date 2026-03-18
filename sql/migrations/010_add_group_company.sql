-- ==========================================
-- Migration 010: 新增 group + company 欄位
-- 支援集團/子公司/同業分類與篩選
-- ==========================================

-- 1) 新增欄位
ALTER TABLE documents ADD COLUMN IF NOT EXISTS "group" TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS company TEXT;

-- 2) 建索引
CREATE INDEX IF NOT EXISTS idx_documents_group   ON documents("group");
CREATE INDEX IF NOT EXISTS idx_documents_company ON documents(company);

-- 3) 回填現有文件
UPDATE documents SET "group" = '台泥企業團', company = '台泥'
WHERE "group" IS NULL;
