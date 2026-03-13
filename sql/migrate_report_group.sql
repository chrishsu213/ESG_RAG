-- 為 documents 表新增 report_group 欄位
-- 用途：將拆分章節的報告書歸為同一群組
ALTER TABLE documents ADD COLUMN IF NOT EXISTS report_group TEXT;

-- 建立索引，方便依群組搜尋
CREATE INDEX IF NOT EXISTS idx_documents_report_group ON documents (report_group);
