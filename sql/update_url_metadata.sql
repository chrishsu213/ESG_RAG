-- ==========================================
-- 更新 URL 文件的 report_group（從 category 複製）
-- 和 display_name（精簡 URL 路徑）
-- 在 Supabase SQL Editor 中執行
-- ==========================================

-- 1) URL 文件：report_group = category
UPDATE documents
SET report_group = category
WHERE source_type = 'url'
  AND (report_group IS NULL OR report_group = '');

-- 2) URL 文件：display_name = 精簡 URL 路徑
UPDATE documents
SET display_name = regexp_replace(
    regexp_replace(file_name, '^https?://[^/]+/', ''),
    '[?#].*$', ''
)
WHERE source_type = 'url'
  AND (display_name IS NULL OR display_name = '');

-- 3) 驗證結果
SELECT report_group, count(*), 
       min(display_name) AS example_display
FROM documents
GROUP BY report_group
ORDER BY count(*) DESC;
