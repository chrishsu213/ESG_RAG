-- ==========================================
-- 修復 match_chunks_hybrid：移除所有舊版本，重建正確版本
-- 在 Supabase SQL Editor 中執行
-- ==========================================

-- 先列出所有 match_chunks_hybrid 的版本
SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE p.proname = 'match_chunks_hybrid'
  AND n.nspname = 'public';
