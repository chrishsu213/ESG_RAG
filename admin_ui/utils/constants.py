"""
admin_ui/utils/constants.py
UI 選項常數 — 統一管理下拉選單選項清單。
"""

# ── 分類：四大群組 ──────────────────────────────────────────
CATEGORY_GROUPS: dict[str, list[str]] = {
    "永續相關報告": [
        "永續報告書",
        "法說會簡報",
    ],
    "財務相關報告": [
        "年度報告",
        "財務報告",
        "TCFD報告",
    ],
    "網站": [
        "官網",
        "ESG專區",
        "新聞",
        "電子報",
    ],
    "其他": [
        "公司政策文件",
        "監管框架",
        "同業資料",
        "研究報告",
        "會議紀錄",
        "其他",
    ],
}

# 展開為扁平清單（向下相容）
CATEGORY_OPTIONS: list[str] = [c for cats in CATEGORY_GROUPS.values() for c in cats]

# 需要顯示「季度」選單的分類
CATEGORY_WITH_QUARTER: set[str] = {"財務報告", "TCFD報告"}

# 需要顯示「發布日期」的分類（時效性內容）
CATEGORY_WITH_PUBLISH_DATE: set[str] = {"新聞", "電子報"}

# 其他選項
LANGUAGE_OPTIONS        = ["zh-TW", "en", "ja", "zh-CN"]
STATUS_OPTIONS          = ["已發布", "已審校", "草稿"]
CONFIDENTIALITY_OPTIONS = ["公開", "內部", "機密"]
FISCAL_PERIOD_OPTIONS   = ["Annual", "Q1", "Q2", "Q3", "Q4"]
TERM_CATEGORIES         = ["一般", "人名", "組織", "技術"]

# 年份快速選單（最近 8 年）
FISCAL_YEAR_OPTIONS: list[str] = [str(y) for y in range(2026, 2017, -1)]
