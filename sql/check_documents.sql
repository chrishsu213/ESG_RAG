-- ==========================================
-- V2: 強制更新所有 documents 的 display_name 和 report_group
-- 在 Supabase SQL Editor 中執行
-- ==========================================

-- 先看看現在的狀態
SELECT id, file_name, source_type, category, display_name, report_group
FROM documents
WHERE source_type = 'pdf'
ORDER BY id;
