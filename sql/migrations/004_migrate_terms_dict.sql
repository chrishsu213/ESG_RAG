-- ==========================================
-- 專有名詞字典表
-- 用於錄音檔轉錄後自動替換專有名詞
-- 也可用於清洗階段的統一用語
-- ==========================================

CREATE TABLE IF NOT EXISTS terms_dictionary (
    id          BIGSERIAL PRIMARY KEY,
    term        TEXT NOT NULL UNIQUE,       -- 原始詞（如 "DAKA", "SBT"）
    full_name   TEXT NOT NULL,              -- 完整名稱（如 "台泥DAKA再生資源處理中心"）
    category    TEXT DEFAULT '一般',         -- 分類（一般 / 人名 / 組織 / 技術）
    language    TEXT DEFAULT 'zh-TW',       -- 語言
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 建立索引
CREATE INDEX IF NOT EXISTS idx_terms_term ON terms_dictionary (term);
CREATE INDEX IF NOT EXISTS idx_terms_category ON terms_dictionary (category);

-- 預設常用詞彙
INSERT INTO terms_dictionary (term, full_name, category) VALUES
    ('TCC',     '台泥集團 (TCC Group)',              '組織'),
    ('DAKA',    '台泥DAKA再生資源處理中心',            '組織'),
    ('SBT',     '科學基礎減碳目標 (Science Based Targets)', '技術'),
    ('SBTi',    '科學基礎減碳目標倡議組織 (SBTi)',      '組織'),
    ('TCFD',    '氣候相關財務揭露 (TCFD)',              '技術'),
    ('ISSB',    '國際永續準則理事會 (ISSB)',            '組織'),
    ('ESG',     '環境、社會與治理 (ESG)',               '技術'),
    ('CSRD',    '企業永續報告指令 (CSRD)',              '技術'),
    ('RE100',   '再生能源100% (RE100)',                '技術'),
    ('CBAM',    '碳邊境調整機制 (CBAM)',                '技術'),
    ('GRI',     '全球報告倡議組織 (GRI)',               '組織'),
    ('CDP',     '碳揭露計畫 (CDP)',                    '組織'),
    ('EBITDA',  '稅息折舊及攤銷前利潤 (EBITDA)',        '技術')
ON CONFLICT (term) DO NOTHING;
