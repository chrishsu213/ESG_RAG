-- ==========================================
-- 批次更新 documents 表的 display_name 和 report_group
-- 在 Supabase SQL Editor 中執行
-- ==========================================

-- 1) PDF 文件：根據 file_name 自動設定 display_name 和 report_group
-- 永續報告書
UPDATE documents
SET display_name = CASE
        WHEN file_name ILIKE '%2024%永續%' OR file_name ILIKE '%2024%sustain%' THEN '台泥2024永續報告書'
        WHEN file_name ILIKE '%2023%永續%' OR file_name ILIKE '%2023%sustain%' THEN '台泥2023永續報告書'
        WHEN file_name ILIKE '%2022%永續%' OR file_name ILIKE '%2022%sustain%' THEN '台泥2022永續報告書'
        WHEN file_name ILIKE '%2024%年報%' OR file_name ILIKE '%2024%annual%' THEN '台泥2024年度報告'
        WHEN file_name ILIKE '%2023%年報%' OR file_name ILIKE '%2023%annual%' THEN '台泥2023年度報告'
        WHEN file_name ILIKE '%2022%年報%' OR file_name ILIKE '%2022%annual%' THEN '台泥2022年度報告'
        ELSE file_name
    END,
    report_group = CASE
        WHEN file_name ILIKE '%永續%' OR file_name ILIKE '%sustain%' THEN '永續報告書'
        WHEN file_name ILIKE '%年報%' OR file_name ILIKE '%annual%' THEN '年度報告'
        ELSE category
    END
WHERE source_type = 'pdf'
  AND display_name IS NULL;

-- 2) URL 文件：根據 category 欄位設定 report_group（若 category 已有值）
UPDATE documents
SET report_group = category
WHERE source_type = 'url'
  AND report_group IS NULL
  AND category IS NOT NULL
  AND category != '其他';

-- 3) URL 文件：根據 URL 模式推斷 report_group（若 category 為空或「其他」）
UPDATE documents
SET report_group = CASE
        WHEN file_name ILIKE '%/esg/%' OR file_name ILIKE '%esg%' THEN 'ESG專區'
        WHEN file_name ILIKE '%news%' OR file_name ILIKE '%新聞%' THEN '新聞'
        WHEN file_name ILIKE '%newsletter%' OR file_name ILIKE '%電子報%' THEN '電子報'
        ELSE '官網'
    END
WHERE source_type = 'url'
  AND report_group IS NULL;

-- 4) URL 文件：display_name 用精簡的 URL path 作為顯示名稱
UPDATE documents
SET display_name = CASE
        WHEN file_name LIKE 'http%'
        THEN regexp_replace(
            regexp_replace(file_name, '^https?://[^/]+/', ''),
            '[?#].*$', ''
        )
        ELSE file_name
    END
WHERE display_name IS NULL;

-- 5) 驗證結果
SELECT id, file_name, display_name, report_group, category, source_type
FROM documents
ORDER BY source_type, report_group, display_name
LIMIT 30;
