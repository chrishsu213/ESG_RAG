-- ==========================================
-- 新增文件分類與命名欄位
-- ==========================================

-- 1) 新增 category 欄位（分類）
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS category TEXT DEFAULT '其他';

-- 2) 新增 display_name 欄位（自訂顯示名稱）
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS display_name TEXT;
